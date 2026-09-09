#!/usr/bin/env python3

import argparse
import json
import math
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv


GFW_REPORT_URL = (
    "https://gateway.api.globalfishingwatch.org/v3/4wings/report"
)

GFW_LAST_REPORT_URL = (
    "https://gateway.api.globalfishingwatch.org/v3/4wings/last-report"
)


# ============================================================
# DATETIME HELPERS
# ============================================================

def utc_now():
    return datetime.now(timezone.utc)


def parse_dt(value):
    if not value:
        return None

    value = str(value).strip()

    # GFW uses values such as:
    # 2018-01-23T04:00:00Z
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"

    dt = datetime.fromisoformat(value)

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    return dt.astimezone(timezone.utc)


def iso_z(dt):
    return (
        dt.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


# ============================================================
# SAFE CONVERSION
# ============================================================

def safe_float(value):
    try:
        if value is None or value == "":
            return None

        return float(value)

    except Exception:
        return None


def safe_int(value):
    try:
        if value is None or value == "":
            return None

        return int(float(value))

    except Exception:
        return None


# ============================================================
# DISTANCE
# ============================================================

def haversine_km(lat1, lon1, lat2, lon2):
    """
    Great-circle distance between two coordinates in km.
    """

    earth_radius_km = 6371.0088

    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)

    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)

    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(lat1_rad)
        * math.cos(lat2_rad)
        * math.sin(dlon / 2.0) ** 2
    )

    return (
        2.0
        * earth_radius_km
        * math.asin(math.sqrt(a))
    )


def gaussian(distance_km, sigma_km):
    """
    Distance compatibility function.

    distance = 0       -> 1
    distance increases -> approaches 0
    """

    if sigma_km <= 0:
        return 1.0 if distance_km == 0 else 0.0

    return math.exp(
        -0.5 * (distance_km / sigma_km) ** 2
    )


# ============================================================
# LOAD STAGE-2 HANDOFF
# ============================================================

