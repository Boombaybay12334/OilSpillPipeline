"""
generate_handoff.py
=====================
Stage-2, Brick 6 (FINAL DELIVERABLE): turns the raw OpenDrift trajectory
NetCDF into the actual Stage-2 -> Stage-3 handoff package.

Stage 3 (AIS-based vessel scoring) should NEVER open the OpenDrift
trajectory NetCDF directly or depend on OpenDrift's internal schema. It
should consume ONLY the two files this script produces:

  1. <event>_stage2_handoff.json
     Structured, versioned JSON with:
       - observation summary (what was detected, when)
       - backtracking run configuration/provenance (so results are
         reproducible and their limitations are explicit)
       - one "origin_hypotheses" entry PER SAVED TIMESTEP, each with the
         top-N highest-probability grid cells and simple cumulative-
         probability coverage stats (how many cells / how large an area
         is needed to cover 50/75/90/95% of particles at that time)

  2. <event>_source_probability.geojson
     A lightweight GeoJSON FeatureCollection of grid cells (as small
     polygons) for a subsampled set of timesteps (every
     HANDOFF_GEOJSON_HOUR_STEP hours), each carrying its probability and
     timestamp as properties -- ready to load directly into QGIS or a web
     map, or to intersect against AIS positions in Stage 3.

Design intent: Stage 3 should query "what is the probability of this
being the origin, at this vessel's observed time and position?" by
looking up the nearest snapshot in origin_hypotheses (by time) and the
nearest grid cell (by position) -- no OpenDrift/xarray knowledge required.

Run:
    python generate_handoff.py

Depends on: pip install xarray numpy
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

import stage2_config as cfg
from prepare_observation import load_observation


def _find_var_name(ds: xr.Dataset, candidates: list[str]) -> str | None:
    available = list(ds.data_vars) + list(ds.coords)
    lower_map = {name.lower(): name for name in available}
    for candidate in candidates:
        if candidate.lower() in lower_map:
            return lower_map[candidate.lower()]
    return None


def _as_utc(dt64: np.datetime64) -> datetime:
    return dt64.astype("datetime64[s]").astype(datetime).replace(tzinfo=timezone.utc)


def _density_grid(lons: np.ndarray, lats: np.ndarray, grid_deg: float):
    lon_bins = np.arange(lons.min() - grid_deg, lons.max() + 2 * grid_deg, grid_deg)
    lat_bins = np.arange(lats.min() - grid_deg, lats.max() + 2 * grid_deg, grid_deg)
    counts, lon_edges, lat_edges = np.histogram2d(lons, lats, bins=[lon_bins, lat_bins])
    return counts, lon_edges, lat_edges


def _cells_from_grid(counts: np.ndarray, lon_edges: np.ndarray, lat_edges: np.ndarray,
                      total_particles: int) -> list[dict[str, Any]]:
    cells = []
    for i in range(counts.shape[0]):
        for j in range(counts.shape[1]):
            c = int(counts[i, j])
            if c == 0:
                continue
            cells.append({
                "lon_center": float((lon_edges[i] + lon_edges[i + 1]) / 2),
                "lat_center": float((lat_edges[j] + lat_edges[j + 1]) / 2),
                "lon_min": float(lon_edges[i]),
                "lon_max": float(lon_edges[i + 1]),
                "lat_min": float(lat_edges[j]),
                "lat_max": float(lat_edges[j + 1]),
                "particle_count": c,
                "probability": c / float(total_particles) if total_particles else 0.0,
            })
    cells.sort(key=lambda cell: cell["particle_count"], reverse=True)
    return cells


def _cumulative_coverage(cells: list[dict[str, Any]], thresholds: list[float]) -> list[dict[str, Any]]:
    """For each threshold (e.g. 0.90), reports the minimum number of
    highest-probability cells whose cumulative probability reaches that
    threshold, and the bounding box covering those cells. This is a
    lightweight substitute for a true alpha-shape/contour polygon -- honest
    about being a bounding box, not a tight contour.
    """
    results = []
    cumulative = 0.0
    included = 0
    bbox = [180.0, 90.0, -180.0, -90.0]  # west, south, east, north
    threshold_iter = iter(sorted(thresholds))
    next_threshold = next(threshold_iter, None)

    for cell in cells:
        cumulative += cell["probability"]
        included += 1
        bbox[0] = min(bbox[0], cell["lon_min"])
        bbox[1] = min(bbox[1], cell["lat_min"])
        bbox[2] = max(bbox[2], cell["lon_max"])
        bbox[3] = max(bbox[3], cell["lat_max"])

        while next_threshold is not None and cumulative >= next_threshold:
            results.append({
                "threshold": next_threshold,
                "num_cells": included,
                "cumulative_probability": round(cumulative, 4),
                "bbox_wsen": list(bbox),
            })
            next_threshold = next(threshold_iter, None)

    return results


def build_origin_hypotheses(trajectory_path: Path, t_obs: datetime) -> list[dict[str, Any]]:
    ds = xr.open_dataset(trajectory_path)
    try:
        lon_name = _find_var_name(ds, ["lon", "longitude"])
        lat_name = _find_var_name(ds, ["lat", "latitude"])
        time_name = _find_var_name(ds, ["time"])
        if lon_name is None or lat_name is None or time_name is None:
            raise KeyError(
                f"Could not find lon/lat/time in trajectory file. "
                f"data_vars={list(ds.data_vars)}, coords={list(ds.coords)}"
            )

        lon = ds[lon_name].values  # shape (trajectory, time)
        lat = ds[lat_name].values
        times = ds[time_name].values  # shape (time,)

        hypotheses = []
        n_steps = lon.shape[1]
        for t_idx in range(n_steps):
            step_lon = lon[:, t_idx]
            step_lat = lat[:, t_idx]
            valid = np.isfinite(step_lon) & np.isfinite(step_lat)
            step_lon = step_lon[valid]
            step_lat = step_lat[valid]

            time_utc = _as_utc(times[t_idx])
            hours_before_obs = (t_obs - time_utc).total_seconds() / 3600.0

            if step_lon.size == 0:
                hypotheses.append({
                    "time_utc": time_utc.isoformat().replace("+00:00", "Z"),
                    "hours_before_observation": round(hours_before_obs, 3),
                    "active_particles": 0,
                    "top_cells": [],
                    "coverage_thresholds": [],
                })
                continue

            counts, lon_edges, lat_edges = _density_grid(step_lon, step_lat, cfg.DENSITY_GRID_DEG)
            cells = _cells_from_grid(counts, lon_edges, lat_edges, int(step_lon.size))
            coverage = _cumulative_coverage(cells, cfg.DENSITY_CONTOUR_THRESHOLDS)

            hypotheses.append({
                "time_utc": time_utc.isoformat().replace("+00:00", "Z"),
                "hours_before_observation": round(hours_before_obs, 3),
                "active_particles": int(step_lon.size),
                "grid_resolution_deg": cfg.DENSITY_GRID_DEG,
                "top_cells": [
                    {"rank": rank + 1, **{k: v for k, v in cell.items() if k not in
                     ("lon_min", "lon_max", "lat_min", "lat_max")}}
                    for rank, cell in enumerate(cells[:cfg.TOP_N_CELLS_PER_SNAPSHOT])
                ],
                "coverage_thresholds": coverage,
            })

        # Ensure chronological order (earliest first) for readability,
        # regardless of how OpenDrift ordered the output for a backward run.
        hypotheses.sort(key=lambda h: h["time_utc"])
        return hypotheses
    finally:
        ds.close()


def build_geojson(origin_hypotheses: list[dict[str, Any]], trajectory_path: Path) -> dict[str, Any]:
    """Rebuilds cell polygons (with full bbox, not just center) for a
    subsampled set of snapshots, for lightweight GIS visualization /
    Stage-3 spatial queries that want actual polygons rather than JSON cell
    centers.
    """
    ds = xr.open_dataset(trajectory_path)
    try:
        lon_name = _find_var_name(ds, ["lon", "longitude"])
        lat_name = _find_var_name(ds, ["lat", "latitude"])
        time_name = _find_var_name(ds, ["time"])
        lon = ds[lon_name].values
        lat = ds[lat_name].values
        times = ds[time_name].values
    finally:
        ds.close()

    features = []
    step = max(1, cfg.HANDOFF_GEOJSON_HOUR_STEP)
    n_steps = lon.shape[1]

    # Pick indices spaced roughly every `step` hours based on actual
    # elapsed time between consecutive saved steps, not just index count.
    time_utcs = [_as_utc(t) for t in times]
    kept_indices = [0]
    for idx in range(1, n_steps):
        hours_since_last_kept = abs((time_utcs[idx] - time_utcs[kept_indices[-1]]).total_seconds()) / 3600.0
        if hours_since_last_kept >= step:
            kept_indices.append(idx)
    if kept_indices[-1] != n_steps - 1:
        kept_indices.append(n_steps - 1)

    for t_idx in kept_indices:
        step_lon = lon[:, t_idx]
        step_lat = lat[:, t_idx]
        valid = np.isfinite(step_lon) & np.isfinite(step_lat)
        step_lon = step_lon[valid]
        step_lat = step_lat[valid]
        if step_lon.size == 0:
            continue

        time_utc_iso = time_utcs[t_idx].isoformat().replace("+00:00", "Z")
        counts, lon_edges, lat_edges = _density_grid(step_lon, step_lat, cfg.DENSITY_GRID_DEG)
        cells = _cells_from_grid(counts, lon_edges, lat_edges, int(step_lon.size))

        for rank, cell in enumerate(cells[:cfg.TOP_N_CELLS_PER_SNAPSHOT]):
            ring = [
                [cell["lon_min"], cell["lat_min"]],
                [cell["lon_max"], cell["lat_min"]],
                [cell["lon_max"], cell["lat_max"]],
                [cell["lon_min"], cell["lat_max"]],
                [cell["lon_min"], cell["lat_min"]],
            ]
            features.append({
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [ring]},
                "properties": {
                    "time_utc": time_utc_iso,
                    "rank": rank + 1,
                    "particle_count": cell["particle_count"],
                    "probability": round(cell["probability"], 4),
                },
            })

    return {"type": "FeatureCollection", "features": features}


def build_handoff_document(origin_hypotheses: list[dict[str, Any]]) -> dict[str, Any]:
    obs = load_observation()
    sim_start, sim_end = obs.simulation_window

    return {
        "schema_version": "1.0",
        "event_id": cfg.EVENT_ID,
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "observation": {
            "catalog_id": obs.catalog_id,
            "t_obs_utc": obs.t_obs.isoformat().replace("+00:00", "Z"),
            "acquisition_start_utc": obs.t_start.isoformat().replace("+00:00", "Z"),
            "acquisition_stop_utc": obs.t_stop.isoformat().replace("+00:00", "Z"),
            "orbit_state": obs.orbit_state,
            "num_detected_regions": len(obs.features),
            "num_polygon_regions": sum(1 for f in obs.features if not f.is_point_like),
            "num_point_like_regions": sum(1 for f in obs.features if f.is_point_like),
            "unpadded_bbox_wsen": list(obs.bbox),
        },
        "backtracking": {
            "method": "OpenDrift/OpenOil deterministic backward Lagrangian tracking",
            "opendrift_version_note": "Verify against your installed 'opendrift' package version.",
            "trajectory_file": cfg.BACKTRACK_TRAJECTORY_NC.name,
            "simulation_start_utc": sim_start.isoformat().replace("+00:00", "Z"),
            "simulation_end_utc": sim_end.isoformat().replace("+00:00", "Z"),
            "backtrack_hours": cfg.BACKTRACK_HOURS,
            "initial_seed_particles": (
                len([f for f in obs.features if not f.is_point_like]) * cfg.PARTICLES_PER_FEATURE
                + len([f for f in obs.features if f.is_point_like]) * cfg.PARTICLES_PER_POINT_FEATURE
            ),
            "current_forcing": {
                "provider": "CMEMS GLORYS12V1 (cmems_mod_glo_phy_my_0.083deg_P1D-m)",
                "variables": ["uo", "vo"],
                "nominal_temporal_resolution_hours": 24,
            },
            "wind_forcing": {
                "provider": "ERA5 (reanalysis-era5-single-levels)",
                "variables": ["u10", "v10"],
                "nominal_temporal_resolution_hours": 1,
            },
            "landmask": "OpenDrift automatic global GSHHG" if cfg.USE_OPENDRIFT_AUTO_LANDMASK else "custom",
            "oil_type": cfg.OPENOIL_OIL_TYPE,
            "density_grid_resolution_deg": cfg.DENSITY_GRID_DEG,
        },
        "origin_hypotheses": origin_hypotheses,
        "limitations": [
            "Single deterministic backward run, not an ensemble posterior -- "
            "no uncertainty from current/wind perturbation, windage, or "
            "diffusion variation is represented yet.",
            "Ocean current forcing (GLORYS12V1) is DAILY resolution; this is "
            "likely the largest source of trajectory uncertainty.",
            "No wave/Stokes-drift forcing included.",
            "No release duration, oil volume, or oil-type inference performed "
            "-- 'oil_type' above is an assumed forward-model input, not an "
            "inferred property of the actual spill.",
            "'top_cells'/'coverage_thresholds' bounding boxes are NOT tight "
            "contour polygons -- they are grid-cell-based approximations.",
            "This handoff describes CANDIDATE origin regions, not a validated "
            "or confirmed release location. Any vessel scoring built on this "
            "data indicates spatial-temporal COMPATIBILITY with the modeled "
            "drift, not proof of responsibility.",
        ],
    }


def main() -> None:
    if not cfg.BACKTRACK_TRAJECTORY_NC.exists():
        raise FileNotFoundError(
            f"Trajectory file not found: {cfg.BACKTRACK_TRAJECTORY_NC}\n"
            f"Run run_backtracking.py first."
        )

    obs = load_observation()
    print(f"[generate_handoff] Reading trajectory: {cfg.BACKTRACK_TRAJECTORY_NC}")
    origin_hypotheses = build_origin_hypotheses(cfg.BACKTRACK_TRAJECTORY_NC, obs.t_obs)

    handoff_doc = build_handoff_document(origin_hypotheses)
    cfg.STAGE2_HANDOFF_JSON.write_text(json.dumps(handoff_doc, indent=2), encoding="utf-8")
    print(f"[generate_handoff] Wrote -> {cfg.STAGE2_HANDOFF_JSON}")

    geojson_doc = build_geojson(origin_hypotheses, cfg.BACKTRACK_TRAJECTORY_NC)
    cfg.SOURCE_PROBABILITY_GEOJSON.write_text(json.dumps(geojson_doc, indent=2), encoding="utf-8")
    print(f"[generate_handoff] Wrote -> {cfg.SOURCE_PROBABILITY_GEOJSON} "
          f"({len(geojson_doc['features'])} features)")

    print(f"\nSnapshots in handoff: {len(origin_hypotheses)}")
    print(f"Earliest snapshot:    {origin_hypotheses[0]['time_utc']} "
          f"({origin_hypotheses[0]['hours_before_observation']:.1f}h before T_obs)")
    print(f"Latest snapshot:      {origin_hypotheses[-1]['time_utc']} "
          f"({origin_hypotheses[-1]['hours_before_observation']:.1f}h before T_obs)")

    print("\nSTAGE 2 COMPLETE. Stage 3 should consume ONLY these two files:")
    print(f"  {cfg.STAGE2_HANDOFF_JSON}")
    print(f"  {cfg.SOURCE_PROBABILITY_GEOJSON}")


if __name__ == "__main__":
    main()
