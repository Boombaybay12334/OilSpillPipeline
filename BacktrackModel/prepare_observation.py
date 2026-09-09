"""
prepare_observation.py
=======================
Stage-2, Brick 1: load the Stage-1 handoff (scene_metadata.json +
oil_regions.geojson) for ONE event, robustly (checking every candidate
metadata path from stage2_config.py), and compute the derived quantities
every later Stage-2 script needs.

Exposes TWO distinct time windows -- do not conflate them:

  - Observation.simulation_window: the EXACT window OpenDrift integrates
    over, [T_obs - BACKTRACK_HOURS, T_obs]. No padding. This is what
    run_backtracking.py uses as (end_time, seed_time).

  - Observation.search_time_window: simulation_window padded by
    TIME_PADDING_HOURS on both ends. Used ONLY to decide how much
    environmental data to download/inspect -- never passed to OpenDrift
    directly.

Run directly to sanity-check one event:
    python prepare_observation.py
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import stage2_config as cfg


@dataclass
class ObservationFeature:
    region_id: Any
    geometry: dict[str, Any]
    geometry_type: str
    centroid_lon: float
    centroid_lat: float
    area_km2: float | None
    mean_probability: float | None
    max_probability: float | None
    is_point_like: bool  # True for Point geometries / degenerate polygons


@dataclass
class Observation:
    event_id: str
    catalog_id: str | None
    t_start: datetime
    t_stop: datetime
    t_obs: datetime
    orbit_state: str | None
    features: list[ObservationFeature] = field(default_factory=list)

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """(west, south, east, north) over all features, unpadded."""
        lons = [f.centroid_lon for f in self.features]
        lats = [f.centroid_lat for f in self.features]
        for f in self.features:
            for lon, lat in _geometry_points(f.geometry):
                lons.append(lon)
                lats.append(lat)
        return min(lons), min(lats), max(lons), max(lats)

    @property
    def padded_bbox(self) -> tuple[float, float, float, float]:
        west, south, east, north = self.bbox
        pad = cfg.SPATIAL_PADDING_DEG
        return (
            max(-180.0, west - pad),
            max(-90.0, south - pad),
            min(180.0, east + pad),
            min(90.0, north + pad),
        )

    @property
    def simulation_window(self) -> tuple[datetime, datetime]:
        """The EXACT window OpenDrift will integrate over: no padding."""
        back = timedelta(hours=cfg.BACKTRACK_HOURS)
        return (self.t_obs - back, self.t_obs)

    @property
    def search_time_window(self) -> tuple[datetime, datetime]:
        """The PADDED window used only to decide how much environmental
        data to download. Always a superset of simulation_window.
        """
        pad = timedelta(hours=cfg.TIME_PADDING_HOURS)
        sim_start, sim_end = self.simulation_window
        return (sim_start - pad, sim_end + pad)

    def summary_dict(self) -> dict[str, Any]:
        west, south, east, north = self.padded_bbox
        sim_start, sim_end = self.simulation_window
        search_start, search_end = self.search_time_window
        n_point_like = sum(1 for f in self.features if f.is_point_like)
        return {
            "event_id": self.event_id,
            "catalog_id": self.catalog_id,
            "acquisition_start_utc": self.t_start.isoformat().replace("+00:00", "Z"),
            "acquisition_stop_utc": self.t_stop.isoformat().replace("+00:00", "Z"),
            "t_obs_utc": self.t_obs.isoformat().replace("+00:00", "Z"),
            "orbit_state": self.orbit_state,
            "num_features": len(self.features),
            "num_point_like_features": n_point_like,
            "unpadded_bbox_wsen": list(self.bbox),
            "padded_bbox_wsen": [west, south, east, north],
            "spatial_padding_deg": cfg.SPATIAL_PADDING_DEG,
            "backtrack_hours": cfg.BACKTRACK_HOURS,
            "time_padding_hours": cfg.TIME_PADDING_HOURS,
            "simulation_window_start_utc": sim_start.isoformat().replace("+00:00", "Z"),
            "simulation_window_end_utc": sim_end.isoformat().replace("+00:00", "Z"),
            "search_window_start_utc": search_start.isoformat().replace("+00:00", "Z"),
            "search_window_end_utc": search_end.isoformat().replace("+00:00", "Z"),
        }


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        if text.endswith("Z"):
            parsed = datetime.fromisoformat(text[:-1] + "+00:00")
        else:
            parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def _geometry_points(geometry: dict[str, Any]):
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if gtype == "Point" and isinstance(coords, list) and len(coords) >= 2:
        yield coords[0], coords[1]
    elif gtype == "Polygon":
        for ring in coords or []:
            for p in ring:
                if isinstance(p, list) and len(p) >= 2:
                    yield p[0], p[1]
    elif gtype == "MultiPolygon":
        for poly in coords or []:
            for ring in poly:
                for p in ring:
                    if isinstance(p, list) and len(p) >= 2:
                        yield p[0], p[1]


def find_scene_metadata() -> dict[str, Any] | None:
    """Checks every candidate path in stage2_config, in order, and returns
    the first one that parses. Returns None if none exist -- callers should
    then fall back to metadata embedded in the GeoJSON itself.
    """
    for candidate in cfg.SCENE_METADATA_CANDIDATES:
        if candidate.exists():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                print(f"[prepare_observation] Using scene_metadata.json: {candidate}")
                return data
            except Exception as exc:
                print(f"[prepare_observation] WARNING: {candidate} exists but failed to parse: {exc}")
    print("[prepare_observation] No scene_metadata.json found at any candidate path; "
          "falling back to GeoJSON 'metadata' block.")
    return None


def load_observation() -> Observation:
    """Loads and validates ONE event's Stage-1 handoff, per stage2_config.py.
    THIS is the sole entry point that reads Stage-1 output -- everything
    downstream in Stage 2 depends only on the Observation object it returns.
    """
    geojson_path = cfg.REGIONS_GEOJSON
    if not geojson_path.exists():
        raise FileNotFoundError(
            f"REGIONS_GEOJSON does not exist: {geojson_path}\n"
            f"Edit stage2_config.py -> REGIONS_GEOJSON for event '{cfg.EVENT_ID}'."
        )

    geojson = json.loads(geojson_path.read_text(encoding="utf-8"))
    if geojson.get("type") != "FeatureCollection":
        raise ValueError(f"{geojson_path} is not a GeoJSON FeatureCollection.")

    geojson_meta = geojson.get("metadata") if isinstance(geojson.get("metadata"), dict) else {}
    scene_meta = find_scene_metadata() or geojson_meta

    catalog_id = scene_meta.get("catalog_id") or geojson_meta.get("catalog_id")
    t_start = _parse_time(scene_meta.get("acquisition_start")) or _parse_time(geojson_meta.get("acquisition_start"))
    t_stop = _parse_time(scene_meta.get("acquisition_stop")) or _parse_time(geojson_meta.get("acquisition_stop"))
    orbit_state = scene_meta.get("orbit_state") or geojson_meta.get("orbit_state")

    if t_start is None or t_stop is None:
        raise ValueError(
            f"Could not resolve a valid acquisition_start/acquisition_stop for "
            f"event '{cfg.EVENT_ID}'. Checked scene_metadata candidates: "
            f"{[str(p) for p in cfg.SCENE_METADATA_CANDIDATES]} and the GeoJSON's "
            f"own 'metadata' block."
        )
    if t_stop < t_start:
        raise ValueError(f"acquisition_stop ({t_stop}) is before acquisition_start ({t_start}).")

    t_obs = t_start + (t_stop - t_start) / 2

    features: list[ObservationFeature] = []
    for feat in geojson.get("features", []):
        if not isinstance(feat, dict) or feat.get("type") != "Feature":
            continue
        geometry = feat.get("geometry") or {}
        gtype = geometry.get("type", "null")
        props = feat.get("properties") or {}

        points = list(_geometry_points(geometry))
        if not points:
            continue

        is_point_like = gtype == "Point"

        centroid_lon = props.get("centroid_lon")
        centroid_lat = props.get("centroid_lat")
        if centroid_lon is None or centroid_lat is None:
            centroid_lon = sum(p[0] for p in points) / len(points)
            centroid_lat = sum(p[1] for p in points) / len(points)

        features.append(ObservationFeature(
            region_id=props.get("region_id"),
            geometry=geometry,
            geometry_type=gtype,
            centroid_lon=float(centroid_lon),
            centroid_lat=float(centroid_lat),
            area_km2=props.get("area_km2"),
            mean_probability=props.get("mean_probability"),
            max_probability=props.get("max_probability"),
            is_point_like=is_point_like,
        ))

    if not features:
        raise ValueError(
            f"{geojson_path} contains zero usable features. Stage 2 needs at "
            f"least one observed slick to seed particles from -- this looks "
            f"like a control/no-spill scene, not a backtracking target."
        )

    return Observation(
        event_id=cfg.EVENT_ID,
        catalog_id=catalog_id,
        t_start=t_start,
        t_stop=t_stop,
        t_obs=t_obs,
        orbit_state=orbit_state,
        features=features,
    )


def main() -> None:
    obs = load_observation()
    summary = obs.summary_dict()

    cfg.OBSERVATION_SUMMARY_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\nEvent:              {obs.event_id}")
    print(f"Catalog ID:         {obs.catalog_id}")
    print(f"Acquisition start:  {summary['acquisition_start_utc']}")
    print(f"Acquisition stop:   {summary['acquisition_stop_utc']}")
    print(f"T_obs (midpoint):   {summary['t_obs_utc']}")
    print(f"Orbit state:        {obs.orbit_state}")
    print(f"Features total:     {summary['num_features']}  "
          f"(point-like: {summary['num_point_like_features']})")
    print(f"Unpadded bbox WSEN: {summary['unpadded_bbox_wsen']}")
    print(f"Padded bbox WSEN:   {summary['padded_bbox_wsen']}  "
          f"(padding={cfg.SPATIAL_PADDING_DEG} deg)")
    print(f"\nSIMULATION window (what OpenDrift actually integrates over, NO padding):")
    print(f"  {summary['simulation_window_start_utc']}  to  {summary['simulation_window_end_utc']}")
    print(f"SEARCH/download window (padded, for fetching env data only):")
    print(f"  {summary['search_window_start_utc']}  to  {summary['search_window_end_utc']}")
    print(f"\nWrote summary -> {cfg.OBSERVATION_SUMMARY_JSON}")


if __name__ == "__main__":
    main()
