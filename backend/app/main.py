from __future__ import annotations

import mimetypes
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from app.core.config import DATA_ROOT
from app.services.data_manager import DataManager
from app.services.discovery import ArtifactDiscoveryService
from app.services.quickviews import QuickviewService
from app.services.presentations import build_stage_summary
from app.services.runners import PipelineRunners
from app.services.store import InvestigationStore

manager = DataManager()
store = InvestigationStore()
discovery = ArtifactDiscoveryService(manager)
quickviews = QuickviewService(manager)
runners = PipelineRunners(manager, discovery, store.emit, quickviews)
executor = ThreadPoolExecutor(max_workers=int(os.getenv("PIPELINE_WORKERS", "2")))


def _sync(event_id: str, artifacts: list[dict[str, Any]]) -> None:
    store.replace_artifacts(event_id, artifacts)


def _run_job(event_id: str, stage: str, mode: str, options: dict[str, Any]) -> None:
    try:
        method = getattr(runners, f"run_{stage}")
        result = method(event_id, options, mode)
        _sync(event_id, result.get("artifacts", []))
    except Exception as exc:
        store.emit(event_id, stage, "failed", str(exc), 100, "ERROR")
        manager.update_event(event_id, status="failed")


try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse, JSONResponse
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(title="Oil Spill Investigation Pipeline", version="1.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

    @app.get("/api/health")
    def health():
        checks = {
            "data_root": {"available": manager.root.exists(), "writable": os.access(manager.root, os.W_OK)},
            "database": store.db_path.exists(),
            "rasterio": _module_available("rasterio"),
            "stage1_service": (Path(__file__).resolve().parents[2] / "Model" / "oilspill_service.py").exists(),
            "opendrift": _module_available("opendrift"),
            "gfw_configured": bool(os.getenv("GFW_API_TOKEN")),
        }
        return {"ok": all(item.get("available", item) if isinstance(item, dict) else item for item in checks.values()), "checks": checks}

    @app.get("/api/investigations")
    def list_investigations():
        return store.list_events()

    @app.post("/api/investigations")
    def create_investigation(payload: dict[str, Any]):
        event = manager.create_event(str(payload.get("name", "Untitled investigation")), str(payload.get("mode", "offline")))
        store.save_event(event)
        return event

    @app.get("/api/investigations/{event_id}")
    def get_investigation(event_id: str):
        try:
            event = manager.read_event(event_id)
        except (OSError, ValueError):
            raise HTTPException(404, "Investigation not found")
        return {**event, "manifest": manager.read_manifest(event_id), "progress": store.progress(event_id)}

    @app.delete("/api/investigations/{event_id}")
    def delete_investigation(event_id: str):
        import shutil
        path = manager.event_dir(event_id)
        if not path.exists():
            raise HTTPException(404, "Investigation not found")
        shutil.rmtree(path)
        store.delete_event(event_id)
        return {"deleted": event_id}

    @app.post("/api/investigations/{event_id}/run")
    def run_pipeline(event_id: str, payload: dict[str, Any]):
        mode = payload.get("mode", manager.read_event(event_id).get("mode", "offline"))
        stage = payload.get("from_stage", "stage1")
        options = payload.get(f"{stage}_options", {})
        _validate_prerequisites(event_id, stage, options)
        job = executor.submit(_run_job, event_id, stage, mode, options)
        return {"job_id": str(id(job)), "event_id": event_id, "stage": stage, "mode": mode}

    for stage_name in ("stage1", "stage2", "stage3"):
        def route(event_id: str, payload: dict[str, Any], stage_name=stage_name):
            mode = payload.get("mode", manager.read_event(event_id).get("mode", "offline"))
            options = payload.get("options", payload)
            _validate_prerequisites(event_id, stage_name, options)
            if mode == "replay" and (options.get("existing_output_dir") or options.get("local_output_dir")):
                result = getattr(runners, f"run_{stage_name}")(event_id, options, mode)
                _sync(event_id, result.get("artifacts", []))
                return {"job_id": None, "event_id": event_id, "stage": stage_name, "status": "completed", "artifacts": len(result.get("artifacts", []))}
            job = executor.submit(_run_job, event_id, stage_name, mode, options)
            return {"job_id": str(id(job)), "event_id": event_id, "stage": stage_name}
        app.add_api_route(f"/api/investigations/{{event_id}}/run/{stage_name}", route, methods=["POST"])

    @app.get("/api/investigations/{event_id}/status")
    def status(event_id: str):
        return {"event": manager.read_event(event_id), "progress": store.progress(event_id)}

    @app.get("/api/investigations/{event_id}/logs")
    def logs(event_id: str):
        return store.progress(event_id)

    @app.post("/api/investigations/{event_id}/cancel")
    def cancel(event_id: str):
        manager.update_event(event_id, status="cancel_requested")
        store.emit(event_id, "pipeline", "cancel_requested", "Cancellation requested", None, "WARNING")
        return {"event_id": event_id, "status": "cancel_requested"}

    @app.get("/api/investigations/{event_id}/artifacts")
    def artifacts(event_id: str):
        return store.artifacts(event_id) or manager.read_manifest(event_id).get("artifacts", [])

    @app.post("/api/investigations/{event_id}/discover-artifacts")
    def discover_artifacts(event_id: str):
        artifacts = []
        for stage in ("stage1", "stage2", "stage3"):
            artifacts.extend(discovery.discover(event_id, stage))
        _sync(event_id, artifacts)
        return artifacts

    @app.post("/api/investigations/{event_id}/generate-quickviews")
    def generate_quickviews(event_id: str, payload: dict[str, Any] | None = None):
        stage = (payload or {}).get("stage", "stage1")
        result = quickviews.generate(event_id, stage)
        artifacts = discovery.discover(event_id, stage)
        by_path = {artifact["relative_path"]: artifact for artifact in artifacts}
        for item in result:
            quickview = by_path.get(item.get("relative_path"))
            source = next((artifact for artifact in artifacts if artifact["artifact_id"] == item.get("source_artifact_id")), None)
            if quickview and source:
                quickview["parent_artifact_id"] = source["artifact_id"]
                source.setdefault("presentation", {})["quickview_artifact_id"] = quickview["artifact_id"]
        manager.write_manifest(event_id, {**manager.read_manifest(event_id), "artifacts": artifacts})
        _sync(event_id, artifacts)
        return {"results": result, "artifacts": artifacts}

    @app.get("/api/investigations/{event_id}/artifacts/{artifact_id}")
    def artifact(event_id: str, artifact_id: str):
        match = next((a for a in manager.read_manifest(event_id).get("artifacts", []) if a["artifact_id"] == artifact_id), None)
        if not match:
            raise HTTPException(404, "Artifact not found")
        path = manager.safe_path(event_id, match["relative_path"])
        if not path.is_file():
            raise HTTPException(404, "Artifact file missing")
        return FileResponse(path, media_type=match.get("mime_type") or mimetypes.guess_type(path.name)[0], filename=path.name, content_disposition_type="inline" if match.get("category") in {"image", "geojson", "report", "raster_quickview"} else "attachment")

    @app.get("/api/investigations/{event_id}/artifacts/{artifact_id}/metadata")
    def artifact_metadata(event_id: str, artifact_id: str):
        match = next((a for a in manager.read_manifest(event_id).get("artifacts", []) if a["artifact_id"] == artifact_id), None)
        if not match:
            raise HTTPException(404, "Artifact not found")
        return match

    @app.get("/api/investigations/{event_id}/stage{stage_number}")
    def stage_summary(event_id: str, stage_number: int):
        stage = f"stage{stage_number}"
        artifacts = manager.read_manifest(event_id).get("artifacts", [])
        return {"summary": build_stage_summary(manager, event_id, stage, artifacts), "artifacts": [a for a in artifacts if a["stage"] == stage], "progress": [p for p in store.progress(event_id) if p["stage"] == stage]}

    frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
    if frontend_dir.exists():
        from fastapi.staticfiles import StaticFiles
        app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

except ImportError:
    app = None


def _module_available(name: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(name) is not None


def _validate_prerequisites(event_id: str, stage: str, options: dict[str, Any]) -> None:
    if stage == "stage1":
        return
    artifacts = manager.read_manifest(event_id).get("artifacts", [])
    if stage == "stage2" and not any(a["stage"] == "stage1" and a["category"] == "stage_handoff" for a in artifacts):
        if not options.get("existing_output_dir") and not options.get("local_output_dir"):
            raise HTTPException(409, "Stage 2 requires a discovered Stage 1 handoff")
    if stage == "stage3" and not any(a["stage"] == "stage2" and a["category"] == "stage_handoff" for a in artifacts):
        if not options.get("existing_output_dir") and not options.get("local_output_dir"):
            raise HTTPException(409, "Stage 3 requires a discovered Stage 2 handoff")
