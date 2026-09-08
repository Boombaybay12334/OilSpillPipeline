"""
stage2_config.py
=================
Single source of truth for ALL Stage-2 (source/time backtracking) paths and
settings.

STAGE-2 IS FULLY STANDALONE:
  - It does NOT import, reference, or require Model/, SNAP, a .SAFE folder,
    scene_out_sanchi/, Stage-1 code, classifier checkpoints, or training data.
  - Its only Stage-1 input is one copied GeoJSON file:
        BacktrackModel/inputs/oil_regions.geojson
  - The GeoJSON already contains top-level `metadata` with acquisition_start,
    acquisition_stop, catalog_id, orbit_state, etc. Therefore a separate
    scene_metadata.json is OPTIONAL, not required.
  - Everything Stage 2 creates stays inside:
        BacktrackModel/stage2_outputs/<event_id>/

For a new event later:
  1. Replace inputs/oil_regions.geojson with that event's Stage-1 GeoJSON.
  2. Change EVENT_ID below.
  3. Optionally change BACKTRACK_HOURS / oil type / particle settings.
  4. Run: python run_stage2_pipeline.py

No other Python file should need path edits for a normal run.
"""

import os
from pathlib import Path

# =============================================================================
# USER SETTINGS -- EDIT PER EVENT
# =============================================================================

# A short label used only for Stage-2 cache/output filenames.
EVENT_ID = "sanchi_2018"

# The directory containing THIS config file: .../BacktrackModel/
THIS_DIR = Path(__file__).resolve().parent

# -----------------------------------------------------------------------------
# INPUT FROM STAGE 1 -- THIS IS THE ONLY REQUIRED EXTERNAL INPUT
# -----------------------------------------------------------------------------
# Copy Stage-1's final oil_regions.geojson into BacktrackModel/inputs/.
# Do NOT point this at Model/, scene_out_sanchi/, a SAFE folder, or old paths.
INPUT_DIR = THIS_DIR / "inputs"
REGIONS_GEOJSON = INPUT_DIR / "oil_regions.geojson"

# OPTIONAL ONLY. Leave this list empty for the current standalone design.
# prepare_observation.py will use the GeoJSON's own top-level `metadata` block.
# If a future Stage-1 version outputs a separate scene_metadata.json and you
# want Stage 2 to prefer it, copy it into inputs/ and uncomment the line:
# SCENE_METADATA_CANDIDATES = [INPUT_DIR / "scene_metadata.json"]
SCENE_METADATA_CANDIDATES = []

# -----------------------------------------------------------------------------
# Coastline / landmask
# -----------------------------------------------------------------------------
# V1 uses OpenDrift's automatic global GSHHG landmask. No NOAA archive, local
# shapefile, or manual landmask path is required for the working prototype.
USE_OPENDRIFT_AUTO_LANDMASK = True

# Reserved for a later high-resolution local-coastline validation pass only.
# It is NOT read by the current V1 scripts.
GSHHG_ARCHIVE_ROOT = None
GSHHG_RESOLUTION = "h"

# -----------------------------------------------------------------------------
# Stage-2 outputs (auto-created; do not move these into Stage 1)
# -----------------------------------------------------------------------------
STAGE2_ROOT = THIS_DIR / "stage2_outputs"
STAGE2_EVENT_DIR = STAGE2_ROOT / EVENT_ID
ENV_DATA_DIR = STAGE2_EVENT_DIR / "env_data"
COASTLINE_DIR = STAGE2_EVENT_DIR / "coastline"
TRAJECTORY_DIR = STAGE2_EVENT_DIR / "trajectories"
REPORT_DIR = STAGE2_EVENT_DIR / "reports"

# -----------------------------------------------------------------------------
# Backtracking search window
# -----------------------------------------------------------------------------
# Exact integration interval is:
#   [T_obs - BACKTRACK_HOURS, T_obs]
#
# 69 hours is the validated value for the already-downloaded Sanchi currents.
# For a NEW event, start with 48-72 then run inspect_environmental_data.py.
# If it says current coverage is insufficient, either shrink this number OR
# delete that event's cached currents .nc file and let the fetcher re-download.
BACKTRACK_HOURS = 69

# Used ONLY when downloading currents/winds, never as extra model runtime.
TIME_PADDING_HOURS = 12

# Extra geographic margin around all observed slick polygons when fetching
# currents/winds. Increase for longer/faster open-ocean scenarios.
SPATIAL_PADDING_DEG = 2.0

