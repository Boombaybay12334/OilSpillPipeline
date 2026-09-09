import os
import json
import math
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv


# ============================================================
# CONFIG
# ============================================================

load_dotenv()

GFW_API_TOKEN = os.getenv("GFW_API_TOKEN", "").strip()

INPUT_HANDOFF_PATH = os.getenv(
    "INPUT_HANDOFF_PATH",
    "./sanchi_2018_stage2_handoff.json"
)

INPUT_OBSERVATION_SUMMARY_PATH = os.getenv(
    "INPUT_OBSERVATION_SUMMARY_PATH",
    "./sanchi_2018_observation_summary.json"
)

OUTPUT_DIR = os.getenv(
    "OUTPUT_DIR",
    "./ais_attribution_output"
)

SPATIAL_PADDING_DEG = float(
    os.getenv("SPATIAL_PADDING_DEG", "2.0")
)

TIME_PADDING_HOURS = float(
    os.getenv("TIME_PADDING_HOURS", "12")
)

GFW_SPATIAL_RESOLUTION = os.getenv(
    "GFW_SPATIAL_RESOLUTION",
    "HIGH"
)

GFW_TEMPORAL_RESOLUTION = os.getenv(
    "GFW_TEMPORAL_RESOLUTION",
    "HOURLY"
)

GFW_GROUP_BY = os.getenv(
    "GFW_GROUP_BY",
    "MMSI"
)

MATCH_SIGMA_KM = float(
    os.getenv("MATCH_SIGMA_KM", "15")
)

MIN_MATCH_SCORE = float(
    os.getenv("MIN_MATCH_SCORE", "0.0")
)

TOP_MATCHES_PER_VESSEL = int(
    os.getenv("TOP_MATCHES_PER_VESSEL", "10")
)

HTTP_TIMEOUT_SECONDS = int(
    os.getenv("HTTP_TIMEOUT_SECONDS", "120")
)

HTTP_RETRIES = int(
    os.getenv("HTTP_RETRIES", "3")
)

REPORT_POLL_SECONDS = int(
    os.getenv("REPORT_POLL_SECONDS", "10")
)

REPORT_MAX_WAIT_MINUTES = int(
    os.getenv("REPORT_MAX_WAIT_MINUTES", "15")
)

# Number of top MMSIs whose identities we resolve through
# the GFW Vessel API.
VESSEL_IDENTITY_TOP_N = int(
    os.getenv("VESSEL_IDENTITY_TOP_N", "100")
)

# Soft speed threshold used only as a trajectory-consistency
# penalty. We do NOT hard-filter vessels because vessel types
# and AIS gaps vary.
SPEED_SOFT_LIMIT_KNOTS = float(
    os.getenv("SPEED_SOFT_LIMIT_KNOTS", "45")
)

# Minimum probability represented by the top source cells
# before treating a probability field as sufficiently informative.
MIN_SOURCE_PROBABILITY_MASS = float(
    os.getenv("MIN_SOURCE_PROBABILITY_MASS", "0.01")
)


GFW_REPORT_URL = (
    "https://gateway.api.globalfishingwatch.org/v3/4wings/report"
)

GFW_LAST_REPORT_URL = (
    "https://gateway.api.globalfishingwatch.org/v3/4wings/report/last-report"
)

GFW_VESSEL_SEARCH_URL = (
    "https://gateway.api.globalfishingwatch.org/v3/vessels/search"
)

GFW_VESSEL_DATASET = (
    "public-global-vessel-identity:latest"
)


# ============================================================
# BASIC HELPERS
# ============================================================

def utc_now():
    return datetime.now(timezone.utc)


def parse_datetime(value):
    if value is None:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    text = str(value).strip()

    if not text:
        return None

    # ISO UTC
    try:
        dt = datetime.fromisoformat(
            text.replace("Z", "+00:00")
        )

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    except Exception:
        pass

    # GFW hourly date format:
    # 2018-01-25 10:00
    for fmt in (
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(
                text,
                fmt
            ).replace(tzinfo=timezone.utc)
        except Exception:
            continue

    return None


def iso_utc(dt):
    if dt is None:
        return None

    return dt.astimezone(timezone.utc).replace(
        microsecond=0
    ).isoformat().replace("+00:00", "Z")


def haversine_km(lat1, lon1, lat2, lon2):
    """
    Great-circle distance between two WGS84 points.
    """

    r = 6371.0088

    p1 = math.radians(lat1)
    p2 = math.radians(lat2)

    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)

    a = (
        math.sin(dp / 2) ** 2
        + math.cos(p1)
        * math.cos(p2)
        * math.sin(dl / 2) ** 2
    )

    return 2 * r * math.asin(
        min(1.0, math.sqrt(a))
    )


