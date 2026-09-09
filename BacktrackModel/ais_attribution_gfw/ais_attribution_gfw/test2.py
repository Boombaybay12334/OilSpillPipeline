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

VESSEL_IDENTITY_TOP_N = int(
    os.getenv("VESSEL_IDENTITY_TOP_N", "100")
)

SPEED_SOFT_LIMIT_KNOTS = float(
    os.getenv("SPEED_SOFT_LIMIT_KNOTS", "45")
)

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

    try:
        dt = datetime.fromisoformat(
            text.replace("Z", "+00:00")
        )

        if dt.tzinfo is None:
            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.astimezone(timezone.utc)

    except Exception:
        pass

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
            ).replace(
                tzinfo=timezone.utc
            )
        except Exception:
            continue

    return None


def iso_utc(dt):
    if dt is None:
        return None

    return (
        dt.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def haversine_km(
    lat1,
    lon1,
    lat2,
    lon2
):
    r = 6371.0088

    p1 = math.radians(lat1)
    p2 = math.radians(lat2)

    dp = math.radians(
        lat2 - lat1
    )

    dl = math.radians(
        lon2 - lon1
    )

    a = (
        math.sin(dp / 2) ** 2
        +
        math.cos(p1)
        * math.cos(p2)
        * math.sin(dl / 2) ** 2
    )

    return (
        2
        * r
        * math.asin(
            min(
                1.0,
                math.sqrt(a)
            )
        )
    )


def gaussian(
    distance_km,
    sigma_km
):
    if sigma_km <= 0:
        return 0.0

    return math.exp(
        -0.5
        * (distance_km / sigma_km) ** 2
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


def load_json(path):
    with open(
        path,
        "r",
        encoding="utf-8"
    ) as f:
        return json.load(f)


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
# EVENT
# ============================================================

def get_event_id(handoff):
    return (
        handoff.get("event_id")
        or
        handoff.get(
            "observation",
            {}
        ).get("catalog_id")
        or
        "oil_spill_event"
    )


# ============================================================
# STAGE-2 PROBABILITY FIELD
# ============================================================

def extract_source_probability_field(
    handoff
):
    hypotheses = handoff.get(
        "origin_hypotheses",
        []
    )

    result = []

    for hypothesis in hypotheses:

        t = parse_datetime(
            hypothesis.get(
                "time_utc"
            )
        )

        if t is None:
            continue

        cells = []

        for cell in hypothesis.get(
            "top_cells",
            []
        ):

            lat = safe_float(
                cell.get(
                    "lat_center"
                )
            )

            lon = safe_float(
                cell.get(
                    "lon_center"
                )
            )

            probability = safe_float(
                cell.get(
                    "probability"
                )
            )

            particle_count = safe_int(
                cell.get(
                    "particle_count"
                )
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
                "particle_count":
                    particle_count,
            })

        if not cells:
            continue

        probability_mass = sum(
            c["probability"]
            for c in cells
        )

        result.append({
            "time_utc": t,
            "hours_before_observation":
                hypothesis.get(
                    "hours_before_observation"
                ),
            "cells": cells,
            "probability_mass":
                probability_mass,
        })

    result.sort(
        key=lambda x:
            x["time_utc"]
    )

    return result


# ============================================================
# AOI
# ============================================================

def build_aoi(
    handoff,
    observation_summary
):
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
            "Could not find unpadded_bbox_wsen."
        )

    west = (
        float(bbox[0])
        - SPATIAL_PADDING_DEG
    )

    south = (
        float(bbox[1])
        - SPATIAL_PADDING_DEG
    )

    east = (
        float(bbox[2])
        + SPATIAL_PADDING_DEG
    )

    north = (
        float(bbox[3])
        + SPATIAL_PADDING_DEG
    )

    return (
        west,
        south,
        east,
        north,
        "handoff.unpadded_bbox_wsen + padding"
    )


# ============================================================
# TIME WINDOW
# ============================================================

def build_time_window(
    handoff,
    observation_summary
):
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
# GFW
# ============================================================

