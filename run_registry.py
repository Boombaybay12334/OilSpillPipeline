"""
run_registry.py
=================
Manages the on-disk "runs/" registry every detect() call is now organized
under -- one folder per run (`run_id`), a `manifest.json` recording what
was requested and what came out, and helpers to list/read runs back. This
is what api_server.py's `/runs` endpoints are backed by, and what
oilspill_service.py calls into so it stays the one integration point (see
that file's module docstring) rather than api_server.py reaching in here
directly.

FOLDER SHAPE for one run (see preprocess_and_infer.py for what actually
writes the raw/ and processed/ contents; this module only owns run_id
assignment + manifest.json + listing):

    <base_dir>/runs/<run_id>/
        manifest.json          <- status, request echo, result summary, file inventory
        scene_metadata.json    <- acquisition timing (see scene_metadata.py)
        raw/
            download/                (only present if this run fetched a scene
                                       itself, i.e. event_key or bbox+datetime --
                                       absent when input_safe_path was given)
            sigma0_vv_vh.tif         SNAP-calibrated linear VV/VH -- NOT
                                     human-viewable as-is, see quickview.py
            oil_mask_prob.tif        float32 oil-probability raster, -1 nodata
        processed/
            oil_regions.geojson      the final answer -- georeferenced regions
            detection_report.json    same content plus scene metadata + summary
            quickview_sar.png        human-viewable renders of the two raw
            quickview_mask.png       tifs above (see quickview.py) -- these
            quickview_overlay.png    are NOT re-derivable from the geojson
                                     alone, hence generated once and stored

WHY "run_id" INSTEAD OF LETTING EVERY CALL DUMP INTO ONE FLAT --output_dir
(the old behavior): running detection twice into the same folder used to
either collide (two scenes' sigma0_vv_vh.tif overwriting each other,
caught only by the source-mismatch guard in run_snap_preprocessing) or
just pile raw + processed + download files together with no way to later
ask "what did I even run last Tuesday". One folder per run, with an
inspectable manifest, fixes both: runs never collide, and `list_runs` /
`get_run` give a real answer to "what's already been processed" without
re-scanning file timestamps or re-parsing filenames.

`base_dir` is a parameter everywhere here, never a hardcoded constant --
api_server.py wires it to config.DATA_DIR by default, but library/CLI
callers can still point at any folder they want (this is exactly what the
pre-existing `DetectionRequest.output_dir` field always let you do; it now
means "the folder runs/ lives under" instead of "the one flat folder
everything gets dumped into").
"""

import json
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

MANIFEST_NAME = "manifest.json"


def _slugify(text: Optional[str]) -> str:
    text = (text or "custom").lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text[:40] or "custom"


def new_run_id(label: Optional[str] = None) -> str:
    """<slugified-label>_<UTC-timestamp>_<8-char-uuid>. The label (usually
    the event_key, or "custom" for bbox/manual-input runs) makes run_ids
    human-scannable in a directory listing; the timestamp+uuid suffix
    guarantees uniqueness even for two runs of the same event started in
    the same second."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    short_uuid = uuid.uuid4().hex[:8]
    return f"{_slugify(label)}_{ts}_{short_uuid}"


def runs_root(base_dir: str) -> str:
    return os.path.join(base_dir, "runs")


def run_dir_for(base_dir: str, run_id: str) -> str:
    return os.path.join(runs_root(base_dir), run_id)


def write_manifest(run_dir: str, manifest: dict) -> str:
    os.makedirs(run_dir, exist_ok=True)
    path = os.path.join(run_dir, MANIFEST_NAME)
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2, default=str)
    return path


def read_manifest(run_dir: str) -> Optional[dict]:
    path = os.path.join(run_dir, MANIFEST_NAME)
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)


def list_run_ids(base_dir: str) -> list:
    root = runs_root(base_dir)
    if not os.path.isdir(root):
        return []
    return [d for d in os.listdir(root) if os.path.isdir(os.path.join(root, d))]


def list_runs(base_dir: str) -> list:
    """Every run's manifest under base_dir, most recent first BY
    manifest['created_at'] -- not by folder-listing order, since run_ids
    are label-prefixed (e.g. "sanchi-2018_...") not timestamp-prefixed, so
    alphabetical directory order is not chronological order."""
    runs = []
    for run_id in list_run_ids(base_dir):
        manifest = read_manifest(run_dir_for(base_dir, run_id))
        if manifest:
            runs.append(manifest)
    runs.sort(key=lambda m: m.get("created_at", ""), reverse=True)
    return runs


def get_run(base_dir: str, run_id: str) -> Optional[dict]:
    return read_manifest(run_dir_for(base_dir, run_id))


def relative_file_inventory(run_dir: str) -> dict:
    """Walks a run's raw/ and processed/ subfolders for the pipeline's
    known filenames and returns which of them actually exist, as paths
    relative to run_dir (None for anything missing). Used both to
    populate manifest['files'] at the end of a successful run, and by
    api_server.py's file-serving endpoints (via
    oilspill_service.get_run_file_path) to resolve a request like
    "give me the mask quickview for run X" to an actual path on disk."""
    def _rel(*parts):
        p = os.path.join(run_dir, *parts)
        return os.path.join(*parts) if os.path.exists(p) else None

    return {
        "raw": {
            "sigma0_tif": _rel("raw", "sigma0_vv_vh.tif"),
            "probability_mask_tif": _rel("raw", "oil_mask_prob.tif"),
        },
        "processed": {
            "regions_geojson": _rel("processed", "oil_regions.geojson"),
            "detection_report_json": _rel("processed", "detection_report.json"),
            "quickview_sar_png": _rel("processed", "quickview_sar.png"),
            "quickview_mask_png": _rel("processed", "quickview_mask.png"),
            "quickview_overlay_png": _rel("processed", "quickview_overlay.png"),
        },
        "scene_metadata_json": _rel("scene_metadata.json"),
    }
