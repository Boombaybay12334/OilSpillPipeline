from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.transform import from_origin

from app.services.data_manager import DataManager
from app.services.discovery import ArtifactDiscoveryService
from app.services.quickviews import QuickviewService


def test_event_layout_isolated(tmp_path: Path):
    manager = DataManager(tmp_path / "data")
    first, second = manager.create_event("one"), manager.create_event("two")
    assert first["event_id"] != second["event_id"]
    assert (manager.event_dir(first["event_id"]) / "stage2" / "env_data").is_dir()
    assert manager.safe_path(first["event_id"], "stage1/outputs/x.txt").parent.name == "outputs"


def test_discovery_is_idempotent_and_content_aware(tmp_path: Path):
    manager = DataManager(tmp_path / "data")
    event = manager.create_event("discovery")
    output = manager.safe_path(event["event_id"], "stage1/outputs")
    output.mkdir(parents=True, exist_ok=True)
    (output / "result.json").write_text(json.dumps({"origin_hypotheses": [], "backtracking": {}}), encoding="utf-8")
    (output / "regions.geojson").write_text(json.dumps({"type": "FeatureCollection", "metadata": {"acquisition_start": "2024-01-01"}, "features": []}), encoding="utf-8")
    service = ArtifactDiscoveryService(manager)
    first = service.discover(event["event_id"], "stage1")
    second = service.discover(event["event_id"], "stage1")
    assert len(first) == len(second) == 2
    assert {item["category"] for item in second} == {"stage_handoff"}


def test_quickview_preserves_source(tmp_path: Path):
    manager = DataManager(tmp_path / "data")
    event = manager.create_event("raster")
    source = manager.safe_path(event["event_id"], "stage1/outputs/probability_mask.tif")
    source.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(source, "w", driver="GTiff", width=20, height=20, count=1, dtype="float32", crs="EPSG:4326", transform=from_origin(10, 20, 0.1, 0.1)) as dataset:
        dataset.write(np.linspace(0, 1, 400, dtype="float32").reshape(20, 20), 1)
    ArtifactDiscoveryService(manager).discover(event["event_id"], "stage1")
    before = source.read_bytes()
    results = QuickviewService(manager).generate(event["event_id"], "stage1")
    assert results and "warning" not in results[0]
    assert source.read_bytes() == before