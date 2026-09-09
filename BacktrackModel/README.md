# Stage 2 -- Oil Spill Source Location / Release Time Backtracking

Takes the Stage-1 output (`oil_regions.geojson` + `scene_metadata.json`)
and produces a **Stage-3-ready** probabilistic map of where and when the
observed oil spill most likely originated, using OpenDrift/OpenOil
backward Lagrangian particle tracking driven by historical ocean currents
(CMEMS GLORYS12V1) and winds (ERA5).

This folder is self-contained. It does not import anything from the
Stage-1 pipeline (SNAP, classifier, segmentor) -- it only reads Stage-1's
two output files.

---

## What you get out of this

Two files, written into `stage2/<event_id>/reports/`:

| File | Purpose |
|---|---|
| `<event>_stage2_handoff.json` | Structured, versioned handoff: observation summary, run provenance/config, and one probability snapshot per saved backward timestep (top-N grid cells + cumulative coverage bounding boxes). **This is what Stage 3 should read.** |
| `<event>_source_probability.geojson` | Lightweight GeoJSON of probability grid cells (as polygons) for a subsampled set of timesteps -- load directly in QGIS, or use for spatial joins against AIS points in Stage 3. |

Everything else in `stage2/<event_id>/` (raw NetCDF trajectory, cached
env-data downloads, intermediate CSV/JSON) is scratch/debug output. Stage 3
should never need to touch it directly.

---

## Files in this folder

| File | Role |
|---|---|
| `stage2_config.py` | **Single source of truth for all paths/settings.** Edit this per event -- no other file needs editing for a normal run. |
| `prepare_observation.py` | Loads Stage-1's GeoJSON + metadata; computes `T_obs`, the observed bbox, and the two time windows (simulation vs. padded search/download). |
| `fetch_environmental_data.py` | Downloads CMEMS currents + ERA5 winds for the exact bbox/window. Network-dependent; requires free CMEMS + CDS accounts. Skips re-downloading if files already exist. |
| `inspect_environmental_data.py` | Verifies the downloaded NetCDFs actually cover the simulation window (not just the padded download window) before OpenDrift is allowed to touch them. Exposes `check_readiness()` as a reusable gate. |
| `seed_particles.py` | Converts observed slick polygons/points into thousands of seed particle positions (uniform-in-polygon sampling; small-disk sampling for degenerate point detections). |
| `run_backtracking.py` | The actual OpenDrift/OpenOil backward run. Gates on `inspect_environmental_data.check_readiness()` first. Writes the raw trajectory NetCDF. |
| `generate_handoff.py` | **The final deliverable.** Reads the trajectory NetCDF and produces the two Stage-3-ready files described above. |
| `run_stage2_pipeline.py` | Runs all of the above in order, end to end, with one command. |
| `requirements.txt` | Python dependencies. |
| `README.md` | This file. |

---

## Which files to move from your existing working directory

Copy **only** these Python files into this new flat folder (overwrite any
older/broken versions you had lying around from earlier iteration):

```
stage2_config.py
prepare_observation.py
fetch_environmental_data.py
inspect_environmental_data.py
seed_particles.py
run_backtracking.py
generate_handoff.py
run_stage2_pipeline.py
requirements.txt
README.md
```

Do **NOT** move:

- Anything from Stage 1 (`config.py`, `preprocess_and_infer.py`,
  `region_extraction.py`, `models.py`, `fetch_s1.py`,
  `s1_preprocess_graph.xml`, the classifier/segmentor training scripts,
  etc.). Stage 2 never imports these -- it only reads Stage-1's two output
  files, whose paths you configure in `stage2_config.py`.
- The downloaded NOAA/NCEI GSHHG archive (`0304143.1.1/...`). It's kept as
  a config path for a possible future local-coastline validation pass, but
  V1 doesn't use it (OpenDrift's automatic GSHHG landmask is used
  instead). No need to move or duplicate that ~600MB archive.
- `check_stage2_handoff.py` / `check_stage2_handoff_fixed.py` (the earlier
  metadata-verification scripts). Their job is now folded into
  `prepare_observation.py`'s own validation. Keep them only if you still
  want a standalone Stage-1 sanity check independent of Stage 2.

Your Stage-1 scene output folder (e.g. `scene_out_sanchi/`) stays exactly
where it is -- Stage 2 reads it via the absolute path in
`stage2_config.py`, it does not need to be copied anywhere.

---

## Setup

### 1. Install dependencies

```
pip install -r requirements.txt
```

On Windows, if `opendrift` fails to build via pip, use conda-forge instead:

```
conda install -c conda-forge opendrift shapely pyproj xarray netCDF4 numpy pandas
pip install copernicusmarine cdsapi
```

### 2. Set up Copernicus Marine (CMEMS) credentials

Register free at https://data.marine.copernicus.eu, then run once:

```
copernicusmarine login
```

(or set `COPERNICUSMARINE_SERVICE_USERNAME` / `COPERNICUSMARINE_SERVICE_PASSWORD`
environment variables).

### 3. Set up Copernicus Climate Data Store (ERA5) credentials

1. Register free at https://cds.climate.copernicus.eu
2. Copy your Personal Access Token from https://cds.climate.copernicus.eu/profile
3. Create `%USERPROFILE%\.cdsapirc` (Windows) or `~/.cdsapirc` (Linux/Mac)
   containing exactly:

   ```
   url: https://cds.climate.copernicus.eu/api
   key: PASTE_YOUR_PERSONAL_ACCESS_TOKEN_HERE
   ```

