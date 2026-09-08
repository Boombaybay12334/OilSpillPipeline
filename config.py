"""
config.py
=========
Inference-side config. All paths resolve relative to THIS FILE's own
location (not the current working directory), so you can move the whole
folder anywhere and it keeps working -- no path edits needed as long as
the layout inside the folder stays the same.

Expects this folder layout (everything in ONE flat folder together --
see README.md for why it has to be flat, not split across subfolders):

    Model/                          <- this folder, name doesn't matter
    ├── config.py                   <- this file
    ├── models.py
    ├── classifier_best.pt
    ├── unet_best.pt
    ├── norm_stats.json
    ├── s1_preprocess_graph.xml
    ├── fetch_s1.py
    ├── preprocess_and_infer.py
    ├── cfar_filter.py
    ├── region_extraction.py
    ├── scene_metadata.py
    ├── oilspill_service.py
    ├── run_pipeline.py
    ├── api_server.py
    ├── .env
    └── requirements.txt
"""

import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# REQUIRED AT INFERENCE -- checkpoint + norm stats paths
# ============================================================
CLASSIFIER_CKPT = os.path.join(BASE_DIR, "classifier_best.pt")
UNET_CKPT = os.path.join(BASE_DIR, "unet_best.pt")
NORM_STATS_JSON = os.path.join(BASE_DIR, "norm_stats.json")

# ============================================================
# Model hyperparameters -- MUST match what the checkpoints were
# actually trained with, or load_state_dict() will fail with a shape
# mismatch. These values are carried over unchanged from the original
# training config.py.
# ============================================================
CLASSIFIER_DROPOUT = 0.3
UNET_ENCODER_CHANNELS = [32, 64, 128, 256, 512]

# ============================================================
# Tiling / grid evaluation -- MUST match training crop size (512)
# ============================================================
GRID_EVAL_CROP_SIZE = 512
GRID_EVAL_STRIDE = 512
SEG_THRESHOLD = 0.5

# ============================================================
# Device -- falls back to CPU automatically in code if CUDA unavailable
# ============================================================
DEVICE = "cuda"
