"""
inspect_environmental_data.py
==============================
Stage-2, Brick 3: verify the two downloaded environmental NetCDF files
BEFORE OpenDrift is allowed to use them.

Validates coverage against Observation.simulation_window (the exact,
UNPADDED window OpenDrift will integrate over), not the padded
search_time_window used only for deciding how much data to download.

check_readiness() is the reusable entry point (used by run_stage2_pipeline.py
to gate the backtracking step); main() wraps it for standalone CLI use and
also writes the full diagnostic JSON report.

This reads only. It never modifies either downloaded NetCDF file.

Run:
    python inspect_environmental_data.py

Depends on:
    pip install xarray netCDF4 numpy pandas
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr

import stage2_config as cfg
from prepare_observation import load_observation


CURRENT_U_CANDIDATES = ["uo", "water_u", "u", "eastward_sea_water_velocity", "x_sea_water_velocity"]
CURRENT_V_CANDIDATES = ["vo", "water_v", "v", "northward_sea_water_velocity", "y_sea_water_velocity"]
WIND_U_CANDIDATES = ["u10", "10u", "10m_u_component_of_wind", "x_wind"]
WIND_V_CANDIDATES = ["v10", "10v", "10m_v_component_of_wind", "y_wind"]
TIME_CANDIDATES = ["time", "valid_time", "forecast_time"]
LAT_CANDIDATES = ["latitude", "lat", "nav_lat", "y"]
LON_CANDIDATES = ["longitude", "lon", "nav_lon", "x"]


def find_name(candidates: list[str], available: list[str]) -> str | None:
    lower_map = {name.lower(): name for name in available}
    for candidate in candidates:
        if candidate.lower() in lower_map:
            return lower_map[candidate.lower()]
    return None


def as_utc_timestamp(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def infer_nominal_step(times: pd.DatetimeIndex) -> tuple[str, float | None, list[float]]:
    if len(times) < 2:
        return "not enough time points", None, []
    seconds = np.diff(times.asi8) / 1e9
    unique, counts = np.unique(seconds, return_counts=True)
    nominal = float(unique[np.argmax(counts)])
    return f"{nominal / 3600:.3f} hours", nominal, [float(v) for v in unique]


def variable_stats(da: xr.DataArray) -> dict[str, Any]:
    values = da.values
    finite = np.isfinite(values)
    finite_count = int(finite.sum())
    total_count = int(values.size)
    result: dict[str, Any] = {
        "dims": list(da.dims),
        "shape": list(da.shape),
        "units": da.attrs.get("units"),
        "long_name": da.attrs.get("long_name"),
        "standard_name": da.attrs.get("standard_name"),
        "finite_count": finite_count,
        "total_count": total_count,
        "finite_fraction": (finite_count / total_count) if total_count else 0.0,
    }
    if finite_count:
        finite_values = values[finite]
        result.update({
            "min": float(np.nanmin(finite_values)),
            "max": float(np.nanmax(finite_values)),
            "mean": float(np.nanmean(finite_values)),
        })
    return result


def inspect_file(path: Path, kind: str, verbose: bool = True) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Missing {kind} NetCDF: {path}")

    if verbose:
        print("\n" + "=" * 88)
        print(f"{kind.upper()} NETCDF")
        print("=" * 88)
        print(f"Path: {path}")
        print(f"File size: {path.stat().st_size / 1024:.2f} KiB")

    ds = xr.open_dataset(path)
    try:
        if verbose:
            print(f"Dimensions: {dict(ds.sizes)}")
            print(f"Coordinates: {list(ds.coords)}")
            print(f"Data variables: {list(ds.data_vars)}")

        all_names = list(ds.coords) + list(ds.data_vars)
        time_name = find_name(TIME_CANDIDATES, all_names)
        lat_name = find_name(LAT_CANDIDATES, all_names)
        lon_name = find_name(LON_CANDIDATES, all_names)

        if kind == "currents":
            u_name = find_name(CURRENT_U_CANDIDATES, list(ds.data_vars))
            v_name = find_name(CURRENT_V_CANDIDATES, list(ds.data_vars))
        else:
            u_name = find_name(WIND_U_CANDIDATES, list(ds.data_vars))
            v_name = find_name(WIND_V_CANDIDATES, list(ds.data_vars))

        if verbose:
            print(f"Detected time coordinate: {time_name}")
            print(f"Detected latitude coordinate: {lat_name}")
            print(f"Detected longitude coordinate: {lon_name}")
            print(f"Detected eastward component: {u_name}")
            print(f"Detected northward component: {v_name}")

        summary: dict[str, Any] = {
            "path": str(path),
            "kind": kind,
            "file_size_bytes": path.stat().st_size,
            "dimensions": {key: int(value) for key, value in ds.sizes.items()},
            "coordinates": list(ds.coords),
            "data_variables": list(ds.data_vars),
            "detected": {"time": time_name, "latitude": lat_name, "longitude": lon_name, "u": u_name, "v": v_name},
        }

        if time_name is None:
            if verbose:
                print("[FAIL] No recognised time coordinate.")
        else:
            raw_times = pd.DatetimeIndex(pd.to_datetime(ds[time_name].values))
            times = pd.DatetimeIndex([as_utc_timestamp(t).tz_localize(None) for t in raw_times])
            start = pd.Timestamp(times.min()).tz_localize("UTC")
            end = pd.Timestamp(times.max()).tz_localize("UTC")
            step_label, nominal_step_seconds, unique_steps = infer_nominal_step(times)
            monotonic = bool(np.all(np.diff(times.asi8) > 0)) if len(times) > 1 else True
            gaps = []
            if nominal_step_seconds is not None:
                gaps = [float(x) for x in (np.diff(times.asi8) / 1e9) if x > nominal_step_seconds * 1.5]

            if verbose:
                print(f"Time count: {len(times)}")
                print(f"Time start: {start.isoformat()}")
                print(f"Time end:   {end.isoformat()}")
                print(f"Nominal time step: {step_label}")
                print(f"Gaps > 1.5x nominal step: {len(gaps)}" + (f" -> {gaps}" if gaps else ""))

            summary["time"] = {
                "count": len(times), "start_utc": start.isoformat(), "end_utc": end.isoformat(),
                "monotonic_increasing": monotonic, "nominal_step_seconds": nominal_step_seconds,
                "gap_intervals_seconds": gaps,
            }

        for coord_name, axis in ((lat_name, "latitude"), (lon_name, "longitude")):
            if coord_name is None:
                continue
            values = np.asarray(ds[coord_name].values)
            finite = values[np.isfinite(values)]
            if finite.size:
                if verbose:
                    print(f"{axis.title()} range: {float(finite.min()):.6f} to {float(finite.max()):.6f}")
                summary[axis] = {"name": coord_name, "min": float(finite.min()), "max": float(finite.max())}

        summary["component_statistics"] = {}
        for component_name, label in ((u_name, "eastward"), (v_name, "northward")):
            if component_name is None:
                continue
            stats = variable_stats(ds[component_name])
            summary["component_statistics"][label] = {"name": component_name, **stats}
            if verbose:
                print(f"{label.title()} component '{component_name}': "
                      f"units={stats['units']!r}, finite={stats['finite_fraction']:.4f}, "
                      f"min={stats.get('min')}, max={stats.get('max')}, mean={stats.get('mean')}")

        return summary
    finally:
        ds.close()


def coverage_check(summary: dict[str, Any], required_start: datetime, required_end: datetime) -> tuple[bool, str]:
    time_info = summary.get("time")
    if not time_info:
        return False, "no time coordinate detected"
    available_start = as_utc_timestamp(time_info["start_utc"]).to_pydatetime()
    available_end = as_utc_timestamp(time_info["end_utc"]).to_pydatetime()
    ok = available_start <= required_start and available_end >= required_end
    if ok:
        return True, "covers required window"
    shortfall_start = max((required_start - available_start).total_seconds(), 0) / 3600
    shortfall_end = max((required_end - available_end).total_seconds(), 0) / 3600
    return False, (f"available [{available_start.isoformat()} .. {available_end.isoformat()}] "
                    f"vs required [{required_start.isoformat()} .. {required_end.isoformat()}] "
                    f"-- short by {shortfall_start:.2f}h at start, {shortfall_end:.2f}h at end")


def check_readiness(verbose: bool = True) -> tuple[bool, dict[str, Any]]:
    """Reusable entry point: returns (is_ready, full_report_dict). Used by
    run_stage2_pipeline.py to gate the backtracking step, and by main()
    below for standalone CLI use.
    """
    obs = load_observation()
    sim_start, sim_end = obs.simulation_window
    search_start, search_end = obs.search_time_window

    current_summary = inspect_file(cfg.CURRENTS_NC, "currents", verbose=verbose)
    wind_summary = inspect_file(cfg.WINDS_NC, "winds", verbose=verbose)

    currents_ok, currents_detail = coverage_check(current_summary, sim_start, sim_end)
    winds_ok, winds_detail = coverage_check(wind_summary, sim_start, sim_end)
    current_names = current_summary["detected"]
    wind_names = wind_summary["detected"]
    pair_ok = bool(current_names["u"] and current_names["v"] and wind_names["u"] and wind_names["v"])

    is_ready = currents_ok and winds_ok and pair_ok

    report = {
        "event_id": cfg.EVENT_ID,
        "simulation_window_start_utc": sim_start.isoformat().replace("+00:00", "Z"),
        "simulation_window_end_utc": sim_end.isoformat().replace("+00:00", "Z"),
        "search_window_start_utc": search_start.isoformat().replace("+00:00", "Z"),
        "search_window_end_utc": search_end.isoformat().replace("+00:00", "Z"),
        "currents": current_summary,
        "winds": wind_summary,
        "readiness": {
            "currents_cover_simulation_window": currents_ok,
            "currents_detail": currents_detail,
            "winds_cover_simulation_window": winds_ok,
            "winds_detail": winds_detail,
            "component_pairs_recognised": pair_ok,
            "overall_ready": is_ready,
        },
    }

    if verbose:
        print("\n" + "=" * 88)
        print("STAGE-2 READINESS DECISION")
        print("=" * 88)
        print(f"SIMULATION window: {sim_start.isoformat()}  to  {sim_end.isoformat()}")
        print(f"[{'PASS' if currents_ok else 'FAIL'}] Currents cover SIMULATION window -- {currents_detail}")
        print(f"[{'PASS' if winds_ok else 'FAIL'}] Winds cover SIMULATION window -- {winds_detail}")
        print(f"[{'PASS' if pair_ok else 'FAIL'}] Current/wind u-v component pairs recognised")

    return is_ready, report


def main() -> None:
    is_ready, report = check_readiness(verbose=True)
    cfg.ENV_DATA_INSPECTION_JSON.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote inspection report -> {cfg.ENV_DATA_INSPECTION_JSON}")
    if is_ready:
        print("\nREADY: proceed to run_backtracking.py.")
    else:
        print("\nNOT READY: adjust BACKTRACK_HOURS in stage2_config.py (shrink it) "
              "or re-fetch data with a wider window, then re-run this script.")


if __name__ == "__main__":
    main()