def load_handoff(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_observation_summary(path):
    if not path:
        return None

    path = Path(path)

    if not path.exists():
        return None

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# ============================================================
# SOURCE PROBABILITY FIELD
# ============================================================

def get_source_probability_field(handoff):
    """
    Convert Stage-2 origin_hypotheses into:

        {
            UTC hour: [
                {
                    lat,
                    lon,
                    probability
                }
            ]
        }

    The Stage-2 field represents POSSIBLE source locations,
    not a confirmed spill origin.
    """

    result = {}

    hypotheses = handoff.get(
        "origin_hypotheses",
        []
    )

    for hypothesis in hypotheses:

        dt = parse_dt(
            hypothesis.get("time_utc")
        )

        if dt is None:
            continue

        hour = dt.replace(
            minute=0,
            second=0,
            microsecond=0,
        )

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

            if (
                lat is None
                or lon is None
                or probability is None
            ):
                continue

            cells.append(
                {
                    "lat": lat,
                    "lon": lon,
                    "probability": probability,
                    "rank": cell.get("rank"),
                    "particle_count": cell.get(
                        "particle_count"
                    ),
                }
            )

        if cells:
            result[hour] = cells

    return result


# ============================================================
# BBOX
# ============================================================

def bbox_from_handoff(handoff):
    observation = handoff.get(
        "observation",
        {}
    )

    bbox = observation.get(
        "unpadded_bbox_wsen"
    )

    if not bbox or len(bbox) != 4:
        raise ValueError(
            "Could not find "
            "observation.unpadded_bbox_wsen "
            "in Stage-2 handoff."
        )

    west = float(bbox[0])
    south = float(bbox[1])
    east = float(bbox[2])
    north = float(bbox[3])

    return (
        west,
        south,
        east,
        north,
    )


def get_aoi(
    handoff,
    observation_summary,
    spatial_padding_deg,
):

    # Prefer the explicitly prepared padded AOI.
    if observation_summary:

        bbox = observation_summary.get(
            "padded_bbox_wsen"
        )

        if bbox and len(bbox) == 4:

            return (
                tuple(
                    map(float, bbox)
                ),
                "observation_summary.padded_bbox_wsen",
            )

    # Otherwise derive it ourselves.
    west, south, east, north = (
        bbox_from_handoff(handoff)
    )

    return (
        (
            west - spatial_padding_deg,
            south - spatial_padding_deg,
            east + spatial_padding_deg,
            north + spatial_padding_deg,
        ),
        "observation.unpadded_bbox_wsen + "
        "SPATIAL_PADDING_DEG",
    )


def bbox_geojson(
    west,
    south,
    east,
    north,
):
    """
    GFW expects the geojson field to be an actual
    GeoJSON object.

    Do NOT json.dumps() this object.
    """

    return {
        "type": "Polygon",
        "coordinates": [
            [
                [west, south],
                [east, south],
                [east, north],
                [west, north],
                [west, south],
            ]
        ],
    }


# ============================================================
# TIME WINDOW
# ============================================================

def get_time_window(
    handoff,
    observation_summary,
    time_padding_hours,
):

    if observation_summary:

        start = observation_summary.get(
            "search_window_start_utc"
        )

        end = observation_summary.get(
            "search_window_end_utc"
        )

        if start and end:

            return (
                parse_dt(start),
                parse_dt(end),
                "observation_summary.search_window_*",
            )

    backtracking = handoff.get(
        "backtracking",
        {}
    )

    sim_start = backtracking.get(
        "simulation_start_utc"
    )

    sim_end = backtracking.get(
        "simulation_end_utc"
    )

    if not sim_start or not sim_end:
        raise ValueError(
            "Could not determine AIS time window."
        )

    start = (
        parse_dt(sim_start)
        - timedelta(
            hours=time_padding_hours
        )
    )

    end = (
        parse_dt(sim_end)
        + timedelta(
            hours=time_padding_hours
        )
    )

    return (
        start,
        end,
        "backtracking.simulation_* + "
        "TIME_PADDING_HOURS",
    )


# ============================================================
# GFW HEADERS
# ============================================================

def gfw_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


# ============================================================
# GFW ERROR DISPLAY
# ============================================================

def print_gfw_error(response):

    print(
        f"[GFW] HTTP {response.status_code}"
    )

    try:

        error_json = response.json()

        print(
            "[GFW] error response:"
        )

        print(
            json.dumps(
                error_json,
                indent=2,
                ensure_ascii=False,
            )
        )

    except Exception:

        print(
            "[GFW] response body:"
        )

        print(
            response.text[:10000]
        )


# ============================================================
# SUBMIT GFW REPORT
# ============================================================

def submit_gfw_report(
    token,
    polygon,
    start,
    end,
    spatial_resolution,
    temporal_resolution,
    group_by,
    timeout,
):

    params = {
        "spatial-resolution": (
            spatial_resolution
        ),

        "temporal-resolution": (
            temporal_resolution
        ),

        "group-by": group_by,

        "datasets[0]": (
            "public-global-presence:latest"
        ),

        "date-range": (
            f"{iso_z(start)},{iso_z(end)}"
        ),

        "format": "JSON",
    }

    # IMPORTANT:
    #
    # This MUST be a JSON object.
    #
    # WRONG:
    # {"geojson": json.dumps(polygon)}
    #
    # CORRECT:
    # {"geojson": polygon}

    body = {
        "geojson": polygon
    }

    print(
        "[GFW] submitting one report..."
    )

    print(
        f"[GFW] date range: "
        f"{params['date-range']}"
    )

    print(
        f"[GFW] resolution: "
        f"{spatial_resolution} / "
        f"{temporal_resolution}"
    )

    print(
        f"[GFW] group-by: {group_by}"
    )

    response = requests.post(
        GFW_REPORT_URL,
        params=params,
        json=body,
        headers=gfw_headers(token),
        timeout=timeout,
    )

    if not response.ok:

        print_gfw_error(response)

        response.raise_for_status()

    try:
        return response.json()

    except Exception:

        return {
            "raw_response": response.text
        }


# ============================================================
# REPORT ID
# ============================================================

def extract_report_identifier(data):

    if not isinstance(data, dict):
        return None

    for key in (
        "id",
        "reportId",
        "report_id",
        "jobId",
        "job_id",
    ):

        value = data.get(key)

        if value:
            return str(value)

    return None


# ============================================================
# LAST REPORT
# ============================================================

def get_last_report(
    token,
    timeout,
):

    response = requests.get(
        GFW_LAST_REPORT_URL,
        headers=gfw_headers(token),
        timeout=timeout,
    )

    if not response.ok:

        print_gfw_error(response)

        response.raise_for_status()

    return response.json()


# ============================================================
# WAIT FOR GFW REPORT
# ============================================================

def download_report_if_needed(
    token,
    report_response,
    timeout,
    poll_seconds,
    max_wait_minutes,
):

    if not isinstance(
        report_response,
        dict,
    ):
        return report_response

    # If the POST response already contains
    # actual report rows, use it directly.
    if (
        "entries" in report_response
        or "data" in report_response
        or "results" in report_response
        or "rows" in report_response
    ):
        return report_response

    report_id = extract_report_identifier(
        report_response
    )

    if not report_id:
        return report_response

    print(
        f"[GFW] report id: {report_id}"
    )

    print(
        "[GFW] waiting for report..."
    )

    deadline = (
        time.time()
        + max_wait_minutes * 60
    )

    while time.time() < deadline:

        time.sleep(
            poll_seconds
        )

        latest = get_last_report(
            token,
            timeout,
        )

        latest_id = (
            extract_report_identifier(
                latest
            )
        )

        if (
            latest_id
            and latest_id != report_id
        ):
            continue

        status = str(
            latest.get(
                "status",
                ""
            )
        ).lower()

        if status in (
            "running",
            "pending",
            "processing",
        ):

            print(
                f"[GFW] status: {status}"
            )

            continue

        if status in (
            "failed",
            "error",
        ):

            raise RuntimeError(
                "GFW report failed:\n"
                + json.dumps(
                    latest,
                    indent=2,
                )
            )

        if (
            "entries" in latest
            or "data" in latest
            or "results" in latest
            or "rows" in latest
        ):

            print(
                "[GFW] report ready."
            )

            return latest

        if isinstance(
            latest.get("report"),
            dict,
        ):

            report = latest["report"]

            if (
                "entries" in report
                or "data" in report
                or "results" in report
                or "rows" in report
            ):

                print(
                    "[GFW] report ready."
                )

                return report

        print(
            "[GFW] still waiting..."
        )

    raise TimeoutError(
        "GFW report did not finish within "
        f"{max_wait_minutes} minutes."
    )


# ============================================================
# GFW REQUEST WITH RETRIES
# ============================================================

def request_gfw(
    token,
    polygon,
    start,
    end,
    spatial_resolution,
    temporal_resolution,
    group_by,
    timeout,
    retries,
    poll_seconds,
    max_wait_minutes,
):

    last_error = None

    for attempt in range(
        1,
        retries + 1,
    ):

        try:

            report = submit_gfw_report(
                token=token,
                polygon=polygon,
                start=start,
                end=end,
                spatial_resolution=(
                    spatial_resolution
                ),
                temporal_resolution=(
                    temporal_resolution
                ),
                group_by=group_by,
                timeout=timeout,
            )

            return download_report_if_needed(
                token=token,
                report_response=report,
                timeout=timeout,
                poll_seconds=poll_seconds,
                max_wait_minutes=(
                    max_wait_minutes
                ),
            )

        except requests.HTTPError as e:

            last_error = e

            status = (
                e.response.status_code
                if e.response is not None
                else None
            )

            # 422 = malformed/invalid request.
            # Retrying it is pointless.
            if status not in (
                429,
                500,
                502,
                503,
                504,
                524,
            ):

                raise

            if attempt < retries:

                wait = min(
                    10 * attempt,
                    30,
                )

                print(
                    f"[GFW] HTTP {status}; "
                    f"retrying in {wait}s "
                    f"({attempt}/{retries})..."
                )

                time.sleep(wait)

        except (
            requests.RequestException,
            TimeoutError,
        ) as e:

            last_error = e

            if attempt < retries:

                wait = min(
                    10 * attempt,
                    30,
                )

                print(
                    "[GFW] network/timeout error; "
                    f"retrying in {wait}s "
                    f"({attempt}/{retries})..."
                )

                time.sleep(wait)

    raise RuntimeError(
        f"GFW request failed after "
        f"{retries} attempts: {last_error}"
    )


# ============================================================
# GFW RESPONSE PARSER
# ============================================================

def rows_from_gfw(data):
    """
    Parse the ACTUAL GFW 4Wings structure.

    The returned JSON looks like:

    {
        "total": 1,
        "entries": [
            {
                "public-global-presence:v4.0": [
                    {
                        "date": "...",
                        "entryTimestamp": "...",
                        "exitTimestamp": "...",
                        "hours": 1,
                        "lat": 30.25,
                        "lon": 122.17,
                        "mmsi": "412427478"
                    }
                ]
            }
        ]
    }

    Therefore we need:

        entries
          -> dataset key
             -> list of vessel rows
    """

    if not isinstance(
        data,
        dict,
    ):
        return []

    entries = data.get(
        "entries",
        []
    )

    if not isinstance(
        entries,
        list,
    ):
        return []

    rows = []

    for entry in entries:

        if not isinstance(
            entry,
            dict,
        ):
            continue

        # Example key:
        #
        # public-global-presence:v4.0

        for (
            dataset_key,
            dataset_rows,
        ) in entry.items():

            if not isinstance(
                dataset_rows,
                list,
            ):
                continue

            for row in dataset_rows:

                if isinstance(
                    row,
                    dict,
                ):
                    rows.append(row)

    return rows


def normalize_row(row):
    """
    Normalize one GFW public-global-presence row.
    """

    if not isinstance(
        row,
        dict,
    ):
        return None

    # --------------------------------------------------------
    # TIME
    # --------------------------------------------------------

    dt = None

    # GFW report's actual observation timestamp.
    if row.get("date"):

        try:
            dt = parse_dt(
                row["date"]
            )

        except Exception:
            dt = None

    # Fallbacks.
    if dt is None:

        for key in (
            "timestamp",
            "datetime",
            "time",
            "entryTimestamp",
            "entry_timestamp",
        ):

            if not row.get(key):
                continue

            try:

                dt = parse_dt(
                    row[key]
                )

                break

            except Exception:
                pass

    # --------------------------------------------------------
    # POSITION
    # --------------------------------------------------------

    lat = safe_float(
        row.get("lat")
    )

    lon = safe_float(
        row.get("lon")
    )

    # Fallback field names.
    if lat is None:

        lat = safe_float(
            row.get("latitude")
        )

    if lon is None:

        lon = safe_float(
            row.get("longitude")
        )

    if (
        lat is None
        or lon is None
    ):
        return None

    # --------------------------------------------------------
    # IDENTITY
    # --------------------------------------------------------

    mmsi = row.get(
        "mmsi"
    )

    vessel_id = (
        row.get("vessel_id")
        or row.get("vesselId")
        or row.get("vesselID")
    )

    if (
        not mmsi
        and not vessel_id
    ):
        return None

    # --------------------------------------------------------
    # NORMALIZED OBJECT
    # --------------------------------------------------------

    return {
        "datetime": dt,

        "lat": lat,
        "lon": lon,

        "mmsi": (
            str(mmsi)
            if mmsi
            else None
        ),

        "vessel_id": (
            str(vessel_id)
            if vessel_id
            else None
        ),

        "vessel_name": (
            row.get("shipName")
            or row.get("vesselName")
            or row.get("ship_name")
            or row.get("vessel_name")
        ),

        "imo": (
            row.get("imo")
            or row.get("IMO")
        ),

        "callsign": (
            row.get("callsign")
            or row.get("callSign")
        ),

        "flag": (
            row.get("flag")
            or row.get("flag_code")
        ),

        "vessel_type": (
            row.get("vesselType")
            or row.get("vessel_type")
        ),

        "geartype": (
            row.get("geartype")
            or row.get("gearType")
            or row.get("gear_type")
        ),

        "hours": safe_float(
            row.get("hours")
        ),

        "entry_timestamp": (
            row.get("entryTimestamp")
        ),

        "exit_timestamp": (
            row.get("exitTimestamp")
        ),

        "raw": row,
    }


def parse_gfw_rows(data):

    rows = rows_from_gfw(
        data
    )

    print(
        f"[GFW] raw vessel rows: "
        f"{len(rows)}"
    )

    normalized = []

    for row in rows:

        item = normalize_row(
            row
        )

        if item is not None:
            normalized.append(item)

    print(
        f"[GFW] normalized AIS rows: "
        f"{len(normalized)}"
    )

    return normalized


# ============================================================
# VESSEL TYPE PRIOR
# ============================================================

TYPE_PRIOR = {
    "tanker": 1.00,
    "cargo": 0.80,
    "carrier": 0.75,
    "support": 0.65,
    "bunker": 0.75,
    "tug": 0.55,
    "fishing": 0.45,
    "passenger": 0.20,
    "unknown": 0.30,
    "other": 0.30,
}


def vessel_type_prior(vessel_type):

    if not vessel_type:
        return TYPE_PRIOR[
            "unknown"
        ]

    text = str(
        vessel_type
    ).lower()

    for key, value in TYPE_PRIOR.items():

        if key in text:
            return value

    return TYPE_PRIOR[
        "other"
    ]


# ============================================================
# SCORE VESSELS
# ============================================================

def score_vessels(
    ais_rows,
    source_probability,
    sigma_km,
):
    """
    Match AIS vessel positions against the Stage-2
    possible-source probability field.

    For every AIS observation:

        1. Find the corresponding UTC hour.
        2. Find Stage-2 possible source cells for that hour.
        3. Calculate distance to every possible source cell.
        4. Calculate Gaussian spatial compatibility.
        5. Multiply by source probability.
        6. Keep the strongest match for that AIS observation.

    Vessel score:

        compatibility_sum
        *
        temporal_coverage_factor
        *
        vessel_type_factor

    IMPORTANT:
    This is a compatibility ranking.
    It is NOT a probability that the vessel caused the spill.
    """

    by_vessel = defaultdict(list)

    # --------------------------------------------------------
    # Group AIS observations by vessel.
    # --------------------------------------------------------

    for row in ais_rows:

        dt = row.get(
            "datetime"
        )

        if dt is None:
            continue

        if (
            row.get("lat") is None
            or row.get("lon") is None
        ):
            continue

        key = (
            row.get("mmsi")
            or row.get("vessel_id")
        )

        if not key:
            continue

        by_vessel[
            str(key)
        ].append(row)

    modeled_hours = len(
        source_probability
    )

    candidates = []

    # --------------------------------------------------------
    # Score each vessel.
    # --------------------------------------------------------

    for (
        vessel_key,
        rows,
    ) in by_vessel.items():

        compatibility_sum = 0.0

        matches = []

        strongest = None

        matched_hour_keys = set()

        # ----------------------------------------------------
        # Every AIS position.
        # ----------------------------------------------------

        for row in rows:

            hour = row[
                "datetime"
            ].replace(
                minute=0,
                second=0,
                microsecond=0,
            )

            source_cells = (
                source_probability.get(
                    hour
                )
            )

            if not source_cells:
                continue

            best_match = None

            # ------------------------------------------------
            # Compare against Stage-2 source cells.
            # ------------------------------------------------

            for cell in source_cells:

                distance_km = (
                    haversine_km(
                        row["lat"],
                        row["lon"],
                        cell["lat"],
                        cell["lon"],
                    )
                )

                distance_weight = (
                    gaussian(
                        distance_km,
                        sigma_km,
                    )
                )

                match_score = (
                    cell["probability"]
                    * distance_weight
                )

                match = {
                    "ais_time_utc": iso_z(
                        row["datetime"]
                    ),

                    "ais_lat": row["lat"],
                    "ais_lon": row["lon"],

                    "source_lat": cell["lat"],
                    "source_lon": cell["lon"],

                    "distance_km": (
                        distance_km
                    ),

                    "source_probability": (
                        cell["probability"]
                    ),

                    "match_score": (
                        match_score
                    ),
                }

                if (
                    best_match is None
                    or match_score
                    > best_match[
                        "match_score"
                    ]
                ):

                    best_match = match

            # ------------------------------------------------
            # Keep strongest source-cell match.
            # ------------------------------------------------

            if best_match:

                compatibility_sum += (
                    best_match[
                        "match_score"
                    ]
                )

                matches.append(
                    best_match
                )

                matched_hour_keys.add(
                    hour
                )

                if (
                    strongest is None
                    or best_match[
                        "match_score"
                    ]
                    > strongest[
                        "match_score"
                    ]
                ):

                    strongest = (
                        best_match
                    )

        # ----------------------------------------------------
        # Temporal coverage.
        # ----------------------------------------------------

        matched_hours = len(
            matched_hour_keys
        )

        temporal_coverage = (
            matched_hours
            / modeled_hours
            if modeled_hours
            else 0.0
        )

        # ----------------------------------------------------
        # Vessel metadata.
        # ----------------------------------------------------

        first_row = rows[0]

        type_prior = (
            vessel_type_prior(
                first_row.get(
                    "vessel_type"
                )
            )
        )

        # ----------------------------------------------------
        # Final ranking score.
        # ----------------------------------------------------

        final_score = (
            compatibility_sum
            * (
                0.5
                + 0.5
                * temporal_coverage
            )
            * (
                0.5
                + 0.5
                * type_prior
            )
        )

        # ----------------------------------------------------
        # Strongest matches first.
        # ----------------------------------------------------

        matches.sort(
            key=lambda x: x[
                "match_score"
            ],
            reverse=True,
        )

        candidates.append(
            {
                "mmsi": first_row.get(
                    "mmsi"
                ),

                "vessel_id": first_row.get(
                    "vessel_id"
                ),

                "vessel_name": first_row.get(
                    "vessel_name"
                ),

                "imo": first_row.get(
                    "imo"
                ),

                "callsign": first_row.get(
                    "callsign"
                ),

                "flag": first_row.get(
                    "flag"
                ),

                "vessel_type": first_row.get(
                    "vessel_type"
                ),

                "geartype": first_row.get(
                    "geartype"
                ),

                "matched_hours": (
                    matched_hours
                ),

                "modeled_hours": (
                    modeled_hours
                ),

                "temporal_coverage_fraction": (
                    temporal_coverage
                ),

                "type_prior": (
                    type_prior
                ),

                "source_compatibility_score": (
                    compatibility_sum
                ),

                "final_score": (
                    final_score
                ),

                "strongest_match": (
                    strongest
                ),

                "top_matches": (
                    matches
                ),
            }
        )

    # --------------------------------------------------------
    # Highest score first.
    # --------------------------------------------------------

    candidates.sort(
        key=lambda x: x[
            "final_score"
        ],
        reverse=True,
    )

    for rank, candidate in enumerate(
        candidates,
        start=1,
    ):

        candidate[
            "rank"
        ] = rank

    return candidates


# ============================================================
# JSON OUTPUT
# ============================================================

def write_json(
    path,
    data,
):

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with open(
        path,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            data,
            f,
            indent=2,
            ensure_ascii=False,
        )


# ============================================================
# BUILD FINAL OUTPUT
# ============================================================

def build_output(
    handoff,
    source_probability,
    ais_rows,
    candidates,
    aoi,
    aoi_source,
    ais_start,
    ais_end,
    time_source,
    config,
):

    observation = handoff.get(
        "observation",
        {}
    )

    backtracking = handoff.get(
        "backtracking",
        {}
    )

    return {

        "schema_version": "1.0",

        "event_id": handoff.get(
            "event_id"
        ),

        "generated_at_utc": (
            iso_z(utc_now())
        ),

        # ----------------------------------------------------
        # Observation
        # ----------------------------------------------------

        "observation": observation,

        # ----------------------------------------------------
        # Backtracking
        # ----------------------------------------------------

        "backtracking": {

            "method": backtracking.get(
                "method"
            ),

            "simulation_start_utc": (
                backtracking.get(
                    "simulation_start_utc"
                )
            ),

            "simulation_end_utc": (
                backtracking.get(
                    "simulation_end_utc"
                )
            ),

            "backtrack_hours": (
                backtracking.get(
                    "backtrack_hours"
                )
            ),

            "initial_seed_particles": (
                backtracking.get(
                    "initial_seed_particles"
                )
            ),

            "currents": (
                backtracking.get(
                    "currents"
                )
            ),

            "winds": (
                backtracking.get(
                    "winds"
                )
            ),

            "oil_type": (
                backtracking.get(
                    "oil_type"
                )
            ),
        },

        # ----------------------------------------------------
        # AIS
        # ----------------------------------------------------

        "ais": {

            "provider": (
                "Global Fishing Watch"
            ),

            "dataset": (
                "public-global-presence:latest"
            ),

            "aoi_wsen": {

                "west": aoi[0],
                "south": aoi[1],
                "east": aoi[2],
                "north": aoi[3],
            },

            "aoi_source": (
                aoi_source
            ),

            "time_start_utc": (
                iso_z(ais_start)
            ),

            "time_end_utc": (
                iso_z(ais_end)
            ),

            "time_source": (
                time_source
            ),

            "spatial_resolution": (
                config[
                    "GFW_SPATIAL_RESOLUTION"
                ]
            ),

            "temporal_resolution": (
                config[
                    "GFW_TEMPORAL_RESOLUTION"
                ]
            ),

            "group_by": (
                config[
                    "GFW_GROUP_BY"
                ]
            ),

            "ais_rows": (
                len(ais_rows)
            ),
        },

        # ----------------------------------------------------
        # Stage-2 source field
        # ----------------------------------------------------

        "source_probability_field": {

            "hours": (
                len(source_probability)
            ),

            "description": (
                "Possible oil-source "
                "locations produced by "
                "Stage-2 backward "
                "transport. These are "
                "hypotheses, not confirmed "
                "spill origins."
            ),
        },

        # ----------------------------------------------------
        # Summary
        # ----------------------------------------------------

        "summary": {

            "ais_rows_used": (
                len(ais_rows)
            ),

            "unique_vessels": (
                len(candidates)
            ),

            "top_candidate": (
                candidates[0]["mmsi"]
                if candidates
                else None
            ),
        },

        # ----------------------------------------------------
        # Candidates
        # ----------------------------------------------------

        "candidates": candidates,

        # ----------------------------------------------------
        # Limitations
        # ----------------------------------------------------

        "limitations": [

            (
                "AIS compatibility does not prove "
                "a vessel caused the spill."
            ),

            (
                "Stage-2 backtracking provides "
                "possible source locations, not "
                "a confirmed origin."
            ),

            (
                "GFW public-global-presence "
                "represents hourly vessel "
                "presence and is not a continuous "
                "raw AIS trajectory."
            ),

            (
                "AIS gaps, transmission behavior, "
                "vessel identity uncertainty, "
                "and model uncertainty can affect "
                "rankings."
            ),

            (
                "The vessel-type prior is only "
                "a weak ranking factor."
            ),

            (
                "Scores are compatibility "
                "rankings, not probabilities "
                "of responsibility."
            ),
        ],
    }


# ============================================================
# MAIN
# ============================================================

def main():

    load_dotenv()

    parser = argparse.ArgumentParser(
        description=(
            "AIS attribution using "
            "Stage-2 oil-spill "
            "backtracking hypotheses."
        )
    )

    parser.add_argument(
        "--input",
        default=os.getenv(
            "INPUT_HANDOFF_PATH",
            "./sanchi_2018_stage2_handoff.json",
        ),
        help=(
            "Stage-2 handoff JSON path."
        ),
    )

    parser.add_argument(
        "--observation-summary",
        default=os.getenv(
            "INPUT_OBSERVATION_SUMMARY_PATH",
            "./sanchi_2018_observation_summary.json",
        ),
        help=(
            "Optional observation summary."
        ),
    )

    parser.add_argument(
        "--output-dir",
        default=os.getenv(
            "OUTPUT_DIR",
            "./ais_attribution_output",
        ),
        help=(
            "Output directory."
        ),
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Calculate AOI/time window "
            "without contacting GFW."
        ),
    )

    args = parser.parse_args()

    input_path = Path(
        args.input
    )

    observation_summary_path = Path(
        args.observation_summary
    )

    output_dir = Path(
        args.output_dir
    )

    # --------------------------------------------------------
    # Validate input.
    # --------------------------------------------------------

    if not input_path.exists():

        raise FileNotFoundError(
            f"Input handoff not found: "
            f"{input_path}"
        )

    # --------------------------------------------------------
    # Load Stage-2.
    # --------------------------------------------------------

    handoff = load_handoff(
        input_path
    )

    event_id = handoff.get(
        "event_id",
        input_path.stem,
    )

    # --------------------------------------------------------
    # Source probability.
    # --------------------------------------------------------

    source_probability = (
        get_source_probability_field(
            handoff
        )
    )

    if not source_probability:

        raise ValueError(
            "No origin_hypotheses/top_cells "
            "found in Stage-2 handoff."
        )

    # --------------------------------------------------------
    # Optional observation summary.
    # --------------------------------------------------------

    observation_summary = (
        load_observation_summary(
            observation_summary_path
        )
    )

    # --------------------------------------------------------
    # Configuration.
    # --------------------------------------------------------

    spatial_padding_deg = float(
        os.getenv(
            "SPATIAL_PADDING_DEG",
            "2.0",
        )
    )

    time_padding_hours = float(
        os.getenv(
            "TIME_PADDING_HOURS",
            "12",
        )
    )

    # --------------------------------------------------------
    # AOI.
    # --------------------------------------------------------

    aoi, aoi_source = get_aoi(
        handoff,
        observation_summary,
        spatial_padding_deg,
    )

    # --------------------------------------------------------
    # AIS time window.
    # --------------------------------------------------------

    (
        ais_start,
        ais_end,
        time_source,
    ) = get_time_window(
        handoff,
        observation_summary,
        time_padding_hours,
    )

    # --------------------------------------------------------
    # Console summary.
    # --------------------------------------------------------

    print()

    print(
        "=" * 72
    )

    print(
        f"Event: {event_id}"
    )

    print(
        f"Input: {input_path}"
    )

    print(
        "=" * 72
    )

    print(
        "Source-probability hours: "
        f"{len(source_probability)}"
    )

    print(
        "AIS AOI: "
        f"W={aoi[0]:.6f}, "
        f"S={aoi[1]:.6f}, "
        f"E={aoi[2]:.6f}, "
        f"N={aoi[3]:.6f}"
    )

    print(
        "AIS time: "
        f"{iso_z(ais_start)} "
        f"-> "
        f"{iso_z(ais_end)}"
    )

    print(
        f"AOI source: {aoi_source}"
    )

    print(
        f"Time source: {time_source}"
    )

    # --------------------------------------------------------
    # Dry run.
    # --------------------------------------------------------

    if args.dry_run:

        print(
            "DRY RUN: no GFW request made."
        )

        return

    # --------------------------------------------------------
    # GFW token.
    # --------------------------------------------------------

    token = os.getenv(
        "GFW_API_TOKEN"
    )

    if not token:

        raise RuntimeError(
            "GFW_API_TOKEN is missing. "
            "Put it in .env."
        )

    # --------------------------------------------------------
    # GFW configuration.
    # --------------------------------------------------------

    config = {

        "GFW_SPATIAL_RESOLUTION": (
            os.getenv(
                "GFW_SPATIAL_RESOLUTION",
                "HIGH",
            )
        ),

        "GFW_TEMPORAL_RESOLUTION": (
            os.getenv(
                "GFW_TEMPORAL_RESOLUTION",
                "HOURLY",
            )
        ),

        "GFW_GROUP_BY": (
            os.getenv(
                "GFW_GROUP_BY",
                "MMSI",
            )
        ),
    }

    timeout = int(
        os.getenv(
            "HTTP_TIMEOUT_SECONDS",
            "120",
        )
    )

    retries = int(
        os.getenv(
            "HTTP_RETRIES",
            "3",
        )
    )

    poll_seconds = int(
        os.getenv(
            "REPORT_POLL_SECONDS",
            "10",
        )
    )

    max_wait_minutes = int(
        os.getenv(
            "REPORT_MAX_WAIT_MINUTES",
            "15",
        )
    )

    sigma_km = float(
        os.getenv(
            "MATCH_SIGMA_KM",
            "15",
        )
    )

    min_match_score = float(
        os.getenv(
            "MIN_MATCH_SCORE",
            "0.0",
        )
    )

    top_matches_per_vessel = int(
        os.getenv(
            "TOP_MATCHES_PER_VESSEL",
            "10",
        )
    )

    # --------------------------------------------------------
    # GeoJSON.
    # --------------------------------------------------------

    polygon = bbox_geojson(
        aoi[0],
        aoi[1],
        aoi[2],
        aoi[3],
    )

    # --------------------------------------------------------
    # GFW query.
    # --------------------------------------------------------

    raw_report = request_gfw(
        token=token,
        polygon=polygon,
        start=ais_start,
        end=ais_end,
        spatial_resolution=(
            config[
                "GFW_SPATIAL_RESOLUTION"
            ]
        ),
        temporal_resolution=(
            config[
                "GFW_TEMPORAL_RESOLUTION"
            ]
        ),
        group_by=(
            config[
                "GFW_GROUP_BY"
            ]
        ),
        timeout=timeout,
        retries=retries,
        poll_seconds=poll_seconds,
        max_wait_minutes=(
            max_wait_minutes
        ),
    )

    # --------------------------------------------------------
    # Output directory.
    # --------------------------------------------------------

    output_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    # --------------------------------------------------------
    # Save raw GFW response.
    # --------------------------------------------------------

    raw_path = (
        output_dir
        / f"{event_id}_gfw_raw.json"
    )

    write_json(
        raw_path,
        raw_report,
    )

    print(
        f"[OUTPUT] raw GFW response: "
        f"{raw_path}"
    )

    # --------------------------------------------------------
    # Parse AIS.
    # --------------------------------------------------------

    ais_rows = parse_gfw_rows(
        raw_report
    )

    # --------------------------------------------------------
    # Score.
    # --------------------------------------------------------

    candidates = score_vessels(
        ais_rows=ais_rows,
        source_probability=(
            source_probability
        ),
        sigma_km=sigma_km,
    )

    # --------------------------------------------------------
    # Minimum score filtering.
    # --------------------------------------------------------

    candidates = [
        candidate
        for candidate in candidates
        if candidate[
            "final_score"
        ] >= min_match_score
    ]

    # --------------------------------------------------------
    # Limit top matches stored per vessel.
    # --------------------------------------------------------

    for candidate in candidates:

        candidate[
            "top_matches"
        ] = candidate[
            "top_matches"
        ][:top_matches_per_vessel]

    # Re-rank after filtering.
    for rank, candidate in enumerate(
        candidates,
        start=1,
    ):

        candidate[
            "rank"
        ] = rank

    # --------------------------------------------------------
    # Build final output.
    # --------------------------------------------------------

    result = build_output(
        handoff=handoff,
        source_probability=(
            source_probability
        ),
        ais_rows=ais_rows,
        candidates=candidates,
        aoi=aoi,
        aoi_source=aoi_source,
        ais_start=ais_start,
        ais_end=ais_end,
        time_source=time_source,
        config=config,
    )

    # --------------------------------------------------------
    # Save attribution.
    # --------------------------------------------------------

    result_path = (
        output_dir
        / f"{event_id}_ais_attribution.json"
    )

    write_json(
        result_path,
        result,
    )

    print(
        f"[OUTPUT] attribution: "
        f"{result_path}"
    )

    # --------------------------------------------------------
    # Console ranking.
    # --------------------------------------------------------

    print()

    print(
        "=" * 72
    )

    print(
        "TOP AIS CANDIDATES"
    )

    print(
        "=" * 72
    )

    if not candidates:

        print(
            "No matching vessels found."
        )

        return

    for candidate in candidates[:20]:

        print(
            f"#{candidate['rank']:>2} "
            f"MMSI={candidate.get('mmsi')} "
            f"name={candidate.get('vessel_name')} "
            f"type={candidate.get('vessel_type')} "
            f"score="
            f"{candidate['final_score']:.6f} "
            f"coverage="
            f"{candidate['temporal_coverage_fraction']:.1%}"
        )


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    try:

        main()

    except KeyboardInterrupt:

        print(
            "\nInterrupted."
        )

        sys.exit(130)

    except Exception as e:

        print(
            f"\nERROR: {e}"
        )

        sys.exit(1)