def make_polygon(
    west,
    south,
    east,
    north
):
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
            "GFW_API_TOKEN is missing."
        )

    return {
        "Authorization":
            f"Bearer {GFW_API_TOKEN}",
        "Content-Type":
            "application/json",
        "Accept":
            "application/json",
    }


def submit_gfw_report(
    polygon,
    start_dt,
    end_dt
):
    """
    GFW v3 4Wings report.

    datasets[0] MUST be a query parameter.
    """

    params = {
        "spatial-resolution":
            GFW_SPATIAL_RESOLUTION,

        "format":
            "JSON",

        "group-by":
            GFW_GROUP_BY,

        "temporal-resolution":
            GFW_TEMPORAL_RESOLUTION,

        "datasets[0]":
            "public-global-presence:latest",

        "date-range":
            (
                f"{iso_utc(start_dt)},"
                f"{iso_utc(end_dt)}"
            ),

        "spatial-aggregation":
            "false",
    }

    payload = {
        "geojson": polygon
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
                f"(attempt {attempt}/"
                f"{HTTP_RETRIES}): {exc}"
            )

            time.sleep(
                2 ** (attempt - 1)
            )

    raise RuntimeError(
        "Unable to submit GFW report."
    )


def poll_gfw_report(
    report_response
):
    if not isinstance(
        report_response,
        dict
    ):
        return report_response

    if "entries" in report_response:
        return report_response

    report_id = (
        report_response.get("id")
        or
        report_response.get("reportId")
        or
        report_response.get("report_id")
    )

    if not report_id:
        return report_response

    print(
        "[GFW] report ID:",
        report_id
    )

    deadline = (
        time.time()
        +
        REPORT_MAX_WAIT_MINUTES * 60
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
                data.get(
                    "status",
                    ""
                )
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
                    +
                    json.dumps(
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

def rows_from_gfw(
    response
):
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

                rows.append(
                    clean
                )

    return rows


def normalize_row(
    row
):
    dt = parse_datetime(
        row.get("date")
    )

    if dt is None:
        dt = parse_datetime(
            row.get(
                "entryTimestamp"
            )
        )

    lat = safe_float(
        row.get("lat")
    )

    lon = safe_float(
        row.get("lon")
    )

    mmsi = row.get(
        "mmsi"
    )

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

        "entry_timestamp":
            row.get(
                "entryTimestamp"
            ),

        "exit_timestamp":
            row.get(
                "exitTimestamp"
            ),

        "dataset":
            row.get(
                "_dataset"
            ),
    }


def parse_gfw_rows(
    response
):
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

def build_ais_index(
    rows
):
    index = {}

    for row in rows:

        mmsi = row["mmsi"]

        index.setdefault(
            mmsi,
            []
        ).append(row)

    return index


# ============================================================
# SOURCE FIELD MATCH
# ============================================================

def probability_field_match(
    ais_lat,
    ais_lon,
    hypothesis,
    sigma_km
):
    cells = hypothesis[
        "cells"
    ]

    if not cells:
        return {
            "compatibility":
                0.0,

            "distance_km":
                None,

            "minimum_distance_km":
                None,

            "best_cell_probability":
                0.0,

            "probability_mass":
                0.0,
        }

    weighted_score = 0.0
    weighted_distance = 0.0
    total_probability = 0.0

    minimum_distance = None
    best_cell_probability = 0.0

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

        if (
            minimum_distance is None
            or d < minimum_distance
        ):
            minimum_distance = d

        if (
            d == minimum_distance
            and p > best_cell_probability
        ):
            best_cell_probability = p

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
            "compatibility":
                0.0,

            "distance_km":
                None,

            "minimum_distance_km":
                None,

            "best_cell_probability":
                0.0,

            "probability_mass":
                0.0,
        }

    normalized_score = (
        weighted_score
        /
        total_probability
    )

    mean_distance = (
        weighted_distance
        /
        total_probability
    )

    return {
        "compatibility":
            normalized_score,

        "distance_km":
            mean_distance,

        "minimum_distance_km":
            minimum_distance,

        "best_cell_probability":
            best_cell_probability,

        "probability_mass":
            total_probability,
    }


