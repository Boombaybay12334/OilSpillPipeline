# Oil Spill Detection Service

Sentinel-1 SAR oil-spill detection: fetch a scene from Copernicus Data Space
Ecosystem → SNAP calibration/terrain-correction → CFAR dark-anomaly
pre-filter → CNN classifier + U-Net segmentor → georeferenced regions
(coordinates, shape, area, timing), plus human-viewable quicklook PNGs.

This is a **closed service**: it's meant to be run once (as a Python
library, a CLI, or an HTTP API) and then talked to by other things — a
future CLI, a notebook, a dashboard — without those callers needing SNAP,
torch, or any of this repo's internals installed themselves.

---

## What's new in this revision

If you used an earlier version of this service, here's what changed:

- **Every detection call gets its own `runs/<run_id>/` folder**, instead
  of everything landing flat in one `--output_dir`. Two calls can never
  collide or overwrite each other's files anymore.
- **Raw outputs and processed outputs are physically separated**
  (`raw/` vs `processed/` subfolders) — see [Folder layout](#folder-layout-per-run).
- **Three PNG quickviews are generated automatically** so you can actually
  *look* at a scene/detection without GIS software — see [Quickviews](#quickviews-why-you-need-them).
- **The event registry is now fully manageable over HTTP** — list, get,
  add, and delete, not just add.
- **The API has a real `/runs` registry** — list every past detection,
  fetch its geojson/report/quickviews/raw tifs individually, on demand.
- A duplicated dead code block in `preprocess_and_infer.py` (a leftover
  copy-paste, unreachable) was removed. No behavior change.

---

## Folder layout per run

Every call to `detect()` (library, CLI, or `POST /detect`) creates one new
folder under `<base_dir>/runs/<run_id>/`:

```
runs/
└── sanchi-2018_20260912T165611Z_1119ae5c/     <- run_id: <label>_<UTC timestamp>_<uuid8>
    ├── manifest.json                # status, request echo, summary, file inventory
    ├── scene_metadata.json          # acquisition timing (see scene_metadata.py)
    │
    ├── raw/                         # the actual scientific outputs -- NOT
    │   │                            # directly human-viewable, see Quickviews below
    │   ├── download/                # fetched .SAFE / .zip (only if this run
    │   │                            # fetched a scene itself -- absent when
    │   │                            # input_safe_path pointed at an existing one)
    │   ├── sigma0_vv_vh.tif         # SNAP-calibrated linear VV/VH, full resolution
    │   └── oil_mask_prob.tif        # float32 oil-probability raster, -1 = nodata
    │
    └── processed/                   # the human-facing outputs
        ├── oil_regions.geojson      # THE FINAL ANSWER -- georeferenced regions
        ├── detection_report.json    # same content + scene metadata + summary
        ├── quickview_sar.png        # grayscale SAR quicklook
        ├── quickview_mask.png       # colorized probability heatmap
        └── quickview_overlay.png    # SAR + flagged-oil-in-red -- the fastest
                                      # "does this detection look right" image
```

`base_dir` (the old `--output_dir` / `DetectionRequest.output_dir`) is now
"the folder `runs/` lives under", not a flat per-call dump folder. It
defaults to `config.DATA_DIR` (a `data/` folder next to `config.py`, or
`$OILSPILL_DATA_DIR`) if you don't specify one — which is what lets the
HTTP API work without a caller needing to know or care about server-side
paths at all.

`run_id` is `<slugified-label>_<UTC-timestamp>_<8-char-uuid>` — the label
is `run_label` if you gave one, else the `event_key`, else `"custom"`. The
timestamp+uuid suffix guarantees uniqueness even for two runs of the same
event started in the same second; the label makes a directory listing
human-scannable.

A run's `manifest.json` is written **immediately**, before the scene is
even fetched, and updated at each stage — so a run that fails partway
through (bad event key, SNAP failure, no satellite pass in the window)
still leaves a real, inspectable record (`status: "failed"` + `error`)
instead of silently vanishing. `GET /runs` / `GET /runs/{run_id}` will
show it.

---

## Quickviews: why you need them

`sigma0_vv_vh.tif` is **linear-scale** calibrated SAR backscatter — values
span several orders of magnitude. Opened in a normal image viewer it's
almost solid black. `oil_mask_prob.tif` is a float32 probability raster
with `-1.0` as nodata — also not viewable, and a bare probability number
doesn't visually communicate "where's the oil" without a colormap.

`quickview.py` (a new, self-contained rendering module) solves this by
generating three ordinary 8-bit PNGs per run, written into `processed/`:

| File | What it shows |
|---|---|
| `quickview_sar.png` | Grayscale VV, converted to dB and percentile-stretched — lets you eyeball a scene (does it look like open water? mostly land/nodata?) independent of anything the model decided. |
| `quickview_mask.png` | The probability raster, colorized (viridis-style ramp). Nodata renders black. |
| `quickview_overlay.png` | The SAR grayscale image with every pixel the model flagged as oil (probability ≥ the segmentation threshold) painted solid red. **This is the single most useful image for sanity-checking a detection at a glance.** |

Generation is decimated at the `rasterio` read level (not "read full
array then downsample"), so it stays fast and low-memory even on a
24000×27000-pixel scene. It's a pure rendering step that runs strictly
*after* the geojson/report are already written — if it fails for any
reason, the error is logged and swallowed rather than failing an
otherwise-successful detection. Set `generate_quickview=False` (library),
`--no_quickview` (CLI), or `"generate_quickview": false` (API) to skip it
entirely if you only want the raw tifs + geojson.

---

## Quickstart

```bash
pip install -r requirements.txt
# Optional, only if you want .env support instead of manual exports:
pip install python-dotenv
# Optional, only if you want the HTTP service (api_server.py):
pip install fastapi uvicorn
```

You also need **ESA SNAP** installed separately (not a pip package) —
https://step.esa.int/main/download/snap-download/ — with `gpt` either on
your PATH or pointed to via the `GPT_EXECUTABLE` environment variable.

Copy `env.example` to `.env` and fill in your CDSE credentials
(dataspace.copernicus.eu), or export the equivalent shell variables. See
`env.example` for every environment variable this service reads
(CDSE credentials, `GPT_EXECUTABLE`, `OILSPILL_DATA_DIR`,
`EVENTS_REGISTRY_PATH`, `GRAPH_XML_PATH`).

### As a CLI

```bash
python run_pipeline.py --event sanchi_2018 --pick 0
python run_pipeline.py --event sanchi_2018 --list           # see available passes first
python run_pipeline.py --bbox 11.0 55.0 13.0 56.0 --datetime "2018-01-10T00:00:00Z/2018-01-10T23:59:59Z"
python run_pipeline.py --input path/to/existing.SAFE
python run_pipeline.py --event sanchi_2018 --run_label my-test --no_quickview
```

`--output_dir` is now optional (defaults to `config.DATA_DIR`) — pass it
only if you want runs organized somewhere other than the default `data/`
folder.

### As a Python library

```python
import oilspill_service as svc

result = svc.detect(svc.DetectionRequest(event_key="sanchi_2018"))
if result.success:
    print(result.run_id, result.run_dir)
    for region in result.regions:
        print(region["centroid_lon"], region["centroid_lat"], region["area_km2"])
else:
    print("failed:", result.error)

# Inspect past runs without re-running anything:
for run in svc.list_runs():
    print(run["run_id"], run["status"], run.get("n_regions"))

manifest = svc.get_run(result.run_id)
mask_path = svc.get_run_file_path(result.run_id, manifest["files"]["raw"]["probability_mask_tif"])
```

### As an HTTP service

```bash
uvicorn api_server:app --host 0.0.0.0 --port 8000
```

```bash
# Kick off a detection
curl -X POST localhost:8000/detect -H "Content-Type: application/json" \
     -d '{"event_key":"sanchi_2018"}'
# -> {"run_id": "sanchi-2018_...", "status": "success", "regions_geojson": {...}, "urls": {...}, ...}

# List everything that's ever been run
curl localhost:8000/runs

# Fetch just the overlay quicklook for a specific run
curl localhost:8000/runs/sanchi-2018_.../quickview/overlay -o overlay.png

# Fetch the raw probability mask tif for a specific run (large -- on demand only)
curl localhost:8000/runs/sanchi-2018_.../raw/mask -o mask.tif
```

---

## API reference

Full interactive docs are always available at `/docs` (Swagger UI) once
the server is running. Summary:

| Method & path | What it does |
|---|---|
| `GET /` | Service info + links |
| `GET /health` | Liveness check |
| `GET /readme` | This file, raw markdown — lets a CLI/client show a real usage guide that can't drift out of sync with the server |
| `GET /events` | Full event/control-scene registry (bbox, datetime window, description) |
| `GET /events/{key}` | One event/control scene, full detail |
| `POST /events` | Register a new spill event or control scene |
| `DELETE /events/{key}` | Remove one (idempotent — no error if already absent) |
| `POST /search` | List available Sentinel-1 passes for an event/bbox — read-only, downloads nothing |
| `POST /detect` | Run full detection → a new `run_id`. Can take minutes (see [Runtime notes](#runtime-notes-snap--long-running-requests)) |
| `GET /runs` | List all past runs, most recent first |
| `GET /runs/{run_id}` | One run's manifest — status, request, scene metadata, region/area summary, geojson inline, and a `urls` map for everything else |
| `GET /runs/{run_id}/geojson` | `oil_regions.geojson`, as-is |
| `GET /runs/{run_id}/report` | Full `detection_report.json` |
| `GET /runs/{run_id}/quickview/{which}` | PNG quicklook. `which` ∈ `{sar, mask, overlay}` |
| `GET /runs/{run_id}/raw/{which}` | Raw GeoTIFF, **on demand only**. `which` ∈ `{sigma0, mask}` |

### Why raw files and processed files are fetched separately

A full-scene `sigma0_vv_vh.tif` can be hundreds of MB to multiple GB; the
probability mask tif is similarly large. `POST /detect` and
`GET /runs/{run_id}` never embed either — they return the (small) geojson
inline plus a `urls` map, and you fetch quickviews/raw tifs with a
separate `GET` only when you actually want them. This is the "quickview +
geojson by default, raw on demand" behavior you asked for: nothing large
moves over the wire unless a client explicitly asks for it.

### Event registry over the API

```bash
# See everything currently registered
curl localhost:8000/events

# Register a new spill event
curl -X POST localhost:8000/events -H "Content-Type: application/json" -d '{
  "key": "my_new_event",
  "bbox": [11.0, 55.0, 13.0, 56.0],
  "datetime_range": "2026-05-01T00:00:00Z/2026-05-05T23:59:59Z",
  "description": "..."
}'

# Remove it
curl -X DELETE localhost:8000/events/my_new_event
```

Registered this way, an event takes effect on the very next `/search` or
`/detect` call using that key — **no server restart required**. The
registry is a plain JSON file (`events_registry.json`, or wherever
`EVENTS_REGISTRY_PATH` points), re-read fresh on every call, so a manual
edit of the file works exactly the same way an API call does.

### Runtime notes: SNAP + long-running requests

`/detect` runs synchronously and can take minutes for a large scene (SNAP
preprocessing + streamed classifier/segmentor inference). This is a
deliberate, left-open integration decision, not an oversight: fronting it
with a job queue (submit → poll/webhook) is the right move for production
use behind a load balancer with request timeouts, but the right queue
technology depends entirely on what you're deploying this into (Celery,
RQ, cloud pub/sub, a simple background-thread + polling endpoint...), so
it's not baked in here.

---

## Running SNAP inside this service (and eventually containerizing it)

You mentioned wanting to put this in Docker later — here's how the pieces
fit together for that, without actually building any Docker artifacts now
(that part really is a separate decision, e.g. base image choice, SNAP's
install size, GPU passthrough for torch if you want CUDA inference).

**SNAP itself isn't a Python dependency.** `preprocess_and_infer.py` calls
`gpt` (SNAP's headless command-line processor) via `subprocess.run` — SNAP
just needs to be *installed somewhere on the same machine/container* and
discoverable. Discovery already happens in this priority order (see
`resolve_gpt_executable()`):
1. `GPT_EXECUTABLE` env var, if set — the reliable option for a container,
   since you control the exact install path in your image.
2. `gpt` on `PATH`.
3. A handful of common OS-default install locations.

This means the *only* thing a container image needs to get right for SNAP
is: install SNAP headless (ESA publishes a scripted/silent-install mode
for this, separate from the GUI installer), then set `GPT_EXECUTABLE` to
wherever that put the `gpt` binary. Nothing in this repo's Python code
needs to change for that.

**The graph XML path is already externalized** the same way
(`GRAPH_XML_PATH` env var, falls back to the file shipped next to
`preprocess_and_infer.py`) — so you can bake a different/tuned graph into
an image without touching code, too.

**Memory, not CPU, is the real constraint to plan around.** SNAP's `gpt`
and this pipeline's own streaming strips (`strip_rows`, default 4096) are
both tunable for memory ceiling vs. speed — a memory-constrained container
should lower `strip_rows` (via the `/detect` request or CLI flag) and give
SNAP's own JVM heap (`gpt` respects a `-J-Xmx...` style override, see
SNAP's own docs) a fixed, conservative cap rather than letting it grow
unbounded.

**Concurrency**: because `/detect` is synchronous and SNAP is
memory-heavy, run `uvicorn` with a worker count that matches how many
concurrent `gpt` processes your container's memory budget can actually
sustain — not the CPU core count. One worker per container, scaled
horizontally (multiple containers behind a queue/load balancer), is a
more predictable starting point than many workers in one container.

**Persistent state**: point `OILSPILL_DATA_DIR` at a mounted volume (so
`runs/` survives a container restart) and `EVENTS_REGISTRY_PATH` at
another mounted file (so events registered via the API aren't lost on
redeploy) — both are already environment-variable-driven for exactly this
reason.

None of the above requires code changes beyond what's already in this
revision — it's a deployment/ops decision, which is why no Dockerfile is
included here.

---

## What each file does

- **`fetch_s1.py`** — authenticates with CDSE, searches the Sentinel-1 GRD
  catalog (by bbox+datetime, or a named event/control scene), resolves and
  downloads the product, extracts it to a real `.SAFE` folder, saves scene
  metadata (acquisition timing) alongside it. Also owns the event registry
  (`get_known_events`, `get_control_scenes`, `add_event`, `remove_event`).
- **`s1_preprocess_graph.xml`** — SNAP `gpt` graph: orbit file, thermal
  noise removal, calibration, terrain correction, land-sea masking. Outputs
  linear (not dB) Sigma0 VV/VH as a GeoTIFF.
- **`preprocess_and_infer.py`** — the core orchestration: runs the SNAP
  graph, streams the scene in row-strips (bounded memory regardless of
  scene size), converts to dB, normalizes, runs the CFAR pre-filter, tiles
  candidate regions, runs the classifier then segmentor, writes the
  probability mask, calls region extraction, metadata, and quickview
  rendering, writes the final report — all split into `raw/`/`processed/`.
- **`cfar_filter.py`** — fast local-threshold dark-anomaly detection
  (shortlist only, never the final answer).
- **`region_extraction.py`** — turns the final pixel mask into discrete
  georeferenced regions: centroid, polygon, area, elongation/circularity,
  confidence.
- **`scene_metadata.py`** — extracts real acquisition start/stop time from
  the SAFE manifest.
- **`quickview.py`** — renders the raw GeoTIFFs into viewable PNGs. See
  [Quickviews](#quickviews-why-you-need-them).
- **`run_registry.py`** — assigns `run_id`s, reads/writes each run's
  `manifest.json`, lists past runs.
- **`oilspill_service.py`** — **the integration contract.** `search()` and
  `detect()`, plus the run-registry read-side (`list_runs`, `get_run`,
  `get_run_file_path`). Import from here, not the files above, if you're
  integrating this elsewhere.
- **`run_pipeline.py`** — thin CLI wrapper over `oilspill_service`.
- **`api_server.py`** — FastAPI wrapper, makes this callable over plain
  HTTP from any language/system. See [API reference](#api-reference).

## Do I need the old training code too?

**Partially.** Two files from the original training codebase are genuinely
required at inference time — everything else is training-only and does
**not** need to be present to run this service.

| File | Needed for inference? | Why |
|---|---|---|
| `config.py` | **Yes** | Supplies checkpoint paths, norm stats path, model hyperparameters, `DATA_DIR` |
| `models.py` | **Yes** | Defines the `PatchClassifierCNN` / `UNet` classes the checkpoints load into |
| `classifier_best.pt`, `unet_best.pt` | **Yes** | The trained model weights themselves |
| `norm_stats.json` | **Yes** | VV/VH mean/std used to normalize new scenes exactly like training data |
| `dataset.py` | No | Only used for training-time data loading/augmentation |
| `losses.py` | No | Only used for training |
| `build_manifest.py`, `make_splits.py`, `compute_norm_stats.py` | No | One-time dataset-prep scripts, already run once to produce `norm_stats.json` |
| `train_classifier.py`, `train_segmentor.py` | No | Only needed if you're retraining |
| `analyze_zenodo_dataset.py`, `dataset2analyze.py` | No | One-off exploratory scripts, not part of any pipeline |

**Exact `config.py` fields the inference service reads:**
```
NORM_STATS_JSON, CLASSIFIER_CKPT, UNET_CKPT, CLASSIFIER_DROPOUT,
UNET_ENCODER_CHANNELS, GRID_EVAL_CROP_SIZE, GRID_EVAL_STRIDE,
SEG_THRESHOLD, DEVICE, DATA_DIR
```

## Repo layout

```
your-project/
├── config.py                  # checkpoint paths + hyperparams + DATA_DIR
├── models.py                  # model class definitions
├── checkpoints/
│   ├── classifier_best.pt
│   └── unet_best.pt
├── norm_stats.json
│
├── s1_preprocess_graph.xml    # SNAP gpt graph
├── fetch_s1.py                # CDSE search/download/extract + event registry
├── scene_metadata.py          # acquisition timing
├── cfar_filter.py             # CFAR dark-anomaly pre-filter
├── region_extraction.py       # pixel mask -> georeferenced regions
├── quickview.py               # raw GeoTIFF -> human-viewable PNG
├── run_registry.py            # run_id assignment + manifest.json
├── preprocess_and_infer.py    # SNAP -> normalize -> CFAR -> tile -> models -> quickviews
├── oilspill_service.py        # <-- the stable integration contract, import this
├── run_pipeline.py            # CLI wrapper over oilspill_service
├── api_server.py              # FastAPI HTTP wrapper
│
├── events_registry.json       # spill events + control scenes (editable via API too)
├── requirements.txt
├── env.example                # copy to .env, fill in CDSE credentials
├── data/                      # default DATA_DIR -- runs/<run_id>/... lands here
└── README.md                  # this file
```

## Known limitations (read before trusting output blindly)

- **CFAR window sizes (`background_window`, `guard_window` in
  `cfar_filter.py`) are starting points, not validated constants** — tune
  and verify against a known scene before relying on them.
- **Dense archipelago / narrow-strait coastlines produce false positives**
  (wind-shadowed calm water reads as a dark anomaly, and straits are
  naturally elongated — matching a real slick's shape signature). Confirmed
  via a control test in open water with a simple coastline, which came back
  clean. Not yet mitigated in code — currently a known, understood gap.
- **Band-order assumption (`VV`=channel 0, `VH`=channel 1) has never been
  independently verified** against actual GeoTIFF band descriptions via
  `gdalinfo`. Recommended before further validation work.
- **`/detect` is synchronous** — see [Runtime notes](#runtime-notes-snap--long-running-requests)
  for why, and what to do about it in production.