def gaussian(distance_km, sigma_km):
    if sigma_km <= 0:
        return 0.0

    return math.exp(
        -0.5 * (distance_km / sigma_km) ** 2
    )


def safe_float(value):
    try:
        return float(value)
    except Exception:
        return None


def safe_int(value):
    try:
        return int(value)
    except Exception:
        return None


# ============================================================
# LOAD INPUTS
# ============================================================

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_event_id(handoff):
    return (
        handoff.get("event_id")
        or handoff.get("observation", {}).get("catalog_id")
        or "oil_spill_event"
    )


# ============================================================
# STAGE-2 SOURCE PROBABILITY FIELD
# ============================================================

def extract_source_probability_field(handoff):
    """
    Converts:

        origin_hypotheses:
        [
            {
                time_utc,
                hours_before_observation,
                top_cells: [
                    {
                        lon_center,
                        lat_center,
                        probability,
                        particle_count
                    }
                ]
            }
        ]

    into a clean hourly probability field.
    """

    hypotheses = handoff.get(
        "origin_hypotheses",
        []
    )

    result = []

    for hypothesis in hypotheses:

        t = parse_datetime(
            hypothesis.get("time_utc")
        )

        if t is None:
            continue

        cells = []

        for cell in hypothesis.get(
            "top_cells",
            []
        ):

            lat = safe_float(
                cell.get("lat_center")
            )

            lon = safe_float(
                cell.get("lon_center")
            )

            probability = safe_float(
                cell.get("probability")
            )

            particle_count = safe_int(
                cell.get("particle_count")
            )

            if (
                lat is None
                or lon is None
                or probability is None
            ):
                continue

            cells.append({
                "lat": lat,
                "lon": lon,
                "probability": max(
                    0.0,
                    probability
                ),
                "particle_count": particle_count,
            })

        if not cells:
            continue

        probability_mass = sum(
            c["probability"]
            for c in cells
        )

        result.append({
            "time_utc": t,
            "hours_before_observation": hypothesis.get(
                "hours_before_observation"
            ),
            "cells": cells,
            "probability_mass": probability_mass,
        })

    result.sort(
        key=lambda x: x["time_utc"]
    )

    return result


# ============================================================
# AOI / TIME WINDOW
# ============================================================

def build_aoi(handoff, observation_summary):
    """
    Prefer observation_summary.padded_bbox_wsen.

    Fallback:
        Stage-2 unpadded bbox + SPATIAL_PADDING_DEG
    """

    summary = observation_summary or {}

    bbox = summary.get(
        "padded_bbox_wsen"
    )

    if bbox and len(bbox) == 4:
        return (
            float(bbox[0]),
            float(bbox[1]),
            float(bbox[2]),
            float(bbox[3]),
            "observation_summary.padded_bbox_wsen"
        )

    bbox = (
        handoff
        .get("observation", {})
        .get("unpadded_bbox_wsen")
    )

    if not bbox or len(bbox) != 4:
        raise RuntimeError(
            "Could not find unpadded_bbox_wsen in Stage-2 handoff."
        )

    west = float(bbox[0]) - SPATIAL_PADDING_DEG
    south = float(bbox[1]) - SPATIAL_PADDING_DEG
    east = float(bbox[2]) + SPATIAL_PADDING_DEG
    north = float(bbox[3]) + SPATIAL_PADDING_DEG

    return (
        west,
        south,
        east,
        north,
        "handoff.unpadded_bbox_wsen + padding"
    )


def build_time_window(handoff, observation_summary):
    """
    Prefer observation_summary.search_window_*.

    Fallback:
        Stage-2 simulation_start/end +/- padding.
    """

    summary = observation_summary or {}

    start = parse_datetime(
        summary.get(
            "search_window_start_utc"
        )
    )

    end = parse_datetime(
        summary.get(
            "search_window_end_utc"
        )
    )

    if start and end:
        return (
            start,
            end,
            "observation_summary.search_window_*"
        )

    backtracking = handoff.get(
        "backtracking",
        {}
    )

    sim_start = parse_datetime(
        backtracking.get(
            "simulation_start_utc"
        )
    )

    sim_end = parse_datetime(
        backtracking.get(
            "simulation_end_utc"
        )
    )

    if not sim_start or not sim_end:
        raise RuntimeError(
            "Could not determine AIS time window."
        )

    padding = timedelta(
        hours=TIME_PADDING_HOURS
    )

    return (
        sim_start - padding,
        sim_end + padding,
        "Stage-2 simulation window + padding"
    )


# ============================================================
# GFW REPORT
# ============================================================

def make_polygon(west, south, east, north):
    return {
        "type": "Polygon",
        "coordinates": [[
            [west, south],
            [east, south],
            [east, north],
            [west, north],
            [west, south],
        ]]
    }


