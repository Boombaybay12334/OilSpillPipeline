from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DATA_ROOT = Path(os.getenv("DATA_ROOT", PROJECT_ROOT / "data")).resolve()
DB_PATH = Path(os.getenv("INVESTIGATION_DB", DATA_ROOT / "investigations.sqlite3")).resolve()
STAGE_LAYOUT = {
    "stage1": ("raw", "quickviews", "outputs", "reports", "logs"),
    "stage2": ("inputs", "env_data", "trajectories", "reports", "quickviews", "logs"),
    "stage3": ("inputs", "reports", "quickviews", "logs"),
}