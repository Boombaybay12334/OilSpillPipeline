from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.services.data_manager import DataManager


def _json_artifacts(manager: DataManager, event_id: str, artifacts: list[dict[str, Any]]) -> list[tuple[dict[str, Any], Any]]:
    values = []
    for artifact in artifacts:
        if artifact["category"] not in {"stage_handoff", "metadata_json", "report", "geojson"}:
            continue
        path = manager.safe_path(event_id, artifact["relative_path"])
        try:
            values.append((artifact, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError, UnicodeDecodeError):
            continue
    return values


def _first(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if data.get(key) is not None:
            return data[key]
    return None


def build_stage_summary(manager: DataManager, event_id: str, stage: str, artifacts: list[dict[str, Any]]) -> dict[str, Any]:
    values = _json_artifacts(manager, event_id, [a for a in artifacts if a["stage"] == stage])
    if stage == "stage1":
        for artifact, data in values:
            if not isinstance(data, dict):
                continue
            metadata = data.get("metadata") or data.get("scene_metadata") or {}
            features = data.get("features") or data.get("regions") or []
            detection_summary = data.get("detection_summary") or {}
            if metadata or features or detection_summary:
                region_count = len(features) if features else detection_summary.get("n_regions", 0)
                return {
                    "stage": stage,
                    "kind": "detection",
                    "metadata": metadata,
                    "detection_summary": detection_summary,
                    "region_count": region_count,
                    "regions": features[:50],
                    "artifact_ids": [artifact["artifact_id"]],
                }
    if stage == "stage2":
        for artifact, data in values:
            if not isinstance(data, dict) or not ({"observation", "backtracking", "origin_hypotheses"} & set(data)):
                continue
            observation, backtracking = data.get("observation", {}), data.get("backtracking", {})
            hypotheses = data.get("origin_hypotheses", [])
            top_cells = [{**cell, "time_utc": hypothesis.get("time_utc")} for hypothesis in hypotheses for cell in hypothesis.get("top_cells", [])[:10]]
            return {
                "stage": stage,
                "kind": "backtracking",
                "observation": observation,
                "backtracking": backtracking,
                "simulation_window": {"start": backtracking.get("simulation_start_utc"), "end": backtracking.get("simulation_end_utc")},
                "hypothesis_count": len(hypotheses),
                "origin_hypotheses": hypotheses,
                "top_cells": top_cells[:50],
                "limitations": data.get("limitations", []),
                "handoff_artifact_id": artifact["artifact_id"],
            }
    if stage == "stage3":
        for artifact, data in values:
            if not isinstance(data, dict):
                continue
            candidates = data.get("ranked_candidates") or data.get("candidates") or data.get("ships") or data.get("vessels")
            if isinstance(candidates, list):
                return {
                    "stage": stage,
                    "kind": "vessel_ranking",
                    "candidates": candidates[:50],
                    "query": data.get("query", {}),
                    "count": data.get("count", len(candidates)),
                    "description": data.get("description", "Top ranked vessel candidates for display."),
                    "artifact_id": artifact["artifact_id"],
                    "disclaimer": "Investigative candidates only. A ranking reflects compatibility with modeled source probability and available AIS evidence; it is not proof of responsibility.",
                }
    return {"stage": stage, "kind": "empty", "message": "No recognized presentation handoff is available yet.", "artifact_ids": [a["artifact_id"] for a in artifacts if a["stage"] == stage]}