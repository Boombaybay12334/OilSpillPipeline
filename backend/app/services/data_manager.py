from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import DATA_ROOT, STAGE_LAYOUT


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class DataManager:
    def __init__(self, data_root: Path = DATA_ROOT):
        self.root = data_root.resolve()
        self.investigations = self.root / "investigations"
        self.bootstrap()

    def bootstrap(self) -> None:
        self.investigations.mkdir(parents=True, exist_ok=True)

    def _safe_event_id(self, event_id: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", event_id):
            raise ValueError("Invalid event id")
        return event_id

    def event_dir(self, event_id: str) -> Path:
        path = (self.investigations / self._safe_event_id(event_id)).resolve()
        if self.root not in path.parents:
            raise ValueError("Event path escapes data root")
        return path

    def safe_path(self, event_id: str, relative_path: str) -> Path:
        event_dir = self.event_dir(event_id)
        path = (event_dir / relative_path).resolve()
        if event_dir not in path.parents and path != event_dir:
            raise ValueError("Artifact path escapes event directory")
        return path

    def create_event(self, name: str, mode: str = "offline") -> dict[str, Any]:
        event_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
        event_dir = self.event_dir(event_id)
        event_dir.mkdir(parents=True)
        for stage, folders in STAGE_LAYOUT.items():
            for folder in folders:
                (event_dir / stage / folder).mkdir(parents=True, exist_ok=True)
        event = {"event_id": event_id, "name": name.strip() or event_id, "mode": mode, "created_at_utc": utc_now(), "status": "created"}
        self._write_json(event_dir / "event.json", event)
        self._write_json(event_dir / "manifest.json", {"event_id": event_id, "updated_at_utc": utc_now(), "artifacts": []})
        self._write_json(event_dir / "inputs" / "stage1_request.json", {})
        self._write_json(event_dir / "inputs" / "local_input_refs.json", [])
        return event

    def read_event(self, event_id: str) -> dict[str, Any]:
        with self.safe_path(event_id, "event.json").open(encoding="utf-8") as handle:
            return json.load(handle)

    def update_event(self, event_id: str, **values: Any) -> dict[str, Any]:
        event = self.read_event(event_id)
        event.update(values)
        self._write_json(self.safe_path(event_id, "event.json"), event)
        return event

    def read_manifest(self, event_id: str) -> dict[str, Any]:
        with self.safe_path(event_id, "manifest.json").open(encoding="utf-8") as handle:
            return json.load(handle)

    def write_manifest(self, event_id: str, manifest: dict[str, Any]) -> None:
        manifest["updated_at_utc"] = utc_now()
        self._write_json(self.safe_path(event_id, "manifest.json"), manifest)

    def checksum(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def import_tree(self, event_id: str, source: Path, stage: str) -> Path:
        if stage not in STAGE_LAYOUT:
            raise ValueError("Unknown stage")
        source = source.resolve()
        if not source.is_dir():
            raise ValueError("Import source must be a directory")
        destination = self.safe_path(event_id, f"{stage}/outputs/imported")
        destination.mkdir(parents=True, exist_ok=True)
        for item in source.rglob("*"):
            excluded_parts = {".git", "__pycache__", ".venv", "venv", "env", "node_modules"}
            excluded_names = {".env", ".env.example", ".cdsapirc"}
            if item.is_file() and item.name not in excluded_names and not any(part in excluded_parts for part in item.parts):
                target = destination / item.relative_to(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
        return destination

    @staticmethod
    def _write_json(path: Path, value: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2, ensure_ascii=True), encoding="utf-8")