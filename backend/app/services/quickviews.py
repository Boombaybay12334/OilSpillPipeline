from __future__ import annotations

from app.services.data_manager import DataManager


class QuickviewService:
    """Generate presentation rasters when rasterio and Pillow are installed."""

    def __init__(self, manager: DataManager):
        self.manager = manager

    def generate(self, event_id: str, stage: str) -> list[dict]:
        try:
            import numpy as np
            import rasterio
            from PIL import Image
        except ImportError as exc:
            return [{"warning": f"Quickviews unavailable: install rasterio and Pillow ({exc})"}]
        manifest = self.manager.read_manifest(event_id)
        results = []
        for artifact in manifest.get("artifacts", []):
            if artifact["stage"] != stage or artifact["category"] != "raster_source":
                continue
            source = self.manager.safe_path(event_id, artifact["relative_path"])
            try:
                with rasterio.open(source) as dataset:
                    scale = min(1.0, 1800 / max(dataset.width, dataset.height))
                    height, width = max(1, int(dataset.height * scale)), max(1, int(dataset.width * scale))
                    data = dataset.read(1, out_shape=(height, width), masked=True)
                    values = np.asarray(data.compressed(), dtype="float32")
                    if values.size == 0:
                        raise ValueError("Raster contains no finite data")
                    low, high = np.percentile(values, [2, 98])
                    if high <= low:
                        high = low + 1
                    pixels = np.clip((data.filled(low) - low) / (high - low) * 255, 0, 255).astype("uint8")
                    output = self.manager.safe_path(event_id, f"{stage}/quickviews/{source.stem}_{artifact['sha256'][:8]}.png")
                    output.parent.mkdir(parents=True, exist_ok=True)
                    Image.fromarray(pixels, mode="L").save(output)
                    results.append({"source_artifact_id": artifact["artifact_id"], "relative_path": output.relative_to(self.manager.event_dir(event_id)).as_posix(), "crs": str(dataset.crs) if dataset.crs else None, "bbox_wsen": [dataset.bounds.left, dataset.bounds.bottom, dataset.bounds.right, dataset.bounds.top], "stretch": {"method": "percentile", "low": 2, "high": 98, "data_min": float(values.min()), "data_max": float(values.max())}})
            except Exception as exc:
                results.append({"source_artifact_id": artifact["artifact_id"], "warning": str(exc)})
        return results