# -----------------------------------------------------------------------------
# Particle seeding
# -----------------------------------------------------------------------------
PARTICLES_PER_FEATURE = 200        # per observed Polygon slick region
PARTICLES_PER_POINT_FEATURE = 50   # per degenerate Point detection
POINT_FEATURE_RADIUS_M = 250.0     # uncertainty disk radius for Point seeds
SEED_RNG = 42                      # reproducible sampling

# -----------------------------------------------------------------------------
# OpenDrift / OpenOil model settings
# -----------------------------------------------------------------------------
OPENOIL_OIL_TYPE = "GENERIC HEAVY CRUDE"  # assumed scenario, not inferred
OPENOIL_LOGLEVEL = 20               # 20 = INFO, 0 = DEBUG / very verbose
BACKTRACK_TIME_STEP_MINUTES = 15    # numerical integration step
OUTPUT_TIME_STEP_MINUTES = 60       # saved trajectory snapshot interval

# -----------------------------------------------------------------------------
# Stage-2 -> Stage-3 AIS handoff settings
# -----------------------------------------------------------------------------
# Grid cell side length in degrees for particle-density probabilities.
DENSITY_GRID_DEG = 0.05
TOP_N_CELLS_PER_SNAPSHOT = 10
DENSITY_CONTOUR_THRESHOLDS = [0.50, 0.75, 0.90, 0.95]
# GeoJSON stores only roughly every N hours to remain lightweight; JSON keeps
# every saved model output time.
HANDOFF_GEOJSON_HOUR_STEP = 6

# -----------------------------------------------------------------------------
# External-service credentials (never hardcode secrets)
# -----------------------------------------------------------------------------
# Optional project-local .env support. If python-dotenv is installed, it will
# load BacktrackModel/.env automatically. Otherwise normal system environment
# variables work. CDS normally reads its own %USERPROFILE%/.cdsapirc file.
try:
    from dotenv import load_dotenv
    load_dotenv(THIS_DIR / ".env")
except ImportError:
    pass

CMEMS_USERNAME = os.environ.get("COPERNICUSMARINE_SERVICE_USERNAME")
CMEMS_PASSWORD = os.environ.get("COPERNICUSMARINE_SERVICE_PASSWORD")
CDSAPI_URL = os.environ.get("CDSAPI_URL", "https://cds.climate.copernicus.eu/api")
CDSAPI_KEY = os.environ.get("CDSAPI_KEY")

# =============================================================================
# DERIVED OUTPUT PATHS -- DO NOT EDIT BELOW THIS LINE
# =============================================================================

for _dir in (INPUT_DIR, STAGE2_ROOT, STAGE2_EVENT_DIR, ENV_DATA_DIR,
             COASTLINE_DIR, TRAJECTORY_DIR, REPORT_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

CURRENTS_NC = ENV_DATA_DIR / f"{EVENT_ID}_currents.nc"
WINDS_NC = ENV_DATA_DIR / f"{EVENT_ID}_winds.nc"
OBSERVATION_SUMMARY_JSON = REPORT_DIR / f"{EVENT_ID}_observation_summary.json"
ENV_DATA_INSPECTION_JSON = REPORT_DIR / f"{EVENT_ID}_environmental_data_inspection.json"

BACKTRACK_TRAJECTORY_NC = TRAJECTORY_DIR / f"{EVENT_ID}_backtrack.nc"

# These two files are THE FINAL STAGE-2 -> STAGE-3 AIS HANDOFF:
STAGE2_HANDOFF_JSON = REPORT_DIR / f"{EVENT_ID}_stage2_handoff.json"
SOURCE_PROBABILITY_GEOJSON = REPORT_DIR / f"{EVENT_ID}_source_probability.geojson"


if __name__ == "__main__":
    # Safe standalone path check; this does not fetch or run anything.
    print(f"BacktrackModel folder: {THIS_DIR}")
    print(f"Input folder:          {INPUT_DIR}  (exists={INPUT_DIR.exists()})")
    print(f"Stage-1 GeoJSON input: {REGIONS_GEOJSON}  (exists={REGIONS_GEOJSON.exists()})")
    print(f"Stage-2 output root:   {STAGE2_ROOT}")
    print(f"Event output folder:   {STAGE2_EVENT_DIR}")
    if not REGIONS_GEOJSON.exists():
        print("\nACTION REQUIRED: Copy Stage-1's oil_regions.geojson to:")
        print(f"  {REGIONS_GEOJSON}")
