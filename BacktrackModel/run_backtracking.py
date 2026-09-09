"""
run_backtracking.py
=====================
Stage-2, Brick 5: the actual backward Lagrangian run. Seeds particles from
the observed Sentinel-1 slick(s) at T_obs, then advects them BACKWARD in
time through historical currents + winds using OpenDrift/OpenOil, using
OpenDrift's own automatic global GSHHG landmask.

Key correctness points (do not "simplify" these away):
  1. Integrates over Observation.simulation_window (EXACT, unpadded window
     [T_obs - BACKTRACK_HOURS, T_obs]) -- never the padded search window.
  2. Converts timezone-AWARE UTC datetimes to NAIVE UTC only at the
     OpenDrift API boundary (seed_elements/run), since OpenDrift's readers
     store naive datetimes internally.
  3. Gates on inspect_environmental_data.check_readiness() FIRST -- refuses
     to run OpenDrift at all if the downloaded NetCDF files don't actually
     cover the simulation window, rather than letting OpenDrift silently
     clamp/extrapolate at the edges.

Depends on: pip install opendrift xarray netCDF4 numpy
(conda-forge is often smoother on Windows: conda install -c conda-forge opendrift)

Run directly:
    python run_backtracking.py
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np

import stage2_config as cfg
from prepare_observation import load_observation
from seed_particles import build_seed_points
from inspect_environmental_data import check_readiness

try:
    from opendrift.models.openoil import OpenOil
    from opendrift.readers import reader_netCDF_CF_generic
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "opendrift is required for run_backtracking.py.\n"
        "Install with: pip install opendrift\n"
        "(or, often more reliably on Windows: conda install -c conda-forge opendrift)"
    ) from exc


def _to_naive_utc(dt: datetime) -> datetime:
    """Converts a timezone-AWARE UTC datetime to naive, for the OpenDrift
    API boundary only. Raises if given a non-UTC datetime.
    """
    if dt.tzinfo is None:
        return dt
    if dt.utcoffset() != timezone.utc.utcoffset(dt):
        raise ValueError(f"Expected a UTC datetime, got offset {dt.utcoffset()} for {dt!r}.")
    return dt.replace(tzinfo=None)


def build_model() -> OpenOil:
    model = OpenOil(loglevel=cfg.OPENOIL_LOGLEVEL)
    model.set_config("general:use_auto_landmask", cfg.USE_OPENDRIFT_AUTO_LANDMASK)

    print(f"[run_backtracking] Adding currents reader: {cfg.CURRENTS_NC}")
    currents_reader = reader_netCDF_CF_generic.Reader(str(cfg.CURRENTS_NC))

    print(f"[run_backtracking] Adding winds reader: {cfg.WINDS_NC}")
    winds_reader = reader_netCDF_CF_generic.Reader(str(cfg.WINDS_NC))

    model.add_reader([currents_reader, winds_reader])
    return model


def seed_and_run_backward(model: OpenOil) -> Path:
    obs = load_observation()
    seeds = build_seed_points(obs)

    lons = np.array([s.lon for s in seeds])
    lats = np.array([s.lat for s in seeds])

    t_obs_naive = _to_naive_utc(obs.t_obs)

    print(f"[run_backtracking] Seeding {len(seeds)} particles at T_obs = "
          f"{obs.t_obs.isoformat()} (from {len(obs.features)} observed feature(s))")

    model.seed_elements(
        lon=lons,
        lat=lats,
        time=t_obs_naive,
        z=0.0,
        oil_type=cfg.OPENOIL_OIL_TYPE,
    )

    sim_start, sim_end = obs.simulation_window
    sim_start_naive = _to_naive_utc(sim_start)
    duration_hours = (sim_end - sim_start).total_seconds() / 3600.0

    print(f"[run_backtracking] Running BACKWARD for {duration_hours:.2f} hours "
          f"(target end time: {sim_start.isoformat()})")

    model.run(
        time_step=-cfg.BACKTRACK_TIME_STEP_MINUTES * 60,
        time_step_output=cfg.OUTPUT_TIME_STEP_MINUTES * 60,
        duration=None,
        end_time=sim_start_naive,
        outfile=str(cfg.BACKTRACK_TRAJECTORY_NC),
    )

    print(f"[run_backtracking] Wrote trajectory output -> {cfg.BACKTRACK_TRAJECTORY_NC}")
    return cfg.BACKTRACK_TRAJECTORY_NC


def run() -> Path:
    """Reusable entry point for run_stage2_pipeline.py. Returns the path to
    the written trajectory NetCDF.
    """
    is_ready, _report = check_readiness(verbose=False)
    if not is_ready:
        raise RuntimeError(
            "Environmental data does not cover the simulation window. "
            "Run 'python inspect_environmental_data.py' for full diagnostics "
            "before running the backward trajectory."
        )

    model = build_model()
    return seed_and_run_backward(model)


def main() -> None:
    trajectory_path = run()
    print(f"\nDONE. Trajectory written -> {trajectory_path}")
    print("NEXT: run generate_handoff.py to build the Stage-3-ready "
          "source-probability handoff package.")


if __name__ == "__main__":
    main()
