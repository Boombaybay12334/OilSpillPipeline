from __future__ import annotations

import mimetypes
import json
import uuid
from pathlib import Path
from typing import Any

from app.services.data_manager import DataManager, utc_now


class ArtifactDiscoveryService:
    def __init__(self, manager: DataManager):
        self.manager = manager

    def discover(self, event_id: str, stage: str, stage_dir: Path | None = None) -> list[dict[str, Any]]:
        root = (stage_dir or self.manager.safe_path(event_id, stage)).resolve()
        event_dir = self.manager.event_dir(event_id)
        if event_dir not in root.parents and root != event_dir:
            raise ValueError("Discovery path escapes event")
        existing = {a["relative_path"]: a for a in self.manager.read_manifest(event_id).get("artifacts", [])}
        existing = {relative: artifact for relative, artifact in existing.items() if not self._is_ignored_presentation_file(Path(relative))}
        for path in root.rglob("*"):
            if not path.is_file() or path.name.endswith((".lock", ".part", ".tmp")):
                continue
            if self._is_ignored_presentation_file(path):
                continue
            relative = path.relative_to(event_dir).as_posix()
            category, label, priority = self._classify(path)
            artifact = existing.get(relative, {"artifact_id": str(uuid.uuid4()), "created_at_utc": utc_now()})
            artifact.update({"event_id": event_id, "stage": stage, "category": category, "label": label, "relative_path": relative, "mime_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream", "size_bytes": path.stat().st_size, "sha256": self.manager.checksum(path), "provenance": "replay", "display_priority": priority, "presentation": artifact.get("presentation", {})})
            existing[relative] = artifact
        artifacts = list(existing.values())
        manifest = self.manager.read_manifest(event_id)
        manifest["artifacts"] = artifacts
        self.manager.write_manifest(event_id, manifest)
        return artifacts

    @staticmethod
    def _is_ignored_presentation_file(path: Path) -> bool:
        name = path.name.lower()
        return "thumbnail" in name or "thumb" in name or name in {"quick-look.png", "logo.png"}

    @staticmethod
    def _classify(path: Path) -> tuple[str, str, int]:
        name, suffix = path.name.lower(), path.suffix.lower()
        if path.parent.name.lower() == "quickviews" and suffix in {".png", ".jpg", ".jpeg"}:
            return "raster_quickview", "Raster quickview", 95
        if "handoff" in name:
            return "stage_handoff", "Stage handoff", 100
        if suffix in {".geojson", ".json"}:
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
                if value.get("type") == "FeatureCollection":
                    properties = [feature.get("properties", {}) for feature in value.get("features", [])[:10]]
                    if any("probability" in item for item in properties):
                        return "geojson", "Source probability GeoJSON", 95
                    if "metadata" in value or any("area_km2" in item or "mean_probability" in item for item in properties):
                        return "stage_handoff", "Stage 1 oil regions", 100
                keys = set(value) if isinstance(value, dict) else set()
                if {"origin_hypotheses", "backtracking"} & keys:
                    return "stage_handoff", "Stage 2 backtracking handoff", 100
                if any(key in keys for key in {"ranked_candidates", "top_matches", "candidates"}):
                    return "report", "Stage 3 vessel ranking", 100
            except (OSError, ValueError, UnicodeDecodeError):
                pass
            if "metadata" in name:
                return "metadata_json", "Metadata", 75
            return ("geojson", "GeoJSON", 60) if suffix == ".geojson" else ("report", "JSON report", 60)
        if suffix in {".tif", ".tiff"}:
            if "prob" in name:
                return "raster_source", "Probability raster", 100
            if "mask" in name or "segment" in name:
                return "raster_source", "Segmentation raster", 90
            return "raster_source", "Raster source", 70
        if suffix in {".png", ".jpg", ".jpeg"}:
            return "image", "Image", 65
        if suffix in {".nc", ".nc4"}:
            return "netcdf", "NetCDF scientific data", 40
        if suffix == ".csv":
            return "csv", "CSV data", 45
        if suffix in {".log", ".txt"}:
            return "log", "Log", 20
        return "unknown_download", path.name, 10