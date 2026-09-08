"""
api_server.py
===============
Optional thin HTTP wrapper around oilspill_service.py. This is what turns
the pipeline into an actually isolated service -- callable over the network
by anything that can make an HTTP request, without needing Python, SNAP,
torch, or any of this repo's internals installed on the CALLING side.

Run:
    pip install fastapi uvicorn
    uvicorn api_server:app --host 0.0.0.0 --port 8000

Then:
    POST /search  {"event_key": "sanchi_2018"}
    POST /detect  {"output_dir": "out", "event_key": "sanchi_2018", "pick_index": 0}
    GET  /health

This file contains ZERO detection logic -- it only translates HTTP <->
oilspill_service's dataclasses. If you need to change what detection does,
change preprocess_and_infer.py/cfar_filter.py/etc, not this file. If you
need to change what's exposed over HTTP, change this file, not those.

NOTE ON RUNTIME: /detect runs synchronously and can take minutes for a
large scene (SNAP + streamed inference). For production use behind a load
balancer with request timeouts, front this with a job queue (submit ->
poll/webhook) rather than calling /detect directly -- that's an
integration-layer decision deliberately left open here, not solved by
this file, since the right choice depends on the calling system.
"""

import os
from typing import Optional, List

try:
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel
except ImportError:
    raise ImportError(
        "api_server.py needs fastapi + pydantic. Install with:\n"
        "  pip install fastapi uvicorn pydantic\n"
        "If you only need Python-level integration (not HTTP), import "
        "oilspill_service directly instead -- this file is optional."
    )

import oilspill_service as svc


app = FastAPI(
    title="Oil Spill Detection Service",
    description="Sentinel-1 SAR oil-spill detection: CFAR pre-filter -> "
                 "CNN classifier -> U-Net segmentor -> georeferenced regions.",
    version="1.0",
)


class SearchRequestModel(BaseModel):
    event_key: Optional[str] = None
    bbox: Optional[List[float]] = None
    datetime_range: Optional[str] = None
    limit: int = 10


class DetectRequestModel(BaseModel):
    output_dir: str
    input_safe_path: Optional[str] = None
    event_key: Optional[str] = None
    pick_index: int = 0
    bbox: Optional[List[float]] = None
    datetime_range: Optional[str] = None
    use_cfar: bool = True
    cfar_k: float = 2.5
    strip_rows: int = 4096


@app.get("/health")
def health():
    return {"status": "ok"}


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
    """
    result = svc.detect(svc.DetectionRequest(**req.dict()))
    if not result.success:
        # 422 (not 500): these are expected/anticipated failure modes
        # (bad request, no satellite pass found, SNAP failure) -- see
        # oilspill_service.DetectionResult's docstring. A genuinely
        # unexpected internal error still propagates as a real 500.
        raise HTTPException(status_code=422, detail=result.error)
    return result.to_dict()


@app.get("/events")
def list_events():
    """Known spill events and control scenes available via `event_key`."""
    import fetch_s1
    return {
        "spill_events": {
            k: v["description"] for k, v in fetch_s1.KNOWN_OIL_SPILL_EVENTS.items()
        },
        "control_scenes": {
            k: v["description"] for k, v in fetch_s1.CONTROL_TEST_LOCATIONS.items()
        },
    }