def gfw_headers():
    if not GFW_API_TOKEN:
        raise RuntimeError(
            "GFW_API_TOKEN is missing from .env"
        )

    return {
        "Authorization": (
            f"Bearer {GFW_API_TOKEN}"
        ),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def submit_gfw_report(
    polygon,
    start_dt,
    end_dt
):
    """
    Submit one 4Wings report.

    IMPORTANT:
    GFW v3 requires datasets[0] as a QUERY PARAMETER,
    not inside the JSON request body.
    """

    params = {
        "spatial-resolution": GFW_SPATIAL_RESOLUTION,
        "format": "JSON",
        "group-by": GFW_GROUP_BY,
        "temporal-resolution": GFW_TEMPORAL_RESOLUTION,
        "datasets[0]": "public-global-presence:latest",
        "date-range": (
            f"{iso_utc(start_dt)},"
            f"{iso_utc(end_dt)}"
        ),
        "spatial-aggregation": "false",
    }

    payload = {
        "geojson": polygon,
    }

    print(
        "[GFW] submitting one report..."
    )

    print(
        "[GFW] date range:",
        params["date-range"]
    )

    print(
        "[GFW] resolution:",
        GFW_SPATIAL_RESOLUTION,
        "/",
        GFW_TEMPORAL_RESOLUTION
    )

    print(
        "[GFW] group-by:",
        GFW_GROUP_BY
    )

    print(
        "[GFW] dataset:",
        params["datasets[0]"]
    )

    session = requests.Session()

    for attempt in range(
        1,
        HTTP_RETRIES + 1
    ):

        try:

            response = session.post(
                GFW_REPORT_URL,
                headers=gfw_headers(),
                params=params,
                json=payload,
                timeout=HTTP_TIMEOUT_SECONDS,
            )

            # Do not retry malformed requests.
            if response.status_code == 422:
                raise RuntimeError(
                    "GFW returned HTTP 422:\n"
                    + response.text[:5000]
                )

            response.raise_for_status()

            return response.json()

        except RuntimeError:
            raise

        except Exception as exc:

            if attempt >= HTTP_RETRIES:
                raise

            print(
                f"[GFW] request failed "
                f"(attempt {attempt}/{HTTP_RETRIES}): "
                f"{exc}"
            )

            time.sleep(
                2 ** (attempt - 1)
            )

    raise RuntimeError(
        "Unable to submit GFW report."
    )

def poll_gfw_report(report_response):
    """
    Some GFW reports may return asynchronously.

    If the submission already contains the final
    entries payload, return it directly.
    """

    if not isinstance(
        report_response,
        dict
    ):
        return report_response

    if "entries" in report_response:
        return report_response

    report_id = (
        report_response.get("id")
        or report_response.get("reportId")
        or report_response.get("report_id")
    )

    if not report_id:
        return report_response

    print(
        "[GFW] report ID:",
        report_id
    )

    deadline = (
        time.time()
        + REPORT_MAX_WAIT_MINUTES * 60
    )

    session = requests.Session()

    while time.time() < deadline:

        try:

            response = session.get(
                GFW_LAST_REPORT_URL,
                headers=gfw_headers(),
                timeout=HTTP_TIMEOUT_SECONDS,
            )

            response.raise_for_status()

            data = response.json()

            if "entries" in data:
                return data

            status = str(
                data.get("status", "")
            ).lower()

            print(
                "[GFW] report status:",
                status or "unknown"
            )

            if status in (
                "failed",
                "error",
                "cancelled",
            ):
                raise RuntimeError(
                    "GFW report failed:\n"
                    + json.dumps(
                        data,
                        indent=2
                    )[:5000]
                )

        except Exception as exc:

            print(
                "[GFW] polling error:",
                exc
            )

        time.sleep(
            REPORT_POLL_SECONDS
        )

    raise TimeoutError(
        "GFW report did not finish within "
        f"{REPORT_MAX_WAIT_MINUTES} minutes."
    )


# ============================================================
# GFW RESPONSE PARSER
# ============================================================

def rows_from_gfw(response):
    """
    Actual GFW response shape:

    {
        "entries": [
            {
                "public-global-presence:v4.0": [
                    {...},
                    {...}
                ]
            }
        ]
    }
    """

    if not isinstance(
        response,
        dict
    ):
        return []

    entries = response.get(
        "entries",
        []
    )

    rows = []

    for entry in entries:

        if not isinstance(
            entry,
            dict
        ):
            continue

        for dataset_name, dataset_rows in entry.items():

            if not isinstance(
                dataset_rows,
                list
            ):
                continue

            for row in dataset_rows:

                if not isinstance(
                    row,
                    dict
                ):
                    continue

                clean = dict(row)

                clean["_dataset"] = (
                    dataset_name
                )

                rows.append(clean)

    return rows


def normalize_row(row):
    """
    Normalize a single GFW presence observation.
    """

    # IMPORTANT:
    # `date` is the actual hourly presence observation.
    # entryTimestamp / exitTimestamp describe the presence
    # interval and are not used as the observation timestamp.

    dt = parse_datetime(
        row.get("date")
    )

    if dt is None:
        dt = parse_datetime(
            row.get("entryTimestamp")
        )

    lat = safe_float(
        row.get("lat")
    )

    lon = safe_float(
        row.get("lon")
    )

    mmsi = row.get("mmsi")

    if mmsi is not None:
        mmsi = str(mmsi)

    if (
        dt is None
        or lat is None
        or lon is None
        or not mmsi
    ):
        return None

    return {
        "time_utc": dt,
        "lat": lat,
        "lon": lon,
        "mmsi": mmsi,
        "hours": safe_float(
            row.get("hours")
        ),
        "entry_timestamp": (
            row.get("entryTimestamp")
        ),
        "exit_timestamp": (
            row.get("exitTimestamp")
        ),
        "dataset": row.get(
            "_dataset"
        ),
    }


def parse_gfw_rows(response):
    raw_rows = rows_from_gfw(
        response
    )

    normalized = []

    for row in raw_rows:

        clean = normalize_row(
            row
        )

        if clean is not None:
            normalized.append(
                clean
            )

    normalized.sort(
        key=lambda x: (
            x["mmsi"],
            x["time_utc"]
        )
    )

    return normalized


# ============================================================
# AIS INDEX
# ============================================================

def build_ais_index(rows):
    """
    MMSI -> hourly observations
    """

    index = {}

    for row in rows:

        mmsi = row["mmsi"]

        index.setdefault(
            mmsi,
            []
        ).append(row)

    return index


# ============================================================
# SOURCE PROBABILITY MATCHING
# ============================================================

def probability_field_match(
    ais_lat,
    ais_lon,
    hypothesis,
    sigma_km
):
    """
    Weighted compatibility between one AIS position
    and the entire Stage-2 probability field for that hour.

    This is better than simply taking the closest/top
    cell because it uses the probability values themselves.

        compatibility =
            sum(
                probability_i *
                Gaussian(distance_i)
            )

    Also returns the probability-weighted mean distance.
    """

    cells = hypothesis["cells"]

    if not cells:
        return {
            "compatibility": 0.0,
            "distance_km": None,
            "probability_mass": 0.0,
        }

    weighted_score = 0.0
    weighted_distance = 0.0
    total_probability = 0.0

    for cell in cells:

        p = max(
            0.0,
            float(
                cell["probability"]
            )
        )

        if p <= 0:
            continue

        d = haversine_km(
            ais_lat,
            ais_lon,
            cell["lat"],
            cell["lon"]
        )

        kernel = gaussian(
            d,
            sigma_km
        )

        weighted_score += (
            p * kernel
        )

        weighted_distance += (
            p * d
        )

        total_probability += p

    if total_probability <= 0:
        return {
            "compatibility": 0.0,
            "distance_km": None,
            "probability_mass": 0.0,
        }

    # Normalize by represented probability mass.
    #
    # This prevents a hypothesis with more listed top
    # cells from automatically getting a larger score.
    normalized_score = (
        weighted_score
        / total_probability
    )

    mean_distance = (
        weighted_distance
        / total_probability
    )

    return {
        "compatibility": normalized_score,
        "distance_km": mean_distance,
        "probability_mass": total_probability,
    }


# ============================================================
# TIME MATCHING
# ============================================================

def nearest_ais_row(
    rows,
    target_time,
    max_delta_hours=0.75
):
    """
    Find nearest AIS hourly observation for a vessel.

    GFW is hourly, so 45 minutes gives us some tolerance
    without allowing arbitrary time shifts.
    """

    if not rows:
        return None

    best = None
    best_delta = None

    for row in rows:

        delta = abs(
            (
                row["time_utc"]
                - target_time
            ).total_seconds()
        )

        if (
            best_delta is None
            or delta < best_delta
        ):
            best = row
            best_delta = delta

    if best is None:
        return None

    if best_delta > (
        max_delta_hours * 3600
    ):
        return None

    return best


# ============================================================
# TRAJECTORY CONSISTENCY
# ============================================================

def implied_speed_knots(
    row1,
    row2
):
    if not row1 or not row2:
        return None

    dt_hours = (
        row2["time_utc"]
        - row1["time_utc"]
    ).total_seconds() / 3600.0

    if dt_hours <= 0:
        return None

    distance_km = haversine_km(
        row1["lat"],
        row1["lon"],
        row2["lat"],
        row2["lon"]
    )

    km_per_hour = (
        distance_km
        / dt_hours
    )

    return km_per_hour / 1.852


def speed_penalty(
    speed_knots,
    soft_limit
):
    """
    Soft penalty.

    <= limit:
        1.0

    > limit:
        smoothly decreases.

    We don't hard reject because AIS can contain
    gaps / position artifacts and some vessels move fast.
    """

    if speed_knots is None:
        return 1.0

    if speed_knots <= soft_limit:
        return 1.0

    ratio = (
        speed_knots
        / soft_limit
    )

    return 1.0 / (
        1.0
        + (ratio - 1.0) ** 2
    )


# ============================================================
# VESSEL TYPE PRIOR
# ============================================================

def vessel_type_prior(shiptype):
    if not shiptype:
        return 0.30

    text = str(
        shiptype
    ).upper()

    # GFW vessel categories vary. Keep this deliberately
    # broad rather than pretending every category is exact.

    if any(
        x in text
        for x in (
            "TANKER",
            "OIL_TANKER",
            "CHEMICAL_TANKER",
            "LNG",
            "LPG",
        )
    ):
        return 1.00

    if any(
        x in text
        for x in (
            "CARGO",
            "CONTAINER",
            "BULK",
            "GENERAL_CARGO",
        )
    ):
        return 0.80

    if "CARRIER" in text:
        return 0.75

    if any(
        x in text
        for x in (
            "BUNKER",
            "FUEL",
        )
    ):
        return 0.80

    if any(
        x in text
        for x in (
            "SUPPORT",
            "OFFSHORE",
        )
    ):
        return 0.65

    if "TUG" in text:
        return 0.55

    if "FISH" in text:
        return 0.45

    if any(
        x in text
        for x in (
            "PASSENGER",
            "CRUISE",
            "PLEASURE",
        )
    ):
        return 0.20

    return 0.30


# ============================================================
# SCORE ONE VESSEL
# ============================================================

def score_vessel(
    mmsi,
    ais_rows,
    hypotheses
):
    """
    Main attribution score.

    For every Stage-2 hour:

        AIS position
             ↓
        Stage-2 probability field
             ↓
        probability-weighted spatial compatibility

    Then add:

        temporal coverage
        consecutive hit behavior
        trajectory speed consistency
    """

    if not ais_rows:
        return None

    matched = []

    total_compatibility = 0.0
    matched_hours = 0

    consecutive = 0
    longest_consecutive = 0

    speeds = []
    speed_penalties = []

    previous_match = None

    for hypothesis in hypotheses:

        target_time = (
            hypothesis["time_utc"]
        )

        ais = nearest_ais_row(
            ais_rows,
            target_time
        )

        if ais is None:
            consecutive = 0
            continue

        match = probability_field_match(
            ais["lat"],
            ais["lon"],
            hypothesis,
            MATCH_SIGMA_KM
        )

        compatibility = (
            match["compatibility"]
        )

        # Count a temporal hit when there is
        # meaningful spatial compatibility.
        is_hit = (
            compatibility >= MIN_MATCH_SCORE
        )

        if is_hit:

            matched_hours += 1

            total_compatibility += (
                compatibility
            )

            consecutive += 1

            longest_consecutive = max(
                longest_consecutive,
                consecutive
            )

            if previous_match is not None:

                speed = implied_speed_knots(
                    previous_match,
                    ais
                )

                if speed is not None:
                    speeds.append(
                        speed
                    )

                    speed_penalties.append(
                        speed_penalty(
                            speed,
                            SPEED_SOFT_LIMIT_KNOTS
                        )
                    )

            previous_match = ais

            matched.append({
                "time_utc": iso_utc(
                    target_time
                ),
                "hours_before_observation":
                    hypothesis.get(
                        "hours_before_observation"
                    ),
                "ais_lat": ais["lat"],
                "ais_lon": ais["lon"],
                "distance_km": match[
                    "distance_km"
                ],
                "compatibility": compatibility,
                "probability_mass": match[
                    "probability_mass"
                ],
            })

        else:
            consecutive = 0

    modeled_hours = len(
        hypotheses
    )

    if modeled_hours <= 0:
        return None

    temporal_coverage = (
        matched_hours
        / modeled_hours
    )

    if matched_hours > 0:
        mean_compatibility = (
            total_compatibility
            / matched_hours
        )
    else:
        mean_compatibility = 0.0

    if speed_penalties:
        trajectory_consistency = (
            sum(speed_penalties)
            / len(speed_penalties)
        )
    else:
        trajectory_consistency = 1.0

    # Reward sustained temporal consistency,
    # but don't allow coverage to completely dominate.
    coverage_factor = (
        0.5
        + 0.5 * temporal_coverage
    )

    # Reward vessels that maintain compatible
    # positions over multiple consecutive hours.
    if modeled_hours > 1:
        continuity_factor = (
            0.75
            + 0.25
            * (
                longest_consecutive
                / modeled_hours
            )
        )
    else:
        continuity_factor = 1.0

    # Trajectory consistency factor.
    trajectory_factor = (
        0.75
        + 0.25
        * trajectory_consistency
    )

    base_score = (
        mean_compatibility
        * coverage_factor
        * continuity_factor
        * trajectory_factor
    )

    return {
        "mmsi": mmsi,

        "score": base_score,

        "mean_hourly_compatibility":
            mean_compatibility,

        "temporal_coverage":
            temporal_coverage,

        "matched_hours":
            matched_hours,

        "modeled_hours":
            modeled_hours,

        "longest_consecutive_match":
            longest_consecutive,

        "trajectory_consistency":
            trajectory_consistency,

        "mean_speed_knots": (
            sum(speeds) / len(speeds)
            if speeds
            else None
        ),

        "max_speed_knots": (
            max(speeds)
            if speeds
            else None
        ),

        "top_matches": sorted(
            matched,
            key=lambda x:
                x["compatibility"],
            reverse=True
        )[:TOP_MATCHES_PER_VESSEL],
    }


# ============================================================
# GFW VESSEL IDENTITY
# ============================================================

def extract_identity_from_entry(entry):
    """
    GFW search response contains:

        entries[]
          registryInfo[]
          selfReportedInfo[]

    We prefer selfReportedInfo because it is directly
    tied to AIS identity, but use registryInfo as fallback.
    """

    if not isinstance(
        entry,
        dict
    ):
        return None

    candidates = []

    self_reported = entry.get(
        "selfReportedInfo",
        []
    )

    registry_info = entry.get(
        "registryInfo",
        []
    )

    if isinstance(
        self_reported,
        list
    ):
        candidates.extend(
            self_reported
        )

    if isinstance(
        registry_info,
        list
    ):
        candidates.extend(
            registry_info
        )

    if not candidates:
        return None

    # Prefer entries with matching MMSI/SSVID,
    # then prefer entries containing useful identity data.
    candidates.sort(
        key=lambda x: (
            bool(
                x.get("ssvid")
                or x.get("mmsi")
            ),
            bool(
                x.get("shipname")
            ),
            bool(
                x.get("imo")
            ),
            bool(
                x.get("flag")
            ),
        ),
        reverse=True
    )

    return candidates[0]


def lookup_vessel_identity(
    mmsi,
    session=None
):
    """
    Search GFW Vessel API by MMSI/SSVID.

    Current GFW API:
        GET /v3/vessels/search

    Example:
        ?query=412331038
        &datasets[0]=public-global-vessel-identity:latest
    """

    if not GFW_API_TOKEN:
        return {
            "lookup_status": "missing_token"
        }

    if session is None:
        session = requests.Session()

    params = [
        (
            "query",
            str(mmsi)
        ),
        (
            "datasets[0]",
            GFW_VESSEL_DATASET
        ),
    ]

    try:

        response = session.get(
            GFW_VESSEL_SEARCH_URL,
            headers={
                "Authorization":
                    f"Bearer {GFW_API_TOKEN}",
                "Accept":
                    "application/json",
            },
            params=params,
            timeout=HTTP_TIMEOUT_SECONDS,
        )

        if response.status_code == 404:
            return {
                "lookup_status": "not_found"
            }

        if response.status_code == 429:
            return {
                "lookup_status":
                    "rate_limited"
            }

        response.raise_for_status()

        data = response.json()

        entries = data.get(
            "entries",
            []
        )

        if not entries:
            return {
                "lookup_status":
                    "not_found"
            }

        identity = (
            extract_identity_from_entry(
                entries[0]
            )
        )

        if not identity:
            return {
                "lookup_status":
                    "no_identity_record"
            }

        return {
            "lookup_status": "found",

            "gfw_vessel_id":
                identity.get("id"),

            "mmsi":
                identity.get(
                    "ssvid",
                    identity.get("mmsi")
                ),

            "shipname":
                identity.get(
                    "shipname"
                ),

            "imo":
                identity.get(
                    "imo"
                ),

            "flag":
                identity.get(
                    "flag"
                ),

            "callsign":
                identity.get(
                    "callsign"
                ),

            "shiptype":
                identity.get(
                    "shiptype"
                ),

            "geartype":
                identity.get(
                    "geartype"
                ),

            "match_fields":
                identity.get(
                    "matchFields"
                ),

            "source_code":
                identity.get(
                    "sourceCode"
                ),

            "transmission_date_from":
                identity.get(
                    "transmissionDateFrom"
                ),

            "transmission_date_to":
                identity.get(
                    "transmissionDateTo"
                ),
        }

    except Exception as exc:

        return {
            "lookup_status": "error",
            "error": str(exc),
        }


def enrich_candidates(
    candidates
):
    """
    Resolve identity only for the strongest candidates.

    This prevents hundreds/thousands of API requests.
    """

    session = requests.Session()

    total = min(
        VESSEL_IDENTITY_TOP_N,
        len(candidates)
    )

    print()
    print(
        "[GFW VESSEL API] resolving identities..."
    )

    print(
        "[GFW VESSEL API] candidates:",
        total
    )

    for index in range(total):

        candidate = candidates[index]

        mmsi = candidate.get(
            "mmsi"
        )

        print(
            f"[IDENTITY] "
            f"{index + 1}/{total} "
            f"MMSI={mmsi}"
        )

        identity = lookup_vessel_identity(
            mmsi,
            session=session
        )

        candidate["vessel_identity"] = (
            identity
        )

        # Add type prior AFTER identity lookup.
        shiptype = identity.get(
            "shiptype"
        )

        prior = vessel_type_prior(
            shiptype
        )

        candidate["vessel_type_prior"] = (
            prior
        )

        # Apply type prior as a modest multiplier.
        #
        # IMPORTANT:
        # We do not let vessel type dominate spatial/
        # temporal evidence.
        raw_score = candidate.get(
            "score",
            0.0
        )

        candidate["score_before_type_prior"] = (
            raw_score
        )

        candidate["score"] = (
            raw_score
            * (
                0.5
                + 0.5 * prior
            )
        )

        time.sleep(
            0.05
        )

    # Candidates outside the identity lookup remain
    # valid AIS candidates, but have unknown identity.
    for candidate in candidates[total:]:

        candidate.setdefault(
            "vessel_identity",
            {
                "lookup_status":
                    "not_requested"
            }
        )

        candidate.setdefault(
            "vessel_type_prior",
            0.30
        )

        candidate["score_before_type_prior"] = (
            candidate.get(
                "score",
                0.0
            )
        )

    candidates.sort(
        key=lambda x:
            x.get("score", 0.0),
        reverse=True
    )

    return candidates


# ============================================================
# OUTPUT
# ============================================================

def write_json(
    path,
    data
):
    path.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with open(
        path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False
        )


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 72)
    print("GFW AIS OIL-SPILL ATTRIBUTION")
    print("=" * 72)

    if not GFW_API_TOKEN:
        raise RuntimeError(
            "GFW_API_TOKEN is missing."
        )

    handoff_path = Path(
        INPUT_HANDOFF_PATH
    )

    summary_path = Path(
        INPUT_OBSERVATION_SUMMARY_PATH
    )

    output_dir = Path(
        OUTPUT_DIR
    )

    handoff = load_json(
        handoff_path
    )

    observation_summary = {}

    if summary_path.exists():

        observation_summary = (
            load_json(
                summary_path
            )
        )

    event_id = get_event_id(
        handoff
    )

    print(
        "Event:",
        event_id
    )

    print(
        "Input:",
        handoff_path
    )

    print("=" * 72)

    # --------------------------------------------------------
    # Stage-2 probability field
    # --------------------------------------------------------

    hypotheses = (
        extract_source_probability_field(
            handoff
        )
    )

    if not hypotheses:
        raise RuntimeError(
            "No Stage-2 origin hypotheses found."
        )

    print(
        "Source-probability hours:",
        len(hypotheses)
    )

    # --------------------------------------------------------
    # AOI
    # --------------------------------------------------------

    (
        west,
        south,
        east,
        north,
        aoi_source
    ) = build_aoi(
        handoff,
        observation_summary
    )

    print(
        "AIS AOI:",
        f"W={west:.6f}, "
        f"S={south:.6f}, "
        f"E={east:.6f}, "
        f"N={north:.6f}"
    )

    print(
        "AOI source:",
        aoi_source
    )

    polygon = make_polygon(
        west,
        south,
        east,
        north
    )

    # --------------------------------------------------------
    # Time window
    # --------------------------------------------------------

    (
        start_dt,
        end_dt,
        time_source
    ) = build_time_window(
        handoff,
        observation_summary
    )

    print(
        "AIS time:",
        iso_utc(start_dt),
        "->",
        iso_utc(end_dt)
    )

    print(
        "Time source:",
        time_source
    )

    # --------------------------------------------------------
    # GFW report
    # --------------------------------------------------------

    report_response = submit_gfw_report(
        polygon,
        start_dt,
        end_dt
    )

    report_response = poll_gfw_report(
        report_response
    )

    output_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    raw_output_path = (
        output_dir
        / f"{event_id}_gfw_raw.json"
    )

    write_json(
        raw_output_path,
        report_response
    )

    print(
        "[OUTPUT] raw GFW response:",
        raw_output_path
    )

    # --------------------------------------------------------
    # Parse AIS
    # --------------------------------------------------------

    ais_rows = parse_gfw_rows(
        report_response
    )

    print(
        "[GFW] raw vessel rows:",
        len(
            rows_from_gfw(
                report_response
            )
        )
    )

    print(
        "[GFW] normalized AIS rows:",
        len(ais_rows)
    )

    if not ais_rows:
        raise RuntimeError(
            "GFW returned zero usable AIS rows."
        )

    ais_index = build_ais_index(
        ais_rows
    )

    print(
        "[GFW] unique MMSIs:",
        len(ais_index)
    )

    # --------------------------------------------------------
    # Score vessels
    # --------------------------------------------------------

    print()
    print(
        "[SCORING] scoring MMSIs..."
    )

    candidates = []

    for mmsi, vessel_rows in ais_index.items():

        result = score_vessel(
            mmsi,
            vessel_rows,
            hypotheses
        )

        if result is None:
            continue

        candidates.append(
            result
        )

    candidates.sort(
        key=lambda x:
            x.get("score", 0.0),
        reverse=True
    )

    print(
        "[SCORING] candidates:",
        len(candidates)
    )

    # --------------------------------------------------------
    # Resolve vessel identities
    # --------------------------------------------------------

    candidates = enrich_candidates(
        candidates
    )

    # --------------------------------------------------------
    # Final output
    # --------------------------------------------------------

    final_output = {
        "schema_version":
            "1.1",

        "event_id":
            event_id,

        "generated_at_utc":
            iso_utc(
                utc_now()
            ),

        "method": {
            "stage_1":
                "Satellite oil-spill detection",

            "stage_2":
                "OpenDrift/OpenOil deterministic "
                "backward Lagrangian tracking",

            "stage_3":
                "Global Fishing Watch AIS-derived "
                "vessel presence attribution",

            "gfw_presence_dataset":
                "public-global-presence:latest",

            "gfw_vessel_identity_dataset":
                GFW_VESSEL_DATASET,

            "spatial_resolution":
                GFW_SPATIAL_RESOLUTION,

            "temporal_resolution":
                GFW_TEMPORAL_RESOLUTION,

            "group_by":
                GFW_GROUP_BY,

            "match_sigma_km":
                MATCH_SIGMA_KM,

            "scoring":
                "Probability-weighted spatial "
                "compatibility + temporal coverage "
                "+ consecutive compatibility "
                "+ trajectory consistency "
                "+ modest vessel-type prior",
        },

        "inputs": {
            "stage2_handoff":
                str(handoff_path),

            "observation_summary":
                str(summary_path)
                if summary_path.exists()
                else None,
        },

        "ais_query": {
            "bbox_wsen": [
                west,
                south,
                east,
                north,
            ],

            "time_start_utc":
                iso_utc(start_dt),

            "time_end_utc":
                iso_utc(end_dt),

            "aoi_source":
                aoi_source,

            "time_source":
                time_source,
        },

        "stage2_probability_field": [
            {
                "time_utc":
                    iso_utc(
                        h["time_utc"]
                    ),

                "hours_before_observation":
                    h[
                        "hours_before_observation"
                    ],

                "probability_mass":
                    h[
                        "probability_mass"
                    ],

                "cell_count":
                    len(
                        h["cells"]
                    ),

                "cells":
                    h["cells"],
            }

            for h in hypotheses
        ],

        "ais_observation_count":
            len(ais_rows),

        "unique_mmsi_count":
            len(ais_index),

        "vessel_identity_lookup_top_n":
            VESSEL_IDENTITY_TOP_N,

        "candidates":
            candidates,
    }

    attribution_output_path = (
        output_dir
        / f"{event_id}_ais_attribution.json"
    )

    write_json(
        attribution_output_path,
        final_output
    )

    print()
    print(
        "[OUTPUT] attribution:",
        attribution_output_path
    )

    # --------------------------------------------------------
    # Console summary
    # --------------------------------------------------------

    print()
    print("=" * 72)
    print("TOP AIS CANDIDATES")
    print("=" * 72)

    for i, candidate in enumerate(
        candidates[:20],
        start=1
    ):

        identity = candidate.get(
            "vessel_identity",
            {}
        )

        name = identity.get(
            "shipname"
        )

        imo = identity.get(
            "imo"
        )

        flag = identity.get(
            "flag"
        )

        shiptype = identity.get(
            "shiptype"
        )

        score = candidate.get(
            "score",
            0.0
        )

        coverage = (
            candidate.get(
                "temporal_coverage",
                0.0
            )
            * 100
        )

        print(
            f"#{i:2d} "
            f"MMSI={candidate['mmsi']} "
            f"name={name} "
            f"IMO={imo} "
            f"flag={flag} "
            f"type={shiptype} "
            f"score={score:.6f} "
            f"coverage={coverage:.1f}%"
        )

    print()
    print(
        "Done."
    )


if __name__ == "__main__":
    main()