4. Visit the ERA5 hourly single-levels dataset page while logged in and
   accept its terms/licence once, before your first request:
   https://cds.climate.copernicus.eu/datasets/reanalysis-era5-single-levels

### 4. Configure the event

Open `stage2_config.py` and edit the **USER SETTINGS** section:

- `EVENT_ID` -- a short label for this spill event.
- `SCENE_OUT_DIR` -- your Stage-1 `run_pipeline.py --output_dir` folder.
- `SCENE_METADATA_CANDIDATES` -- list every path where `scene_metadata.json`
  might actually live for this event (Stage-1's output location for this
  file has been inconsistent; the list lets Stage-2 find it regardless).
- `REGIONS_GEOJSON` -- defaults to `SCENE_OUT_DIR / "oil_regions.geojson"`.
- `BACKTRACK_HOURS` -- how far back to run. **Must not exceed the actual
  historical coverage of whatever currents product you fetch** -- check
  with `inspect_environmental_data.py` before increasing this.
- `STAGE2_ROOT` -- where all Stage-2 outputs (env data cache, trajectories,
  reports) get written. Fully separate from `SCENE_OUT_DIR`.

Everything else has sensible defaults for a first run.

---

## Running it

### One command, full pipeline

```
python run_stage2_pipeline.py
```

This runs all five steps in order and stops with a clear error message if
any gate fails (e.g. environmental data doesn't cover the simulation
window).

### Or, step by step (useful for debugging)

```
python prepare_observation.py         # verify T_obs, bbox, feature counts
python fetch_environmental_data.py    # download currents + winds (needs credentials)
python inspect_environmental_data.py  # verify coverage before trusting the data
python run_backtracking.py            # the actual OpenDrift backward run
python generate_handoff.py            # build the two Stage-3 deliverables
```

If you only changed something downstream (e.g. `TOP_N_CELLS_PER_SNAPSHOT`
in the config), you don't need to re-fetch data or re-run the backward
simulation -- just re-run `generate_handoff.py` on the existing trajectory
file.

---

## What "Stage 2 done" looks like

A successful run ends with:

```
STAGE 2 PIPELINE COMPLETE
Hand these two files to Stage 3:
  <path>\reports\<event>_stage2_handoff.json
  <path>\reports\<event>_source_probability.geojson
```

Open `<event>_stage2_handoff.json` and sanity-check:

- `observation.num_detected_regions` matches what Stage 1 reported.
- `backtracking.simulation_start_utc` / `simulation_end_utc` match what you
  expect from `BACKTRACK_HOURS`.
- `origin_hypotheses` has one entry per saved output timestep, each with
  `top_cells` (ranked candidate origin grid cells) and
  `coverage_thresholds` (how many cells are needed to cover 50/75/90/95%
  of particles at that time).
- The `limitations` array is present and unmodified -- it documents this
  run's known scientific caveats (single deterministic run, daily current
  forcing, no wave forcing, etc.) and should be surfaced to whoever
  consumes Stage 3's output, not silently dropped.

---

## Known V1 limitations (carried into every handoff JSON's `limitations` field)

- **Single deterministic run.** No ensemble over current/wind
  perturbation, windage coefficient, or diffusion. Treat `top_cells` as
  candidate regions, not a validated answer.
- **Daily-resolution ocean currents** (CMEMS GLORYS12V1 `P1D-m`). This is
  almost certainly the largest source of trajectory uncertainty. A
  higher-frequency or regional current product should be evaluated before
  this is used for anything beyond prototyping.
- **No wave/Stokes-drift forcing.** Surface transport may be
  underestimated in wind-driven conditions.
- **No oil-type, volume, or release-duration inference.** `oil_type` in
  the config is an assumed forward-model input, not something the model
  infers from the SAR detection.
- **`coverage_thresholds` bounding boxes are not tight contour polygons.**
  They're the bounding box of the N highest-probability grid cells needed
  to reach a cumulative-probability threshold -- a cheap, honest
  approximation, not an alpha-shape/concave-hull contour.
- **This describes candidate origin regions, not a confirmed source.** Any
  vessel-scoring built on top of this in Stage 3 indicates
  spatial-temporal *compatibility* with the modeled drift, not proof of
  responsibility.

---

## Stage 3 preview (not implemented in this folder)

Stage 3 (AIS-based candidate vessel scoring) is intentionally **not**
part of this folder. When you build it, it should:

1. Read `<event>_stage2_handoff.json` and, for each AIS-observed vessel
   position `(lon, lat, t)`, find the nearest `origin_hypotheses` entry by
   time and look up the local probability at `(lon, lat)` from its
   `top_cells` (or fall back to `<event>_source_probability.geojson` for a
   full-resolution spatial join if the position falls outside the
   top-N cells).
2. Combine that spatial-temporal probability with route/heading
   consistency, vessel type, and AIS track completeness into a single
   compatibility score per candidate vessel (see design discussion in
   project chat history).
3. Always report scored vessels as *investigative candidates*, never as
   confirmed sources -- carry the `limitations` array from the Stage-2
   handoff (or an equivalent disclaimer) through to any Stage-3 report.
