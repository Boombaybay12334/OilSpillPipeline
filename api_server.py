"""
api_server.py
===============
Thin HTTP wrapper around oilspill_service.py. This is what turns the
pipeline into an actually isolated, robust service -- callable over the
network by anything that can make an HTTP request, without needing
Python, SNAP, torch, or any of this repo's internals installed on the
CALLING side (e.g. a future CLI, per the project plan).

Run:
    pip install fastapi uvicorn
    uvicorn api_server:app --host 0.0.0.0 --port 8000

This file contains ZERO detection logic -- it only translates HTTP <->
oilspill_service's dataclasses/run-registry, and serves files that already
exist on disk. If you need to change what detection does, change
preprocess_and_infer.py/cfar_filter.py/etc, not this file. If you need to
change what's exposed over HTTP, change this file, not those.

ENDPOINT MAP (see each handler's docstring for details):
    GET  /                          service info + links
    GET  /health                    liveness check
    GET  /readme                    this repo's README.md, raw markdown

    GET  /events                    full event/control-scene registry
    GET  /events/{key}              one event/control scene, full detail
    POST /events                    register a new event or control scene
    DELETE /events/{key}            remove one (idempotent)

    POST /search                    list available Sentinel-1 passes (read-only)
    POST /detect                    run full detection -> a new run_id

    GET  /runs                      list all past runs (most recent first)
    GET  /runs/{run_id}             one run's manifest + file URLs
    GET  /runs/{run_id}/geojson     the final answer -- georeferenced regions
    GET  /runs/{run_id}/report      full detection_report.json
    GET  /runs/{run_id}/quickview/{which}   PNG, which in {sar, mask, overlay}
    GET  /runs/{run_id}/raw/{which}         GeoTIFF, which in {sigma0, mask}

WHY /detect RETURNS URLS, NOT FILE CONTENTS: a full-scene sigma0 GeoTIFF
can be hundreds of MB to multiple GB; a probability mask tif is similarly
large. Embedding either in a JSON response would make ordinary detection
calls enormous even when the caller only wants the geojson (which IS
already inline in /detect's response body, alongside the quickview PNG
URLs, since those are cheap). Raw tifs are always a deliberate, separate
GET -- "on demand", not "every response, whether you wanted it or not".

NOTE ON RUNTIME: /detect runs synchronously and can take minutes for a
large scene (SNAP + streamed inference). For production use behind a load
balancer with request timeouts, front this with a job queue (submit ->
poll/webhook) rather than calling /detect directly -- that's an
integration-layer decision deliberately left open here, not solved by
this file, since the right choice depends on the calling system. See the
"Running behind SNAP / eventual containerization" section of README.md
for concrete notes on wiring this up.
"""

import os
from typing import Optional, List, Dict, Any

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse, PlainTextResponse
    from pydantic import BaseModel
except ImportError:
    raise ImportError(
        "api_server.py needs fastapi + pydantic. Install with:\n"
        "  pip install fastapi uvicorn pydantic\n"
        "If you only need Python-level integration (not HTTP), import "
        "oilspill_service directly instead -- this file is optional."
    )

import config
import fetch_s1
import oilspill_service as svc

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
README_PATH = os.path.join(BASE_DIR, "README.md")

app = FastAPI(
    title="Oil Spill Detection Service",
    description="Sentinel-1 SAR oil-spill detection: CFAR pre-filter -> "
                 "CNN classifier -> U-Net segmentor -> georeferenced regions.",
    version="1.1",
)


# =========================
#  REQUEST MODELS
# =========================

class SearchRequestModel(BaseModel):
    event_key: Optional[str] = None
    bbox: Optional[List[float]] = None
    datetime_range: Optional[str] = None
    limit: int = 10


class DetectRequestModel(BaseModel):
    output_dir: Optional[str] = None  # defaults server-side to config.DATA_DIR
    input_safe_path: Optional[str] = None
    event_key: Optional[str] = None
    pick_index: int = 0
    bbox: Optional[List[float]] = None
    datetime_range: Optional[str] = None
    use_cfar: bool = True
    cfar_k: float = 2.5
    strip_rows: int = 4096
    run_label: Optional[str] = None
    generate_quickview: bool = True


class AddEventModel(BaseModel):
    key: str
    bbox: List[float]
    datetime_range: str
    description: str
    is_control: bool = False


# =========================
#  SERVICE INFO
# =========================

