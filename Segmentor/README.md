# Oil Spill Detection Service

Sentinel-1 SAR oil-spill detection: fetch a scene from Copernicus Data Space
Ecosystem → SNAP calibration/terrain-correction → CFAR dark-anomaly
pre-filter → CNN classifier + U-Net segmentor → georeferenced regions
(coordinates, shape, area, timing).

## Short answer to "do I need the old training code too?"

**Partially.** Two files from the original training codebase are genuinely
required at inference time — everything else is training-only and does
**not** need to be present to run this service.

| File | Needed for inference? | Why |
|---|---|---|
| `config.py` | **Yes** | Supplies checkpoint paths, norm stats path, model hyperparameters (see exact field list below) |
| `models.py` | **Yes** | Defines the `PatchClassifierCNN` / `UNet` classes the checkpoints load into |
| `classifier_best.pt`, `unet_best.pt` | **Yes** | The trained model weights themselves |
| `norm_stats.json` | **Yes** | VV/VH mean/std used to normalize new scenes exactly like training data |
| `dataset.py` | No | Only used for training-time data loading/augmentation |
| `losses.py` | No | Only used for training |
| `build_manifest.py`, `make_splits.py`, `compute_norm_stats.py` | No | One-time dataset-prep scripts, already run once to produce `norm_stats.json` |
| `train_classifier.py`, `train_segmentor.py` | No | Only needed if you're retraining |
| `analyze_zenodo_dataset.py`, `dataset2analyze.py` | No | One-off exploratory scripts, not part of any pipeline |

This was verified by grepping actual imports across every inference-side
file (`fetch_s1.py`, `preprocess_and_infer.py`, `cfar_filter.py`,
`region_extraction.py`, `scene_metadata.py`, `oilspill_service.py`,
`api_server.py`, `run_pipeline.py`) — not assumed.

**Exact `config.py` fields the inference service reads** (everything else
in that file — the `OIL_IMAGES_DIR`-style training paths — is present but
unused at inference; harmless to leave in, since Python doesn't validate
unused attributes):
```
NORM_STATS_JSON, CLASSIFIER_CKPT, UNET_CKPT, CLASSIFIER_DROPOUT,
UNET_ENCODER_CHANNELS, GRID_EVAL_CROP_SIZE, GRID_EVAL_STRIDE,
SEG_THRESHOLD, DEVICE
```

## Folder layout

```
your-project/
├── config.py                  # from training repo -- checkpoint paths + hyperparams
├── models.py                  # from training repo -- model class definitions
├── checkpoints/
│   ├── classifier_best.pt
│   └── unet_best.pt
├── norm_stats.json
│
├── s1_preprocess_graph.xml    # SNAP gpt graph (calibration, terrain-correction, land mask)
├── fetch_s1.py                # CDSE search/download/extract
├── scene_metadata.py          # acquisition timing (SAFE manifest parsing)
├── cfar_filter.py             # CFAR dark-anomaly pre-filter
├── region_extraction.py       # pixel mask -> georeferenced regions with shape/coords
├── preprocess_and_infer.py    # SNAP -> normalize -> CFAR -> tile -> classifier/segmentor
├── oilspill_service.py        # <-- the stable integration contract, import this
├── run_pipeline.py            # CLI wrapper over oilspill_service
├── api_server.py              # optional HTTP wrapper (FastAPI)
│
├── requirements.txt
├── .env.example                # copy to .env, fill in CDSE credentials
└── README.md                   # this file
```

`config.CLASSIFIER_CKPT` / `config.UNET_CKPT` / `config.NORM_STATS_JSON`
must point at wherever you actually put those three files — adjust the
paths in `config.py` to match your layout above.

## Setup

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

Copy `.env.example` to `.env` and fill in your CDSE credentials
(dataspace.copernicus.eu), or export `CDSE_USERNAME` / `CDSE_PASSWORD` as
shell environment variables.

## Running it

**As a CLI:**
```bash
python run_pipeline.py --output_dir scene_out --event sanchi_2018 --pick 0
python run_pipeline.py --output_dir scene_out --event sanchi_2018 --list   # see available passes first
python run_pipeline.py --output_dir scene_out --bbox 11.0 55.0 13.0 56.0 --datetime "2018-01-10T00:00:00Z/2018-01-10T23:59:59Z"
python run_pipeline.py --output_dir scene_out --input path/to/existing.SAFE
```

**As a Python library:**
```python
import oilspill_service as svc

result = svc.detect(svc.DetectionRequest(output_dir="out", event_key="sanchi_2018"))
if result.success:
    for region in result.regions:
        print(region["centroid_lon"], region["centroid_lat"], region["area_km2"])
else:
    print("failed:", result.error)
```

**As an HTTP service:**
```bash
uvicorn api_server:app --host 0.0.0.0 --port 8000
curl -X POST localhost:8000/detect -H "Content-Type: application/json" \
     -d '{"output_dir":"out","event_key":"sanchi_2018"}'
```

## What each file does

- **`fetch_s1.py`** — authenticates with CDSE, searches the Sentinel-1 GRD
  catalog (by bbox+datetime, or a named event/control scene), resolves and
  downloads the product, extracts it to a real `.SAFE` folder, saves scene
  metadata (acquisition timing) alongside it.
- **`s1_preprocess_graph.xml`** — SNAP `gpt` graph: orbit file, thermal
  noise removal, calibration, terrain correction, land-sea masking. Outputs
  linear (not dB) Sigma0 VV/VH as a GeoTIFF.
- **`preprocess_and_infer.py`** — the core orchestration: runs the SNAP
  graph, streams the scene in row-strips (bounded memory regardless of
  scene size), converts to dB, normalizes, runs the CFAR pre-filter, tiles
  candidate regions, runs the classifier then segmentor, writes the
  probability mask, calls region extraction and metadata, writes the
  final report.
- **`cfar_filter.py`** — fast local-threshold dark-anomaly detection
  (shortlist only, never the final answer).
- **`region_extraction.py`** — turns the final pixel mask into discrete
  georeferenced regions: centroid, polygon, area, elongation/circularity,
  confidence.
- **`scene_metadata.py`** — extracts real acquisition start/stop time from
  the SAFE manifest.
- **`oilspill_service.py`** — **the integration contract.** Two functions,
  `search()` and `detect()`, typed request/response dataclasses. Import
  from here, not the files above, if you're integrating this elsewhere.
- **`run_pipeline.py`** — thin CLI wrapper over `oilspill_service`.
- **`api_server.py`** — optional FastAPI wrapper, makes this callable over
  plain HTTP from any language/system.

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
