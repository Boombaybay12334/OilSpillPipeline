from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any, Callable

from app.services.data_manager import DataManager
from app.services.discovery import ArtifactDiscoveryService
from app.services.quickviews import QuickviewService


class PipelineRunners:
    def __init__(self, manager: DataManager, discover: ArtifactDiscoveryService, emit: Callable[..., Any], quickviews: QuickviewService | None = None):
        self.manager, self.discover, self.emit, self.quickviews = manager, discover, emit, quickviews

    def import_outputs(self, event_id: str, stage: str, source: str) -> dict[str, Any]:
        self.emit(event_id, stage, "running", f"Importing local {stage} outputs", 10)
        destination = self.manager.import_tree(event_id, Path(source), stage)
        artifacts = self.discover.discover(event_id, stage)
        if self.quickviews:
            self.quickviews.generate(event_id, stage)
            artifacts = self.discover.discover(event_id, stage)
        self.emit(event_id, stage, "completed", f"Imported and discovered {len(artifacts)} artifacts", 100)
        self.manager.update_event(event_id, status=f"{stage}_ready")
        return {"stage": stage, "mode": "replay", "destination": destination.relative_to(self.manager.event_dir(event_id)).as_posix(), "artifacts": artifacts}

    def run_stage1(self, event_id: str, options: dict[str, Any], mode: str) -> dict[str, Any]:
        local_output = options.get("existing_output_dir") or options.get("local_output_dir")
        if local_output:
            return self.import_outputs(event_id, "stage1", local_output)
        if mode in {"offline", "replay"}:
            raise RuntimeError("Offline Stage 1 requires existing_output_dir or local_output_dir")
        event_dir = self.manager.event_dir(event_id)
        output_dir = event_dir / "stage1" / "outputs"
        model_dir = Path(__file__).resolve().parents[3] / "Model"
        sys.path.insert(0, str(model_dir))
        try:
            import oilspill_service as service
            request = service.DetectionRequest(output_dir=str(output_dir), input_safe_path=options.get("input_safe_path"), event_key=options.get("event_key"), pick_index=options.get("pick_index", 0), bbox=options.get("bbox"), datetime_range=options.get("datetime_range"))
            self.emit(event_id, "stage1", "running", "Calling existing Stage 1 service", 20)
            result = service.detect(request)
            if not result.success:
                raise RuntimeError(result.error or "Stage 1 failed")
        finally:
            if str(model_dir) in sys.path:
                sys.path.remove(str(model_dir))
        artifacts = self.discover.discover(event_id, "stage1")
        self.emit(event_id, "stage1", "completed", f"Stage 1 completed with {len(artifacts)} artifacts", 100)
        self.manager.update_event(event_id, status="stage1_ready")
        return {"stage": "stage1", "mode": mode, "result": result.to_dict(), "artifacts": artifacts}

    def run_stage2(self, event_id: str, options: dict[str, Any], mode: str) -> dict[str, Any]:
        local_output = options.get("existing_output_dir") or options.get("local_output_dir")
        if local_output:
            return self.import_outputs(event_id, "stage2", local_output)
        if mode in {"offline", "replay"}:
            raise RuntimeError("Offline Stage 2 requires existing_output_dir containing cached outputs")
        raise RuntimeError("Live Stage 2 requires an event-isolated adapter; use local import until OpenDrift configuration is supplied")

    def run_stage3(self, event_id: str, options: dict[str, Any], mode: str) -> dict[str, Any]:
        local_output = options.get("existing_output_dir") or options.get("local_output_dir")
        if local_output:
            return self.import_outputs(event_id, "stage3", local_output)
        if mode in {"offline", "replay"}:
            raise RuntimeError("Offline Stage 3 requires existing_output_dir containing cached ranking outputs")
        raise RuntimeError("Live Stage 3 requires an explicit GFW token and isolated adapter; use local import for replay")
