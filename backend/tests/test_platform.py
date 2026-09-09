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


def test_sar_quickview_uses_db_composite_and_skips_thumbnail(tmp_path: Path):
    manager = DataManager(tmp_path / "data")
    event = manager.create_event("sar")
    source = manager.safe_path(event["event_id"], "stage1/outputs/sigma0_vv_vh.tif")
    thumb = manager.safe_path(event["event_id"], "stage1/outputs/scene_thumbnail.tif")
    source.parent.mkdir(parents=True, exist_ok=True)
    profile = {"driver": "GTiff", "width": 10, "height": 10, "count": 2, "dtype": "float32", "crs": "EPSG:4326", "transform": from_origin(10, 20, 0.1, 0.1)}
    with rasterio.open(source, "w", **profile) as dataset:
        dataset.write(np.full((10, 10), 0.01, dtype="float32"), 1)
        dataset.write(np.full((10, 10), 0.001, dtype="float32"), 2)
    with rasterio.open(thumb, "w", **{**profile, "count": 1}) as dataset:
        dataset.write(np.ones((10, 10), dtype="float32"), 1)
    artifacts = ArtifactDiscoveryService(manager).discover(event["event_id"], "stage1")
    assert not any("thumbnail" in item["relative_path"] for item in artifacts)
    results = QuickviewService(manager).generate(event["event_id"], "stage1")
    sar = next(item for item in results if item.get("source_relative_path", "").endswith("sigma0_vv_vh.tif"))
    assert sar["renderer"] == "sar_linear_to_db_vv_vh_composite"
    assert sar["stretch"]["display_min_db"] < 0
    assert not any(item.get("source_relative_path", "").endswith("scene_thumbnail.tif") for item in results)


def test_esa_quicklook_is_excluded_but_other_preview_is_kept(tmp_path: Path):
    manager = DataManager(tmp_path / "data")
    event = manager.create_event("esa-preview")
    root = manager.safe_path(event["event_id"], "stage1/outputs/preview")
    root.mkdir(parents=True, exist_ok=True)
    (root / "quick-look.png").write_bytes(b"esa quick look")
    (root / "product-preview.html").write_text("preview", encoding="utf-8")
    artifacts = ArtifactDiscoveryService(manager).discover(event["event_id"], "stage1")
    paths = {item["relative_path"] for item in artifacts}
    assert "stage1/outputs/preview/quick-look.png" not in paths
    assert "stage1/outputs/preview/product-preview.html" in paths