@app.get("/")
def root():
    """Service info + a map of what's available -- a starting point for
    anything (a future CLI, a curious human with curl) integrating fresh."""
    return {
        "service": "Oil Spill Detection Service",
        "version": app.version,
        "docs": "/docs",
        "readme": "/readme",
        "events": "/events",
        "runs": "/runs",
        "data_dir": config.DATA_DIR,
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/readme")
def get_readme():
    """This repo's README.md, returned as raw markdown -- so a CLI or any
    other client can show a real usage guide without shipping its own
    copy that can drift out of sync with the server it's talking to."""
    if not os.path.exists(README_PATH):
        raise HTTPException(status_code=404, detail="README.md not found on server")
    with open(README_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    return PlainTextResponse(content, media_type="text/markdown")


# =========================
#  EVENT REGISTRY
# =========================

@app.get("/events")
def list_events():
    """Full spill-event and control-scene registry (bbox, datetime window,
    description -- not just descriptions), read fresh from
    events_registry.json on every call. Register new ones via POST
    /events; this never needs a server restart to pick up either an API
    write or a manual edit of the JSON file."""
    return {
        "spill_events": fetch_s1.get_known_events(),
        "control_scenes": fetch_s1.get_control_scenes(),
    }


@app.get("/events/{key}")
def get_event(key: str):
    """One event or control scene's full config, by key."""
    events = fetch_s1.get_known_events()
    controls = fetch_s1.get_control_scenes()
    if key in events:
        return {"key": key, "is_control": False, **events[key]}
    if key in controls:
        return {"key": key, "is_control": True, **controls[key]}
    raise HTTPException(
        status_code=404,
        detail=f"Unknown event/control key '{key}'. Known keys: "
               f"{list(events.keys()) + list(controls.keys())}",
    )


@app.post("/events")
def add_event_endpoint(req: AddEventModel):
    """
    Registers a new spill event or control scene -- no file editing, no
    restart. Takes effect on the very next /search or /detect call using
    this key. Overwrites an existing entry with the same key (use GET
    /events/{key} first if you want to check before clobbering one).
    """
    if len(req.bbox) != 4:
        raise HTTPException(
            status_code=400,
            detail="bbox must have exactly 4 values: [west, south, east, north]",
        )
    fetch_s1.add_event(req.key, req.bbox, req.datetime_range, req.description,
                        is_control=req.is_control)
    return {"status": "added", "key": req.key}


@app.delete("/events/{key}")
def delete_event_endpoint(key: str):
    """Removes an event or control scene from the registry. Idempotent --
    returns removed=False (not a 404) if the key was already absent,
    since "make sure this key isn't registered" is a perfectly reasonable
    thing to want regardless of whether it currently is."""
    removed = fetch_s1.remove_event(key)
    return {"status": "removed" if removed else "not_found", "key": key, "removed": removed}


# =========================
#  SEARCH / DETECT
# =========================

@app.post("/search")
def search_endpoint(req: SearchRequestModel):
    """List available Sentinel-1 passes -- read-only, downloads nothing."""
    try:
        scenes = svc.search(svc.SearchRequest(
            event_key=req.event_key, bbox=req.bbox,
            datetime_range=req.datetime_range, limit=req.limit,
        ))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"scenes": [s.__dict__ for s in scenes]}


@app.post("/detect")
def detect_endpoint(req: DetectRequestModel):
    """
    Run full detection. Can take minutes -- see module docstring re:
    fronting this with a job queue for production use.

    Returns a manifest-shaped response: run_id, status, the final geojson
    inline (see `regions_geojson`), scene metadata/summary, and a `urls`
    map for everything else (quickview PNGs, raw GeoTIFFs, the full
    report) -- fetch those separately, ON DEMAND, via GET /runs/{run_id}/...
    """
    result = svc.detect(svc.DetectionRequest(**req.dict()))
    if not result.success:
        raise HTTPException(status_code=422, detail={
            "error": result.error, "run_id": result.run_id, "run_dir": result.run_dir,
        })
    return _run_summary_response(result.run_id)


# =========================
#  RUNS (past detections)
# =========================

_QUICKVIEW_KEYS = {"sar": "quickview_sar_png", "mask": "quickview_mask_png",
                    "overlay": "quickview_overlay_png"}
_RAW_KEYS = {"sigma0": "sigma0_tif", "mask": "probability_mask_tif"}


def _run_urls(run_id: str, files: Dict[str, Any]) -> Dict[str, Any]:
    """Builds this-API's-own endpoint URLs for whatever files a run
    actually has (per its manifest's `files` inventory), rather than
    exposing server filesystem paths to the caller."""
    base = f"/runs/{run_id}"
    processed = files.get("processed", {}) if files else {}
    raw = files.get("raw", {}) if files else {}

    urls: Dict[str, Any] = {
        "geojson": f"{base}/geojson" if processed.get("regions_geojson") else None,
        "report": f"{base}/report" if processed.get("detection_report_json") else None,
        "quickview": {
            which: f"{base}/quickview/{which}"
            for which, key in _QUICKVIEW_KEYS.items() if processed.get(key)
        },
        "raw": {
            which: f"{base}/raw/{which}"
            for which, key in _RAW_KEYS.items() if raw.get(key)
        },
    }
    return urls


def _run_summary_response(run_id: str) -> Dict[str, Any]:
    manifest = svc.get_run(run_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"No such run: {run_id}")

    response = {
        "run_id": manifest.get("run_id"),
        "status": manifest.get("status"),
        "created_at": manifest.get("created_at"),
        "finished_at": manifest.get("finished_at"),
        "error": manifest.get("error"),
        "request": manifest.get("request"),
        "scene_metadata": manifest.get("scene_metadata"),
        "n_regions": manifest.get("n_regions"),
        "total_oil_area_km2": manifest.get("total_oil_area_km2"),
        "urls": _run_urls(run_id, manifest.get("files", {})),
    }

    # The geojson itself is small relative to the raw tifs and IS the
    # "perfect, no need to touch" final answer -- inline it directly so a
    # caller who only wants regions never needs a second request.
    geojson_rel = manifest.get("files", {}).get("processed", {}).get("regions_geojson")
    if geojson_rel:
        try:
            path = svc.get_run_file_path(run_id, geojson_rel)
            import json as _json
            with open(path, "r") as f:
                response["regions_geojson"] = _json.load(f)
        except FileNotFoundError:
            response["regions_geojson"] = None

    return response


@app.get("/runs")
def list_runs_endpoint():
    """All past runs, most recent first -- status, event/bbox requested,
    region/area summary, and the same `urls` map /runs/{run_id} gives you
    for each one."""
    manifests = svc.list_runs()
    return {"runs": [
        {
            "run_id": m.get("run_id"),
            "status": m.get("status"),
            "created_at": m.get("created_at"),
            "finished_at": m.get("finished_at"),
            "request": m.get("request"),
            "n_regions": m.get("n_regions"),
            "total_oil_area_km2": m.get("total_oil_area_km2"),
            "urls": _run_urls(m.get("run_id"), m.get("files", {})),
        }
        for m in manifests
    ]}


@app.get("/runs/{run_id}")
def get_run_endpoint(run_id: str):
    """One run's full manifest: status, the request that produced it,
    scene metadata, region/area summary, the geojson inline, and a `urls`
    map for everything else (quickviews, raw tifs, full report) --
    fetched on demand via the endpoints below."""
    return _run_summary_response(run_id)


@app.get("/runs/{run_id}/geojson")
def get_run_geojson(run_id: str):
    """The final answer, as-is -- oil_regions.geojson, unmodified."""
    manifest = svc.get_run(run_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"No such run: {run_id}")
    rel = manifest.get("files", {}).get("processed", {}).get("regions_geojson")
    if not rel:
        raise HTTPException(status_code=404, detail=f"No geojson for run {run_id}")
    path = svc.get_run_file_path(run_id, rel)
    return FileResponse(path, media_type="application/geo+json")


@app.get("/runs/{run_id}/report")
def get_run_report(run_id: str):
    """Full detection_report.json (scene metadata + summary + regions +
    output file paths) -- the same file preprocess_and_infer.py writes."""
    manifest = svc.get_run(run_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"No such run: {run_id}")
    rel = manifest.get("files", {}).get("processed", {}).get("detection_report_json")
    if not rel:
        raise HTTPException(status_code=404, detail=f"No report for run {run_id}")
    path = svc.get_run_file_path(run_id, rel)
    return FileResponse(path, media_type="application/json")


@app.get("/runs/{run_id}/quickview/{which}")
def get_run_quickview(run_id: str, which: str):
    """A human-viewable PNG render of this run's output -- see
    quickview.py. `which` is one of: sar (grayscale SAR context), mask
    (colorized probability heatmap), overlay (SAR + flagged-oil in red,
    the fastest "does this look right" image)."""
    key = _QUICKVIEW_KEYS.get(which)
    if key is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown quickview '{which}', expected one of {list(_QUICKVIEW_KEYS)}",
        )
    manifest = svc.get_run(run_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"No such run: {run_id}")
    rel = manifest.get("files", {}).get("processed", {}).get(key)
    if not rel:
        raise HTTPException(
            status_code=404,
            detail=f"Quickview '{which}' not available for run {run_id} "
                   f"(generate_quickview may have been False for this run)",
        )
    path = svc.get_run_file_path(run_id, rel)
    return FileResponse(path, media_type="image/png")


@app.get("/runs/{run_id}/raw/{which}")
def get_run_raw_file(run_id: str, which: str):
    """The actual scientific-output GeoTIFF -- large, not directly
    human-viewable (see quickview.py for that), fetched ON DEMAND rather
    than ever being embedded in a JSON response. `which` is one of:
    sigma0 (calibrated linear VV/VH), mask (float32 oil-probability
    raster, -1 nodata)."""
    key = _RAW_KEYS.get(which)
    if key is None:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown raw file '{which}', expected one of {list(_RAW_KEYS)}",
        )
    manifest = svc.get_run(run_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail=f"No such run: {run_id}")
    rel = manifest.get("files", {}).get("raw", {}).get(key)
    if not rel:
        raise HTTPException(status_code=404, detail=f"Raw file '{which}' not available for run {run_id}")
    path = svc.get_run_file_path(run_id, rel)
    return FileResponse(path, media_type="image/tiff", filename=os.path.basename(path))
