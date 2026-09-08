"""
oilspill_service.py
=====================
THE single integration point for this pipeline. Any other code, script,
notebook, or API layer should import from HERE and nowhere else -- not
fetch_s1, not preprocess_and_infer, not cfar_filter directly. Those stay
internal implementation bricks; this file is the stable contract.

    from oilspill_service import search, detect, SearchRequest, DetectionRequest

    result = detect(DetectionRequest(output_dir="out", event_key="sanchi_2018"))
    if result.success:
        for region in result.regions:
            print(region["centroid_lon"], region["centroid_lat"])

WHY THIS EXISTS (not just style):
Before this file, orchestration logic was split across run_pipeline.py
(fetch + CLI args) and preprocess_and_infer.py (SNAP + CFAR + inference),
with results only available as printed log lines and files on disk. That
made this pipeline hard to call from anything other than its own CLI --
exactly the "how do I integrate this" problem being solved here. Now:
  - Input is one typed object (DetectionRequest), not a pile of CLI flags.
  - Output is one typed object (DetectionResult) with real Python types
    (floats, lists of dicts), not stdout to scrape.
  - Failure modes you should expect (no satellite pass found, SNAP
    failure) come back as `success=False` + `error`, not an exception you
    have to wrap every call in.
  - Every field is a plain dataclass -> JSON-serializable via
    dataclasses.asdict(), so this same contract works unchanged whether
    you're calling it from Python directly, wrapping it in a REST API
    (see api_server.py), or a batch/job-queue script.

WHAT THIS FILE DELIBERATELY DOES NOT DO:
It does not reimplement fetch/SNAP/CFAR/inference logic -- it only calls
into fetch_s1.py and preprocess_and_infer.py and reshapes their outputs.
If you need to change how detection actually works, change those files;
change this file only if the CONTRACT (what goes in, what comes out)
needs to change.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any

import fetch_s1
import preprocess_and_infer as pi


# =========================
#  INPUT CONTRACT
# =========================

@dataclass
class SearchRequest:
    """
    Exactly one of `event_key` OR (`bbox` AND `datetime_range`) must be set.
    event_key: a name from fetch_s1.KNOWN_OIL_SPILL_EVENTS or
        fetch_s1.CONTROL_TEST_LOCATIONS (e.g. "sanchi_2018").
    bbox: [west, south, east, north] in EPSG:4326 degrees.
    datetime_range: STAC-style "start_iso/end_iso", e.g.
        "2018-01-14T00:00:00Z/2018-01-25T23:59:59Z".
    """
    event_key: Optional[str] = None
    bbox: Optional[List[float]] = None
    datetime_range: Optional[str] = None
    limit: int = 10


@dataclass
class DetectionRequest:
    """
    The one request object `detect()` accepts. Exactly one scene source
    must be given:
      - `input_safe_path`: skip search+download, use an existing .SAFE
        folder or .zip already on disk.
      - `event_key`: fetch a named event/control scene, `pick_index`
        selects which of the (possibly several) available passes.
      - `bbox` + `datetime_range`: raw search, first result is used.

    Everything else has sane defaults -- override only what you need to.
    """
    output_dir: str

    input_safe_path: Optional[str] = None
    event_key: Optional[str] = None
    pick_index: int = 0
    bbox: Optional[List[float]] = None
    datetime_range: Optional[str] = None

    use_cfar: bool = True
    cfar_k: float = 2.5
    strip_rows: int = 4096

    def validate(self) -> Optional[str]:
        """Returns an error string if the request is malformed, else None."""
        sources_given = sum([
            bool(self.input_safe_path),
            bool(self.event_key),
            bool(self.bbox and self.datetime_range),
        ])
        if sources_given == 0:
            return ("Must provide exactly one scene source: input_safe_path, "
                    "event_key, or (bbox + datetime_range).")
        if sources_given > 1:
            return ("Multiple scene sources given -- provide exactly ONE of "
                    "input_safe_path, event_key, or (bbox + datetime_range), "
                    "not several, so it's unambiguous which one is used.")
        if self.bbox and not self.datetime_range:
            return "bbox given without datetime_range -- both are required together."
        if self.datetime_range and not self.bbox:
            return "datetime_range given without bbox -- both are required together."
        return None


# =========================
#  OUTPUT CONTRACT
# =========================

@dataclass
class SceneInfo:
    """One available Sentinel-1 pass, as returned by search()."""
    catalog_id: str
    datetime: Optional[str]
    orbit_state: Optional[str]


@dataclass
class DetectionResult:
    """
    The one result object `detect()` returns. Always check `success`
    first -- on failure, every other field is empty/zeroed and `error`
    explains what happened. This never raises for expected failure modes
    (no satellite pass found for the window, SNAP processing failure,
    malformed request); it DOES still raise for genuinely unexpected
    internal errors, since silently swallowing those would hide real bugs
    rather than surface them to whoever's integrating this.
    """
    success: bool
    error: Optional[str] = None

    scene_metadata: Dict[str, Any] = field(default_factory=dict)
    n_regions: int = 0
    total_oil_area_km2: float = 0.0
    regions: List[Dict[str, Any]] = field(default_factory=list)

    probability_mask_tif: str = ""
    regions_geojson: str = ""
    detection_report_json: str = ""

    def to_dict(self) -> dict:
        """JSON-serializable representation, for API responses or logging."""
        return asdict(self)


# =========================
#  THE TWO PUBLIC FUNCTIONS
# =========================

def search(request: SearchRequest) -> List[SceneInfo]:
    """
    Lists available Sentinel-1 GRD passes for a scene source -- READ ONLY,
    downloads nothing. This is the "what's available" half of the
    contract; detect() is "go get one and analyze it". Use this first when
    you don't already know which pass (pick_index) you want.
    """
    if not request.event_key and not (request.bbox and request.datetime_range):
        raise ValueError("search() needs either event_key, or both bbox and datetime_range")

    token = fetch_s1.get_cdse_access_token(
        fetch_s1.CDSE_USERNAME, fetch_s1.CDSE_PASSWORD, fetch_s1.CDSE_TOTP
    )

    bbox, datetime_range = request.bbox, request.datetime_range
    if request.event_key:
        cfg = fetch_s1._resolve_scene_config(request.event_key)
        bbox, datetime_range = cfg["bbox"], cfg["datetime"]

    items = fetch_s1.search_scenes_list(token, bbox, datetime_range, limit=request.limit)
    return [
        SceneInfo(
            catalog_id=item.get("id"),
            datetime=item.get("properties", {}).get("datetime"),
            orbit_state=item.get("properties", {}).get("sat:orbit_state"),
        )
        for item in items
    ]


def detect(request: DetectionRequest) -> DetectionResult:
    """
    The one entry point for full detection: resolve the scene (fetch, or
    use a provided path) -> SNAP preprocess -> CFAR pre-filter -> classifier
    + segmentor -> georeferenced regions -> written report. Returns a
    DetectionResult; see its docstring for the success/error contract.
    """
    validation_error = request.validate()
    if validation_error:
        return DetectionResult(success=False, error=validation_error)

    try:
        os.makedirs(request.output_dir, exist_ok=True)

        if request.input_safe_path:
            safe_path = pi.resolve_safe_input(request.input_safe_path, request.output_dir)
        elif request.event_key:
            safe_path = fetch_s1.fetch_known_event(
                request.event_key, pick_index=request.pick_index,
                work_dir=os.path.join(request.output_dir, "download"),
            )
        else:  # bbox + datetime_range, validated above
            safe_path = fetch_s1.fetch_s1_scene(
                bbox=request.bbox, datetime_range=request.datetime_range,
                work_dir=os.path.join(request.output_dir, "download"),
            )

    except (RuntimeError, KeyError, IndexError) as e:
        # Expected failure modes: no passes found, unresolvable OData
        # lookup, bad event key, pick_index out of range, etc.
        return DetectionResult(success=False, error=str(e))

    try:
        outputs = pi.run_preprocess_and_infer(
            safe_path, request.output_dir, use_cfar=request.use_cfar,
            cfar_k=request.cfar_k, strip_rows=request.strip_rows,
        )
    except RuntimeError as e:
        # Expected failure mode: SNAP gpt itself failed (bad install, bad
        # product, etc.) -- run_snap_preprocessing already raises RuntimeError
        # with a clear message in that case.
        return DetectionResult(success=False, error=str(e))

    with open(outputs["detection_report"], "r") as f:
        report = json.load(f)

    return DetectionResult(
        success=True,
        scene_metadata=report["scene_metadata"],
        n_regions=report["detection_summary"]["n_regions"],
        total_oil_area_km2=report["detection_summary"]["total_oil_area_km2"],
        regions=report["regions"],
        probability_mask_tif=outputs["mask_tif"],
        regions_geojson=outputs["regions_geojson"],
        detection_report_json=outputs["detection_report"],
    )