# ============================================================
# AIS TIME MATCH
# ============================================================

def nearest_ais_row(
    rows,
    target_time,
    max_delta_hours=0.75
):
    if not rows:
        return None

    best = None
    best_delta = None

    for row in rows:

        delta = abs(
            (
                row["time_utc"]
                -
                target_time
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
        -
        row1["time_utc"]
    ).total_seconds() / 3600.0

    if dt_hours <= 0:
        return None

    distance_km = haversine_km(
        row1["lat"],
        row1["lon"],
        row2["lat"],
        row2["lon"]
    )

    return (
        distance_km
        /
        dt_hours
        /
        1.852
    )


def speed_penalty(
    speed_knots,
    soft_limit
):
    if speed_knots is None:
        return 1.0

    if speed_knots <= soft_limit:
        return 1.0

    ratio = (
        speed_knots
        /
        soft_limit
    )

    return 1.0 / (
        1.0
        +
        (ratio - 1.0) ** 2
    )


# ============================================================
# VESSEL TYPE
# ============================================================

def vessel_type_prior(
    shiptype
):
    if not shiptype:
        return 0.30

    text = str(
        shiptype
    ).upper()

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

    best_match = None

    hourly_scores = []

    for hypothesis in hypotheses:

        target_time = (
            hypothesis[
                "time_utc"
            ]
        )

        ais = nearest_ais_row(
            ais_rows,
            target_time
        )

        if ais is None:

            hourly_scores.append({
                "time_utc":
                    iso_utc(
                        target_time
                    ),

                "hours_before_observation":
                    hypothesis.get(
                        "hours_before_observation"
                    ),

                "ais_present":
                    False,

                "compatibility":
                    0.0,
            })

            consecutive = 0

            continue

        match = probability_field_match(
            ais["lat"],
            ais["lon"],
            hypothesis,
            MATCH_SIGMA_KM
        )

        compatibility = (
            match[
                "compatibility"
            ]
        )

        is_hit = (
            compatibility
            >=
            MIN_MATCH_SCORE
        )

        hourly_record = {
            "time_utc":
                iso_utc(
                    target_time
                ),

            "hours_before_observation":
                hypothesis.get(
                    "hours_before_observation"
                ),

            "ais_present":
                True,

            "ais_lat":
                ais["lat"],

            "ais_lon":
                ais["lon"],

            "compatibility":
                compatibility,

            "probability_mass":
                match[
                    "probability_mass"
                ],

            "mean_distance_km":
                match[
                    "distance_km"
                ],

            "minimum_distance_km":
                match[
                    "minimum_distance_km"
                ],

            "best_cell_probability":
                match[
                    "best_cell_probability"
                ],
        }

        hourly_scores.append(
            hourly_record
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

            detailed_match = {
                "time_utc":
                    iso_utc(
                        target_time
                    ),

                "hours_before_observation":
                    hypothesis.get(
                        "hours_before_observation"
                    ),

                "ais_lat":
                    ais["lat"],

                "ais_lon":
                    ais["lon"],

                "compatibility":
                    compatibility,

                "mean_distance_km":
                    match[
                        "distance_km"
                    ],

                "minimum_distance_km":
                    match[
                        "minimum_distance_km"
                    ],

                "best_cell_probability":
                    match[
                        "best_cell_probability"
                    ],

                "probability_mass":
                    match[
                        "probability_mass"
                    ],
            }

            matched.append(
                detailed_match
            )

            if (
                best_match is None
                or
                compatibility
                >
                best_match[
                    "compatibility"
                ]
            ):
                best_match = (
                    detailed_match
                )

        else:
            consecutive = 0

    modeled_hours = len(
        hypotheses
    )

    if modeled_hours <= 0:
        return None

    temporal_coverage = (
        matched_hours
        /
        modeled_hours
    )

    if matched_hours > 0:

        mean_compatibility = (
            total_compatibility
            /
            matched_hours
        )

    else:
        mean_compatibility = 0.0

    if speed_penalties:

        trajectory_consistency = (
            sum(speed_penalties)
            /
            len(speed_penalties)
        )

    else:
        trajectory_consistency = 1.0

    coverage_factor = (
        0.5
        +
        0.5
        *
        temporal_coverage
    )

    continuity_ratio = (
        longest_consecutive
        /
        modeled_hours
    )

    continuity_factor = (
        0.75
        +
        0.25
        *
        continuity_ratio
    )

    trajectory_factor = (
        0.75
        +
        0.25
        *
        trajectory_consistency
    )

    raw_score = (
        mean_compatibility
        *
        coverage_factor
        *
        continuity_factor
        *
        trajectory_factor
    )

    return {
        # ----------------------------------------------------
        # Identity
        # ----------------------------------------------------

        "mmsi":
            mmsi,

        # ----------------------------------------------------
        # FINAL SCORE
        # ----------------------------------------------------

        "score":
            raw_score,

        "score_before_type_prior":
            raw_score,

        # ----------------------------------------------------
        # PRIMARY COMPONENTS
        # ----------------------------------------------------

        "spatial": {
            "mean_hourly_compatibility":
                mean_compatibility,

            "best_hourly_compatibility":
                (
                    best_match[
                        "compatibility"
                    ]
                    if best_match
                    else 0.0
                ),

            "best_match_distance_km":
                (
                    best_match[
                        "minimum_distance_km"
                    ]
                    if best_match
                    else None
                ),

            "best_match_mean_distance_km":
                (
                    best_match[
                        "mean_distance_km"
                    ]
                    if best_match
                    else None
                ),
        },

        "temporal": {
            "matched_hours":
                matched_hours,

            "modeled_hours":
                modeled_hours,

            "coverage":
                temporal_coverage,

            "coverage_percent":
                temporal_coverage * 100.0,

            "longest_consecutive_match_hours":
                longest_consecutive,

            "continuity_ratio":
                continuity_ratio,
        },

        "trajectory": {
            "consistency":
                trajectory_consistency,

            "mean_speed_knots":
                (
                    sum(speeds)
                    /
                    len(speeds)
                    if speeds
                    else None
                ),

            "max_speed_knots":
                (
                    max(speeds)
                    if speeds
                    else None
                ),

            "speed_samples":
                len(speeds),
        },

        # ----------------------------------------------------
        # SCORE FACTORS
        # ----------------------------------------------------

        "score_components": {
            "mean_spatial_compatibility":
                mean_compatibility,

            "coverage_factor":
                coverage_factor,

            "continuity_factor":
                continuity_factor,

            "trajectory_factor":
                trajectory_factor,

            "type_factor":
                None,
        },

        # ----------------------------------------------------
        # BEST MATCH
        # ----------------------------------------------------

        "best_match":
            best_match,

        # ----------------------------------------------------
        # DETAILED HOURLY MATCHES
        # ----------------------------------------------------

        "hourly_matches":
            hourly_scores,

        # ----------------------------------------------------
        # TOP MATCHES
        # ----------------------------------------------------

        "top_matches":
            sorted(
                matched,
                key=lambda x:
                    x[
                        "compatibility"
                    ],
                reverse=True
            )[
                :TOP_MATCHES_PER_VESSEL
            ],

        # Filled after identity lookup
        "vessel_type_prior":
            None,

        "vessel_identity":
            None,
    }


# ============================================================
# VESSEL IDENTITY
# ============================================================

def extract_identity_from_entry(
    entry
):
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

    candidates.sort(
        key=lambda x: (
            bool(
                x.get("ssvid")
                or
                x.get("mmsi")
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
    if not GFW_API_TOKEN:
        return {
            "lookup_status":
                "missing_token"
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
                "lookup_status":
                    "not_found"
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

        # Preserve the complete identity response
        # fields rather than throwing information away.
        result = dict(identity)

        result["lookup_status"] = (
            "found"
        )

        return result

    except Exception as exc:

        return {
            "lookup_status":
                "error",

            "error":
                str(exc),
        }


def get_identity_field(
    identity,
    *names
):
    if not identity:
        return None

    for name in names:

        value = identity.get(
            name
        )

        if value not in (
            None,
            "",
            [],
            {},
        ):
            return value

    return None


def enrich_candidates(
    candidates
):
    session = requests.Session()

    total = min(
        VESSEL_IDENTITY_TOP_N,
        len(candidates)
    )

    print()
    print(
        "[GFW VESSEL API] "
        "resolving identities..."
    )

    print(
        "[GFW VESSEL API] candidates:",
        total
    )

    for index in range(total):

        candidate = candidates[
            index
        ]

        mmsi = candidate[
            "mmsi"
        ]

        print(
            f"[IDENTITY] "
            f"{index + 1}/{total} "
            f"MMSI={mmsi}"
        )

        identity = (
            lookup_vessel_identity(
                mmsi,
                session=session
            )
        )

        candidate[
            "vessel_identity"
        ] = identity

        # ----------------------------------------------------
        # Extract vessel type from whichever field the
        # identity API actually returned.
        # ----------------------------------------------------

        shiptype = get_identity_field(
            identity,
            "shiptype",
            "shipType",
            "vesselType",
            "type",
        )

        candidate[
            "vessel_type_prior"
        ] = vessel_type_prior(
            shiptype
        )

        type_factor = (
            0.5
            +
            0.5
            *
            candidate[
                "vessel_type_prior"
            ]
        )

        candidate[
            "score_components"
        ][
            "type_factor"
        ] = type_factor

        candidate[
            "score_before_type_prior"
        ] = candidate[
            "score"
        ]

        candidate[
            "score"
        ] = (
            candidate[
                "score_before_type_prior"
            ]
            *
            type_factor
        )

        time.sleep(
            0.05
        )

    # Candidates outside identity lookup
    for candidate in candidates[
        total:
    ]:

        candidate[
            "vessel_identity"
        ] = {
            "lookup_status":
                "not_requested"
        }

        candidate[
            "vessel_type_prior"
        ] = None

        candidate[
            "score_components"
        ][
            "type_factor"
        ] = None

    candidates.sort(
        key=lambda x:
            x.get(
                "score",
                0.0
            ),
        reverse=True
    )

    # Add final rank after re-sorting.
    for rank, candidate in enumerate(
        candidates,
        start=1
    ):
        candidate[
            "rank"
        ] = rank

    return candidates


# ============================================================
# API-FRIENDLY SUMMARY
# ============================================================

def make_candidate_summary(
    candidate
):
    identity = candidate.get(
        "vessel_identity"
    ) or {}

    return {
        "rank":
            candidate.get(
                "rank"
            ),

        "mmsi":
            candidate.get(
                "mmsi"
            ),

        "name":
            get_identity_field(
                identity,
                "shipname",
                "shipName",
                "name",
            ),

        "imo":
            get_identity_field(
                identity,
                "imo",
                "IMO",
            ),

        "flag":
            get_identity_field(
                identity,
                "flag",
                "flagCode",
            ),

        "callsign":
            get_identity_field(
                identity,
                "callsign",
                "callSign",
            ),

        "vessel_type":
            get_identity_field(
                identity,
                "shiptype",
                "shipType",
                "vesselType",
                "type",
            ),

        "score":
            candidate.get(
                "score"
            ),

        "spatial_compatibility":
            candidate[
                "spatial"
            ].get(
                "mean_hourly_compatibility"
            ),

        "best_spatial_compatibility":
            candidate[
                "spatial"
            ].get(
                "best_hourly_compatibility"
            ),

        "best_distance_km":
            candidate[
                "spatial"
            ].get(
                "best_match_distance_km"
            ),

        "temporal_coverage":
            candidate[
                "temporal"
            ].get(
                "coverage"
            ),

        "matched_hours":
            candidate[
                "temporal"
            ].get(
                "matched_hours"
            ),

        "longest_consecutive_match_hours":
            candidate[
                "temporal"
            ].get(
                "longest_consecutive_match_hours"
            ),

        "trajectory_consistency":
            candidate[
                "trajectory"
            ].get(
                "consistency"
            ),

        "mean_speed_knots":
            candidate[
                "trajectory"
            ].get(
                "mean_speed_knots"
            ),

        "max_speed_knots":
            candidate[
                "trajectory"
            ].get(
                "max_speed_knots"
            ),

        "best_match":
            candidate.get(
                "best_match"
            ),
    }

# ============================================================
# COMPACT FINAL SHIP OUTPUT
# ============================================================

# ============================================================
# COMPACT FINAL SHIP OUTPUT (FOR WEBSITE)
# ============================================================

# ============================================================
# SMALL WEBSITE SHIP RECORD
# ============================================================

def make_final_ship_record(candidate):
    """
    Small, frontend-friendly record for one ranked vessel.
    No raw identity object, no hourly match arrays.
    """

    identity = (
        candidate.get("vessel_identity")
        or {}
    )

    spatial = (
        candidate.get("spatial")
        or {}
    )

    temporal = (
        candidate.get("temporal")
        or {}
    )

    trajectory = (
        candidate.get("trajectory")
        or {}
    )

    return {
        "rank": candidate.get(
            "rank"
        ),

        "mmsi": candidate.get(
            "mmsi"
        ),

        "name": get_identity_field(
            identity,
            "shipname",
            "shipName",
            "name",
        ),

        "imo": get_identity_field(
            identity,
            "imo",
            "IMO",
        ),

        "flag": get_identity_field(
            identity,
            "flag",
            "flagCode",
        ),

        "callsign": get_identity_field(
            identity,
            "callsign",
            "callSign",
        ),

        "vessel_type": get_identity_field(
            identity,
            "shiptype",
            "shipType",
            "vesselType",
            "type",
        ),

        "score": candidate.get(
            "score"
        ),

        "score_before_type_prior": candidate.get(
            "score_before_type_prior"
        ),

        "spatial_compatibility": spatial.get(
            "mean_hourly_compatibility"
        ),

        "best_spatial_compatibility": spatial.get(
            "best_hourly_compatibility"
        ),

        "best_distance_km": spatial.get(
            "best_match_distance_km"
        ),

        "best_mean_distance_km": spatial.get(
            "best_match_mean_distance_km"
        ),

        "matched_hours": temporal.get(
            "matched_hours"
        ),

        "modeled_hours": temporal.get(
            "modeled_hours"
        ),

        "coverage_percent": temporal.get(
            "coverage_percent"
        ),

        "longest_consecutive_match_hours": temporal.get(
            "longest_consecutive_match_hours"
        ),

        "trajectory_consistency": trajectory.get(
            "consistency"
        ),

        "mean_speed_knots": trajectory.get(
            "mean_speed_knots"
        ),

        "max_speed_knots": trajectory.get(
            "max_speed_knots"
        ),

        "best_match_time_utc": (
            candidate.get(
                "best_match"
            ) or {}
        ).get(
            "time_utc"
        ),

        "best_match_lat": (
            candidate.get(
                "best_match"
            ) or {}
        ).get(
            "ais_lat"
        ),

        "best_match_lon": (
            candidate.get(
                "best_match"
            ) or {}
        ).get(
            "ais_lon"
        ),
    }
def write_final_ships_json(
    output_dir,
    event_id,
    candidates,
    handoff,
    aoi,
    start_dt,
    end_dt,
    aoi_source,
    time_source,
):
    """
    Writes exactly the top 20 candidates, or fewer if fewer exist.
    Existing raw and full attribution JSON files are untouched.
    """

    selected_candidates = candidates[:20]

    final_ships = [
        make_final_ship_record(
            candidate
        )
        for candidate in selected_candidates
    ]

    final_output = {
        "schema_version": "1.0",
        "output_type": "website_ranked_vessels",
        "event_id": event_id,
        "generated_at_utc": iso_utc(
            utc_now()
        ),

        "description": (
            "Top ranked vessel candidates for "
            "website display. Scores are relative "
            "AIS compatibility rankings, not causal "
            "probabilities."
        ),

        "query": {
            "bbox_wsen": [
                aoi[0],
                aoi[1],
                aoi[2],
                aoi[3],
            ],

            "aoi_source": aoi_source,

            "time_start_utc": iso_utc(
                start_dt
            ),

            "time_end_utc": iso_utc(
                end_dt
            ),

            "time_source": time_source,
        },

        "count": len(
            final_ships
        ),

        "ships": final_ships,
    }

    output_path = (
        Path(output_dir)
        / f"{event_id}_final_ships.json"
    )

    write_json(
        output_path,
        final_output,
    )

    return output_path


def main():

    print("=" * 72)
    print(
        "GFW AIS OIL-SPILL ATTRIBUTION"
    )
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

    # ========================================================
    # STAGE-2
    # ========================================================

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

    # ========================================================
    # AOI
    # ========================================================

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

    # ========================================================
    # TIME
    # ========================================================

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

    # ========================================================
    # GFW REPORT
    # ========================================================

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
        /
        f"{event_id}_gfw_raw.json"
    )

    write_json(
        raw_output_path,
        report_response
    )

    print(
        "[OUTPUT] raw GFW response:",
        raw_output_path
    )

    # ========================================================
    # AIS PARSING
    # ========================================================

    raw_rows = rows_from_gfw(
        report_response
    )

    ais_rows = parse_gfw_rows(
        report_response
    )

    print(
        "[GFW] raw vessel rows:",
        len(raw_rows)
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

    # ========================================================
    # SCORE
    # ========================================================

    print()
    print(
        "[SCORING] scoring MMSIs..."
    )

    candidates = []

    for mmsi, vessel_rows in (
        ais_index.items()
    ):

        result = score_vessel(
            mmsi,
            vessel_rows,
            hypotheses
        )

        if result is not None:
            candidates.append(
                result
            )

    candidates.sort(
        key=lambda x:
            x.get(
                "score",
                0.0
            ),
        reverse=True
    )

    print(
        "[SCORING] candidates:",
        len(candidates)
    )

    # ========================================================
    # IDENTITY
    # ========================================================

    candidates = enrich_candidates(
        candidates
    )

    # ========================================================
    # API-READY SUMMARY
    # ========================================================

    candidate_summaries = [
        make_candidate_summary(
            candidate
        )
        for candidate in candidates
    ]

    # ========================================================
# CLEAN FINAL SHIPS JSON
# ========================================================

    final_ships_path = write_final_ships_json(
        output_dir=output_dir,
        event_id=event_id,
        candidates=candidates[:20],
        handoff=handoff,
        aoi=(
            west,
            south,
            east,
            north,
        ),
        start_dt=start_dt,
        end_dt=end_dt,
        aoi_source=aoi_source,
        time_source=time_source,
    )

    print(
        "[OUTPUT] final ships:",
        final_ships_path
    )

    # ========================================================
    # FINAL OUTPUT
    # ========================================================

    final_output = {

        "schema_version":
            "2.0",

        "event_id":
            event_id,

        "generated_at_utc":
            iso_utc(
                utc_now()
            ),

        # ----------------------------------------------------
        # Pipeline metadata
        # ----------------------------------------------------

        "pipeline": {
            "stage_1":
                "Satellite oil-spill detection",

            "stage_2":
                "OpenDrift/OpenOil deterministic "
                "backward Lagrangian tracking",

            "stage_3":
                "Global Fishing Watch AIS-derived "
                "vessel attribution",
        },

        # ----------------------------------------------------
        # Method
        # ----------------------------------------------------

        "method": {

            "ais_dataset":
                "public-global-presence:latest",

            "vessel_identity_dataset":
                GFW_VESSEL_DATASET,

            "spatial_resolution":
                GFW_SPATIAL_RESOLUTION,

            "temporal_resolution":
                GFW_TEMPORAL_RESOLUTION,

            "group_by":
                GFW_GROUP_BY,

            "match_sigma_km":
                MATCH_SIGMA_KM,

            "speed_soft_limit_knots":
                SPEED_SOFT_LIMIT_KNOTS,

            "scoring": {
                "spatial":
                    "Probability-weighted "
                    "Gaussian distance compatibility",

                "temporal":
                    "Fraction of Stage-2 modeled "
                    "hours with compatible AIS presence",

                "continuity":
                    "Longest consecutive compatible "
                    "hour sequence",

                "trajectory":
                    "Soft penalty for implausible "
                    "AIS-derived vessel speeds",

                "type":
                    "Modest vessel-type prior",

                "final":
                    "Spatial × temporal × continuity "
                    "× trajectory × type factor",
            },

            "score_interpretation":
                "Relative vessel compatibility score; "
                "NOT a causal probability of spill origin.",
        },

        # ----------------------------------------------------
        # Input files
        # ----------------------------------------------------

        "inputs": {

            "stage2_handoff":
                str(
                    handoff_path
                ),

            "observation_summary":
                (
                    str(
                        summary_path
                    )
                    if summary_path.exists()
                    else None
                ),
        },

        # ----------------------------------------------------
        # AIS query
        # ----------------------------------------------------

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

        # ----------------------------------------------------
        # Stage-2 metadata
        # ----------------------------------------------------

        "stage2": {

            "modeled_hours":
                len(hypotheses),

            "backtrack_hours":
                handoff
                .get("backtracking", {})
                .get("backtrack_hours"),

            "initial_seed_particles":
                handoff
                .get("backtracking", {})
                .get(
                    "initial_seed_particles"
                ),

            "current_dataset":
                handoff
                .get("backtracking", {})
                .get(
                    "current_dataset"
                ),

            "wind_dataset":
                handoff
                .get("backtracking", {})
                .get(
                    "wind_dataset"
                ),
        },

        # ----------------------------------------------------
        # Data statistics
        # ----------------------------------------------------

        "data_statistics": {

            "raw_gfw_observations":
                len(raw_rows),

            "normalized_ais_observations":
                len(ais_rows),

            "unique_mmsis":
                len(ais_index),

            "scored_candidates":
                len(candidates),

            "identity_enriched_candidates":
                min(
                    VESSEL_IDENTITY_TOP_N,
                    len(candidates)
                ),
        },

        # ----------------------------------------------------
        # Ranked API-friendly candidates
        # ----------------------------------------------------

        "ranked_candidates":
            candidate_summaries,

        # ----------------------------------------------------
        # Full candidates with every scoring detail
        # ----------------------------------------------------

        "candidates":
            candidates,

        # ----------------------------------------------------
        # Stage-2 probability field
        # ----------------------------------------------------

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
    }

    # ========================================================
    # WRITE
    # ========================================================

    attribution_output_path = (
        output_dir
        /
        f"{event_id}_ais_attribution.json"
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

    # ========================================================
    # CONSOLE
    # ========================================================

    print()
    print("=" * 72)
    print(
        "TOP AIS CANDIDATES"
    )
    print("=" * 72)

    for candidate in candidates[:20]:

        identity = (
            candidate.get(
                "vessel_identity"
            )
            or {}
        )

        name = get_identity_field(
            identity,
            "shipname",
            "shipName",
            "name",
        )

        imo = get_identity_field(
            identity,
            "imo",
            "IMO",
        )

        flag = get_identity_field(
            identity,
            "flag",
            "flagCode",
        )

        shiptype = get_identity_field(
            identity,
            "shiptype",
            "shipType",
            "vesselType",
            "type",
        )

        print(
            f"#{candidate['rank']:2d} "
            f"MMSI={candidate['mmsi']} "
            f"name={name} "
            f"IMO={imo} "
            f"flag={flag} "
            f"type={shiptype} "
            f"score={candidate['score']:.6f} "
            f"spatial={candidate['spatial']['mean_hourly_compatibility']:.4f} "
            f"coverage={candidate['temporal']['coverage_percent']:.1f}% "
            f"continuity={candidate['temporal']['longest_consecutive_match_hours']}h"
        )

    print()
    print(
        "Done."
    )


if __name__ == "__main__":
    main()