"""
run_stage2_pipeline.py
========================
THE single entry point for Stage 2. Run this one script to go from the
Stage-1 handoff (oil_regions.geojson + scene_metadata.json, as configured
in stage2_config.py) all the way to the Stage-3-ready deliverables.

    Stage-1 oil_regions.geojson
        |
        v
    [1] prepare_observation   -> T_obs, bbox, simulation window
        |
        v
    [2] fetch_environmental_data -> currents.nc, winds.nc (skips if cached)
        |
        v
    [3] inspect_environmental_data -> gate: refuses to continue if coverage
        |                             is insufficient
        v
    [4] run_backtracking      -> OpenDrift/OpenOil backward run -> trajectory.nc
        |
        v
    [5] generate_handoff      -> stage2_handoff.json + source_probability.geojson
        |
        v
    STAGE 3 (AIS vessel scoring) starts here -- not part of this script.

Usage:
    python run_stage2_pipeline.py

Every step is idempotent / cache-aware:
  - fetch_environmental_data skips downloads if the target .nc already exists
  - run_backtracking will overwrite the trajectory file each run (deterministic
    given the same seeds/config, so this is safe and expected)
  - generate_handoff always regenerates its two output files

If you only want to re-run FROM a certain step (e.g. you already have
env_data and just changed BACKTRACK_TIME_STEP_MINUTES), just run the
individual script for that step and everything after it, instead of this
whole orchestrator. Each individual script remains fully usable standalone.
"""

from __future__ import annotations

import sys
import time


def _run_step(step_number: int, step_name: str, func) -> None:
    print("\n" + "#" * 88)
    print(f"# STEP {step_number}: {step_name}")
    print("#" * 88)
    started = time.time()
    func()
    elapsed = time.time() - started
    print(f"# STEP {step_number} done in {elapsed:.1f}s")


def main() -> None:
    import stage2_config as cfg
    import prepare_observation
    import fetch_environmental_data
    import inspect_environmental_data
    import run_backtracking
    import generate_handoff

    print(f"Stage-2 pipeline starting for event: {cfg.EVENT_ID}")
    print(f"Stage-1 input GeoJSON: {cfg.REGIONS_GEOJSON}")

    if not cfg.REGIONS_GEOJSON.exists():
        print(f"\nERROR: Stage-1 input not found: {cfg.REGIONS_GEOJSON}")
        print("Edit stage2_config.py -> SCENE_OUT_DIR / REGIONS_GEOJSON and retry.")
        sys.exit(1)

    _run_step(1, "prepare_observation", prepare_observation.main)
    _run_step(2, "fetch_environmental_data", fetch_environmental_data.main)

    is_ready, _report = inspect_environmental_data.check_readiness(verbose=True)
    if not is_ready:
        print("\nERROR: environmental data does not cover the required simulation "
              "window. Run 'python inspect_environmental_data.py' for full "
              "diagnostics, adjust stage2_config.py (e.g. shrink BACKTRACK_HOURS, "
              "or delete the .nc files to re-fetch a wider window), and re-run "
              "this pipeline.")
        sys.exit(1)
    print("[STEP 3] Environmental data readiness: PASS")

    _run_step(4, "run_backtracking", run_backtracking.run)
    _run_step(5, "generate_handoff", generate_handoff.main)

    print("\n" + "=" * 88)
    print("STAGE 2 PIPELINE COMPLETE")
    print("=" * 88)
    print("Hand these two files to Stage 3:")
    print(f"  {cfg.STAGE2_HANDOFF_JSON}")
    print(f"  {cfg.SOURCE_PROBABILITY_GEOJSON}")


if __name__ == "__main__":
    main()
