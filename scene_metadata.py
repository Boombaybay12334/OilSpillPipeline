"""
scene_metadata.py
===================
Small, standalone brick: extracts and persists scene identity + acquisition
timing. This is the piece a future backtrack-to-origin model needs most --
drift modeling is meaningless without an accurate "T_SAR" (acquisition time)
to backtrack from.

Two time sources, most authoritative first:
    1. The SAFE product's own manifest.safe XML (safe:startTime/stopTime) --
       this is the actual sensor acquisition window, most precise.
    2. The STAC catalog item's `properties.datetime` (from fetch_s1.py's
       search) -- a fallback if the manifest can't be parsed for any
       reason. Less authoritative but always available since it comes from
       the search step itself.

Kept as its own module (not folded into fetch_s1.py or preprocess_and_infer.
py) because BOTH of those scripts need it independently: fetch time happens
right after download, but the manifest itself is only readable once the
.SAFE folder is extracted -- and preprocess_and_infer.py needs to read this
same metadata back later to stamp it onto the final detection report.
"""

import json
import os
import re
from datetime import datetime, timezone


def parse_safe_manifest_times(safe_folder: str):
    """
    Parses <safe_folder>/manifest.safe for safe:startTime / safe:stopTime.
    Returns (start_iso, stop_iso) strings, or (None, None) if not found or
    unparseable -- callers should fall back to catalog datetime in that case.
    """
    manifest_path = os.path.join(safe_folder, "manifest.safe")
    if not os.path.exists(manifest_path):
        print(f"[SceneMetadata] No manifest.safe found at {manifest_path}, "
              f"falling back to catalog datetime.")
        return None, None

    try:
        with open(manifest_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except OSError as e:
        print(f"[SceneMetadata] Could not read manifest.safe: {e}")
        return None, None

    start_match = re.search(r"<safe:startTime[^>]*>(.*?)</safe:startTime>", content)
    stop_match = re.search(r"<safe:stopTime[^>]*>(.*?)</safe:stopTime>", content)

    start_iso = start_match.group(1).strip() if start_match else None
    stop_iso = stop_match.group(1).strip() if stop_match else None

    if not start_iso or not stop_iso:
        print("[SceneMetadata] safe:startTime/stopTime not found in manifest.safe, "
              "falling back to catalog datetime.")

    return start_iso, stop_iso


def build_scene_metadata(catalog_item: dict, safe_folder: str) -> dict:
    """
    Combines catalog search metadata with manifest-derived acquisition
    times into one metadata dict. `catalog_item` is the raw STAC-like item
    dict as returned by fetch_s1.py's catalog search functions.
    """
    props = catalog_item.get("properties", {}) if catalog_item else {}
    catalog_id = catalog_item.get("id") if catalog_item else None
    catalog_datetime = props.get("datetime")

    start_iso, stop_iso = parse_safe_manifest_times(safe_folder)

    metadata = {
        "catalog_id": catalog_id,
        "acquisition_start": start_iso or catalog_datetime,
        "acquisition_stop": stop_iso or catalog_datetime,
        "acquisition_time_source": "manifest.safe" if start_iso else "catalog_datetime_fallback",
        "orbit_state": props.get("sat:orbit_state"),
        "product_type": props.get("sat:product_type"),
        "safe_folder": safe_folder,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
    }
    return metadata


def save_scene_metadata(metadata: dict, output_dir: str) -> str:
    """Writes scene_metadata.json into output_dir, returns its path."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "scene_metadata.json")
    with open(path, "w") as f:
        json.dump(metadata, f, indent=2)
    print(f"[SceneMetadata] Wrote {path}")
    return path


def load_scene_metadata(output_dir: str) -> dict | None:
    """Reads back scene_metadata.json if present, else returns None."""
    path = os.path.join(output_dir, "scene_metadata.json")
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)
