from __future__ import annotations

import json
from pathlib import Path

from app.services.data_manager import DataManager, utc_now


class QuickviewService:
    """Create presentation-only PNGs without changing scientific rasters."""

    MAX_EDGE = 1800

    def __init__(self, manager: DataManager):
        self.manager = manager

    def generate(self, event_id: str, stage: str) -> list[dict]:
        try:
            import numpy as np
            import rasterio
            from rasterio.enums import Resampling
            from PIL import Image
        except ImportError as exc:
            return [{"warning": f"Quickviews unavailable: install rasterio and Pillow ({exc})"}]

        manifest = self.manager.read_manifest(event_id)
        results = []
        for artifact in manifest.get("artifacts", []):
            if artifact["stage"] != stage or artifact["category"] != "raster_source":
                continue
            source = self.manager.safe_path(event_id, artifact["relative_path"])
            if self._is_thumbnail(source):
                results.append({"source_artifact_id": artifact["artifact_id"], "skipped": True, "warning": "Thumbnail source skipped by presentation rules."})
                continue
            try:
                with rasterio.open(source) as dataset:
                    scale = min(1.0, self.MAX_EDGE / max(dataset.width, dataset.height))
                    height = max(1, int(dataset.height * scale))
                    width = max(1, int(dataset.width * scale))
                    role = self._role(source, dataset.count)
                    if role == "probability_mask":
                        pixels, stretch = self._render_probability(dataset, height, width, np, Resampling.bilinear)
                    elif role == "sar_backscatter":
                        pixels, stretch = self._render_sar(dataset, height, width, np, Resampling.bilinear)
                    else:
                        pixels, stretch = self._render_generic(dataset, height, width, np, Resampling.bilinear)

                    output = self.manager.safe_path(event_id, f"{stage}/quickviews/{source.stem}_{artifact['sha256'][:8]}.png")
                    output.parent.mkdir(parents=True, exist_ok=True)
                    Image.fromarray(pixels, mode="RGBA").save(output)
                    relative_output = output.relative_to(self.manager.event_dir(event_id)).as_posix()
                    sidecar = output.with_suffix(".json")
                    metadata = {
                        "source_artifact_id": artifact["artifact_id"],
                        "quickview_relative_path": relative_output,
                        "source_relative_path": artifact["relative_path"],
                        "role": role,
                        "renderer": stretch["method"],
                        "width": dataset.width,
                        "height": dataset.height,
                        "bands": dataset.count,
                        "crs": str(dataset.crs) if dataset.crs else None,
                        "bbox_wsen": [dataset.bounds.left, dataset.bounds.bottom, dataset.bounds.right, dataset.bounds.top],
                        "stretch": stretch,
                        "created_at_utc": utc_now(),
                        "warnings": [],
                    }
                    sidecar.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
                    results.append(metadata)
            except Exception as exc:
                results.append({"source_artifact_id": artifact["artifact_id"], "warning": str(exc)})
        return results

    @staticmethod
    def _is_thumbnail(source: Path) -> bool:
        name = source.name.lower()
        return "thumbnail" in name or "thumb" in name or name in {"quick-look.png", "logo.png"}

    @staticmethod
    def _role(source: Path, band_count: int) -> str:
        name = source.name.lower()
        if "prob" in name and "mask" in name:
            return "probability_mask"
        if "sigma0" in name or ("vv" in name and band_count >= 2):
            return "sar_backscatter"
        return "generic_raster"

    @staticmethod
    def _finite_values(data, np):
        values = np.asarray(data.compressed(), dtype="float32")
        values = values[np.isfinite(values)]
        if values.size == 0:
            raise ValueError("Raster contains no finite displayable data")
        return values

    @classmethod
    def _render_probability(cls, dataset, height, width, np, resampling):
        data = dataset.read(1, out_shape=(height, width), masked=True, resampling=resampling)
        values = cls._finite_values(data, np)
        clipped = np.clip(data.filled(0), 0.0, 1.0)
        # Blue means low confidence; yellow/red means high probability.
        red = np.clip(clipped * 2.0, 0.0, 1.0)
        green = np.clip(clipped * 2.0 - 0.8, 0.0, 1.0)
        blue = np.clip(0.7 - clipped * 1.8, 0.0, 1.0)
        alpha = np.where(np.ma.getmaskarray(data), 0, 255).astype("uint8")
        pixels = np.dstack([(red * 255).astype("uint8"), (green * 255).astype("uint8"), (blue * 255).astype("uint8"), alpha])
        return pixels, {"method": "probability_0_1_heatmap", "valid_min": float(values.min()), "valid_max": float(values.max()), "clip": [0.0, 1.0]}

    @classmethod
    def _render_sar(cls, dataset, height, width, np, resampling):
        band_count = min(dataset.count, 2)
        data = dataset.read(list(range(1, band_count + 1)), out_shape=(band_count, height, width), masked=True, resampling=resampling)
        db_bands = []
        masks = []
        for band in data:
            linear = band.filled(0).astype("float32")
            valid = (~np.ma.getmaskarray(band)) & np.isfinite(linear) & (linear > 1e-6)
            db = np.full(linear.shape, np.nan, dtype="float32")
            db[valid] = 10.0 * np.log10(linear[valid])
            db_bands.append(db)
            masks.append(valid)
        valid_all = np.logical_and.reduce(masks)
        values = np.concatenate([band[valid_all] for band in db_bands])
        if values.size == 0:
            raise ValueError("Sigma0 raster has no positive linear backscatter values")
        low, high = np.percentile(values, [2, 98])
        if high <= low:
            high = low + 1.0
        channels = []
        for band in db_bands:
            normalized = np.clip((np.nan_to_num(band, nan=low) - low) / (high - low), 0.0, 1.0)
            channels.append((normalized * 255).astype("uint8"))
        if len(channels) == 1:
            channels = [channels[0], channels[0], channels[0]]
        else:
            # VV red, VH green, and their mean blue preserves both polarisations.
            channels = [channels[0], channels[1], ((channels[0].astype("uint16") + channels[1]) // 2).astype("uint8")]
        alpha = np.where(valid_all, 255, 0).astype("uint8")
        return np.dstack([*channels, alpha]), {"method": "sar_linear_to_db_vv_vh_composite", "percentile": [2, 98], "data_min_db": float(values.min()), "data_max_db": float(values.max()), "display_min_db": float(low), "display_max_db": float(high), "invalid_rule": "linear Sigma0 <= 1e-6 or source nodata"}

    @classmethod
    def _render_generic(cls, dataset, height, width, np, resampling):
        data = dataset.read(1, out_shape=(height, width), masked=True, resampling=resampling)
        values = cls._finite_values(data, np)
        low, high = np.percentile(values, [2, 98])
        if high <= low:
            high = low + 1.0
        normalized = np.clip((data.filled(low) - low) / (high - low), 0.0, 1.0)
        gray = (normalized * 255).astype("uint8")
        alpha = np.where(np.ma.getmaskarray(data), 0, 255).astype("uint8")
        return np.dstack([gray, gray, gray, alpha]), {"method": "generic_percentile_grayscale", "percentile": [2, 98], "data_min": float(values.min()), "data_max": float(values.max())}
