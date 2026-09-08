"""
fetch_s1.py
===========
Search + download a Sentinel-1 GRD product from the Copernicus Data Space
Ecosystem (CDSE) and return the path to the extracted `.SAFE` folder,
ready to feed straight into `preprocess_and_infer.py`.

WHY THIS VERSION IS DIFFERENT FROM THE ORIGINAL fetch_s1_grd_test.py:
----------------------------------------------------------------------
1. Credentials come from environment variables, not hardcoded strings.
   Set these before running (once per shell session), e.g. on Linux/Mac:

       export CDSE_USERNAME="you@example.com"
       export CDSE_PASSWORD="your-password"

   On Windows PowerShell:

       $env:CDSE_USERNAME = "you@example.com"
       $env:CDSE_PASSWORD = "your-password"

   (Your previous script had a real password committed in plaintext --
   please rotate that password on dataspace.copernicus.eu.)

2. THE ACTUAL BUG FIX: the OData `$value` endpoint always returns a
   *zip archive* of the SAFE product, no matter what you name the output
   file. The old script saved those zip bytes as `s1_grd_sample.safe`,
   which is not a real SAFE product and is not something SNAP's `gpt`
   can reliably auto-detect. This version:
       - downloads to a `.zip` file (correct extension),
       - extracts it,
       - locates the inner `<name>.SAFE` directory,
       - returns that folder's path.
   That folder is what you pass to SNAP / the preprocessing graph.

3. The OData "Name" lookup is made more robust. The Catalog API's item
   `id` doesn't always exactly match the OData `Name` field (it may be
   missing the `.SAFE` suffix). This version tries an exact match first,
   then falls back to appending `.SAFE`, then falls back to a `contains`
   filter.
"""

import os
import zipfile
import requests

from scene_metadata import build_scene_metadata, save_scene_metadata

try:
    from dotenv import load_dotenv
    load_dotenv()  # picks up a `.env` file in the current directory, if present
except ImportError:
    pass  # fine -- env vars can still be set manually / via shell export

# =========================
#  CONFIG
# =========================

CDSE_USERNAME = os.environ.get("CDSE_USERNAME")
CDSE_PASSWORD = os.environ.get("CDSE_PASSWORD")
CDSE_TOTP = os.environ.get("CDSE_TOTP")  # optional, only if you have 2FA enabled

BBOX = [11.0, 55.0, 13.0, 56.0]  # [west, south, east, north] in EPSG:4326
DATETIME = "2018-01-10T00:00:00Z/2018-01-10T23:59:59Z"

# =========================
#  KNOWN REAL OIL SPILL EVENTS (for testing against a known-positive scene)
# =========================
# bbox is deliberately kept mostly open-water to sidestep the land-mask
# issue for now. datetime windows are chosen from independently reported
# spill timelines (news, coast guard, NOAA/CEDRE incident reports), not
# guessed -- but Sentinel-1 revisit is ~6-12 days, so a given window may
# still return 0-3 actual passes. Use --list to see what's really there
# before picking one.
KNOWN_OIL_SPILL_EVENTS = {
    "sanchi_2018": {
        "description": (
            "MT Sanchi tanker collision (6 Jan 2018) and sinking (14 Jan 2018), "
            "East China Sea. Confirmed oil/condensate slicks reported by China's "
            "State Oceanic Administration and tracked via VIIRS/Sentinel-2 through "
            "mid-to-late January 2018, centered near 28.37N 125.92E."
        ),
        "bbox": [124.5, 27.5, 127.0, 29.0],
        "datetime": "2018-01-14T00:00:00Z/2018-01-25T23:59:59Z",
    },
}

# =========================
#  CONTROL SCENES (for isolating pipeline bugs from real geography)
# =========================
# NOT known oil spills -- deliberately open ocean, far from any coastline or
# island, chosen to test whether a detection artifact is caused by our own
# code (valid_mask/CFAR/region logic) versus by coastal/strait geometry
# (wind-shadowed calm water near land is a real, documented "lookalike"
# cause -- see the elongation-artifact investigation this scene was added
# to resolve). Kept in a SEPARATE registry from KNOWN_OIL_SPILL_EVENTS on
# purpose so a control scene can never be mistaken for a real spill target.
CONTROL_TEST_LOCATIONS = {
    "bay_of_biscay_control": {
        "description": (
            "Open-water control scene, central Bay of Biscay -- roughly "
            "150-250km offshore from both the French and Spanish coasts, "
            "no islands in the bbox. NOT a known spill location; this is a "
            "clean baseline to check whether elongated false-positive "
            "regions still occur far from any coastline. Chosen in this "
            "region specifically because it's heavily monitored by "
            "Sentinel-1 (same area as the 2002 Prestige spill), so real "
            "archived passes are reliably available."
        ),
        "bbox": [-6.0, 44.5, -4.0, 46.0],
        "datetime": "2018-01-01T00:00:00Z/2018-01-31T23:59:59Z",
    },
}


def _resolve_scene_config(key: str):
    """Looks up `key` in either registry, spill events first."""
    if key in KNOWN_OIL_SPILL_EVENTS:
        return KNOWN_OIL_SPILL_EVENTS[key]
    if key in CONTROL_TEST_LOCATIONS:
        return CONTROL_TEST_LOCATIONS[key]
    all_keys = list(KNOWN_OIL_SPILL_EVENTS.keys()) + list(CONTROL_TEST_LOCATIONS.keys())
    raise KeyError(f"Unknown event/control key '{key}'. Known keys: {all_keys}")

TOKEN_URL = (
    "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/"
    "protocol/openid-connect/token"
)
CATALOG_SEARCH_URL = "https://sh.dataspace.copernicus.eu/catalog/v1/search"
CATALOG_PRODUCTS_URL = "https://catalogue.dataspace.copernicus.eu/odata/v1/Products"
DOWNLOAD_BASE_URL = "https://download.dataspace.copernicus.eu/odata/v1/Products"


# =========================
#  BRICK 1: ACCESS TOKEN
# =========================

def get_cdse_access_token(username: str, password: str, totp: str | None = None) -> str:
    if not username or not password:
        raise RuntimeError(
            "CDSE_USERNAME / CDSE_PASSWORD are not set. Export them as "
            "environment variables before running this script."
        )

    data = {
        "username": username,
        "password": password,
        "grant_type": "password",
        "client_id": "cdse-public",
    }
    if totp:
        data["totp"] = totp

    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    resp = requests.post(TOKEN_URL, headers=headers, data=data)
    try:
        resp.raise_for_status()
    except requests.HTTPError:
        print("Token request failed:", resp.status_code, resp.text)
        raise

    return resp.json()["access_token"]


# =========================
#  BRICK 2: CATALOG SEARCH
# =========================

def search_scenes_list(access_token: str, bbox, datetime_range, limit: int = 10):
    """
    Like catalog_search_s1_grd, but returns ALL matching items (up to
    `limit`) instead of just the first, and prints each one's date/id so
    you can pick which actual pass to download. Used for browsing a known
    event's time window, where several Sentinel-1 passes may exist.
    """
    payload = {
        "bbox": bbox,
        "datetime": datetime_range,
        "collections": ["sentinel-1-grd"],
        "limit": limit,
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    resp = requests.post(CATALOG_SEARCH_URL, headers=headers, json=payload)
    resp.raise_for_status()
    result = resp.json()

    items = result.get("features", []) or result.get("items", [])
    print(f"Found {len(items)} Sentinel-1 GRD passes in this window\n")
    for i, item in enumerate(items):
        props = item.get("properties", {})
        print(f"  [{i}] {item.get('id')}")
        print(f"       datetime={props.get('datetime')}  "
              f"orbit={props.get('sat:orbit_state')}")

    if not items:
        print("No passes found -- try widening the bbox or date range.")

    return items


def catalog_search_s1_grd(access_token: str, bbox=None, datetime_range=None):
    payload = {
        "bbox": bbox or BBOX,
        "datetime": datetime_range or DATETIME,
        "collections": ["sentinel-1-grd"],
        "limit": 5,
    }
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    resp = requests.post(CATALOG_SEARCH_URL, headers=headers, json=payload)
    resp.raise_for_status()
    result = resp.json()

    items = result.get("features", []) or result.get("items", [])
    print(f"Found {len(items)} items")
    if not items:
        print("No Sentinel-1 GRD items found. Adjust BBOX/DATETIME.")
        return None

    item = items[0]
    props = item.get("properties", {})
    print("\n=== First item metadata (Catalog) ===")
    print("ID:", item.get("id"))
    print("Datetime:", props.get("datetime"))
    print("Product type:", props.get("sat:product_type"))
    print("Orbit state:", props.get("sat:orbit_state"))

    return item


# =========================
#  BRICK 3: OData LOOKUP (robust name matching)
# =========================

def _odata_query(access_token: str, filter_str: str):
    headers = {"Authorization": f"Bearer {access_token}"}
    resp = requests.get(
        CATALOG_PRODUCTS_URL, headers=headers, params={"$filter": filter_str}
    )
    resp.raise_for_status()
    return resp.json().get("value", [])


def odata_lookup_product_by_name(access_token: str, product_name: str):
    """
    Tries, in order:
      1. exact match on product_name
      2. exact match on product_name + '.SAFE'
      3. 'contains' match on product_name
    Returns (product_id, name, s3_path) or (None, None, None).
    """
    candidates = [
        f"Name eq '{product_name}'",
        f"Name eq '{product_name}.SAFE'",
        f"contains(Name,'{product_name}')",
    ]

    for filt in candidates:
        values = _odata_query(access_token, filt)
        if values:
            p = values[0]
            print(f"\n=== OData product metadata (matched via: {filt}) ===")
            print("Id:", p.get("Id"))
            print("Name:", p.get("Name"))
            return p.get("Id"), p.get("Name"), p.get("S3Path")

    print(f"No OData product found for Name ~ '{product_name}' (tried exact, +.SAFE, contains).")
    return None, None, None


# =========================
#  BRICK 4: DOWNLOAD + EXTRACT (the actual fix)
# =========================

def download_product_zip(access_token: str, product_id: str, out_zip_path: str):
    """
    Downloads the product via OData $value. This endpoint returns a ZIP
    archive containing the SAFE product -- always save it with a .zip
    extension, never as .safe directly.
    """
    download_url = f"{DOWNLOAD_BASE_URL}({product_id})/$value"
    headers = {"Authorization": f"Bearer {access_token}"}

    print(f"\nDownloading product {product_id} -> {out_zip_path} ...")
    with requests.get(download_url, headers=headers, stream=True) as r:
        r.raise_for_status()
        with open(out_zip_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

    size_mb = os.path.getsize(out_zip_path) / 1024 / 1024
    print(f"Download complete: {size_mb:.2f} MB")


def extract_safe_folder(zip_path: str, extract_dir: str) -> str:
    """
    Extracts the downloaded zip and returns the path to the inner
    `<product>.SAFE` directory (what SNAP's gpt expects as -Pinput).

    IMPORTANT: `extract_dir` must be a directory DEDICATED to this one
    product (see fetch_scene_by_catalog_id, which creates a per-product
    subfolder before calling this). Do NOT pass a shared work_dir that
    might contain leftover .SAFE folders from a previous run's different
    scene -- this function picks the first .SAFE folder it finds, and a
    shared directory with multiple .SAFE folders will silently pick the
    wrong one with no error. This exact bug happened once already: running
    the pipeline twice into the same --output_dir caused a stale Baltic
    Sea test scene's leftover .SAFE folder to be silently reused instead
    of a freshly-downloaded Sanchi event scene.
    """
    os.makedirs(extract_dir, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(extract_dir)

    safe_dirs = [
        os.path.join(extract_dir, name)
        for name in os.listdir(extract_dir)
        if name.upper().endswith(".SAFE") and os.path.isdir(os.path.join(extract_dir, name))
    ]
    if not safe_dirs:
        raise RuntimeError(
            f"No .SAFE folder found after extracting {zip_path}. "
            f"Contents were: {os.listdir(extract_dir)}"
        )
    if len(safe_dirs) > 1:
        raise RuntimeError(
            f"Found {len(safe_dirs)} .SAFE folders in {extract_dir}, expected exactly 1: "
            f"{safe_dirs}. This should be impossible if extract_dir is a dedicated "
            f"per-product folder (see fetch_scene_by_catalog_id) -- refusing to guess "
            f"which one is correct rather than silently picking the wrong scene."
        )

    safe_path = safe_dirs[0]
    print(f"Extracted SAFE product -> {safe_path}")
    return safe_path


# =========================
#  PUBLIC ENTRY POINT
# =========================

def fetch_scene_by_catalog_id(access_token: str, catalog_id: str, work_dir: str) -> str:
    """
    Given a specific Sentinel Hub catalog item id (e.g. one printed by
    search_scenes_list), resolves it via OData, downloads, and extracts.
    Returns the path to the extracted .SAFE folder. This is the shared
    core used by both fetch_s1_scene() (auto-pick first result) and
    fetch_known_event() (pick a specific listed pass).

    Extraction happens into `work_dir/<product_name>/`, a subfolder
    dedicated to THIS product -- never directly into the shared `work_dir`,
    which may contain leftover .SAFE folders from a previous run's
    different scene. This is what actually prevents the stale-scene
    collision bug (see extract_safe_folder's docstring for the incident).
    """
    os.makedirs(work_dir, exist_ok=True)

    print("\nLooking up OData product by Name:", catalog_id)
    product_id, name, s3_path = odata_lookup_product_by_name(access_token, catalog_id)
    if not product_id:
        raise RuntimeError(f"Could not resolve OData product for catalog id '{catalog_id}'.")

    product_dir = os.path.join(work_dir, name)  # dedicated per-product subfolder

    # If this exact product was already fully fetched in a previous run,
    # reuse it instead of re-downloading hundreds of MB again.
    existing = [
        os.path.join(product_dir, d) for d in os.listdir(product_dir)
        if os.path.isdir(product_dir) and d.upper().endswith(".SAFE")
    ] if os.path.isdir(product_dir) else []
    if existing:
        print(f"[fetch] {name} already extracted at {existing[0]}, reusing (skip re-download).")
        return existing[0]

    zip_path = os.path.join(product_dir, f"{name}.zip")
    os.makedirs(product_dir, exist_ok=True)
    download_product_zip(access_token, product_id, zip_path)

    return extract_safe_folder(zip_path, product_dir)


# =========================
#  PUBLIC ENTRY POINT
# =========================

def fetch_s1_scene(bbox=None, datetime_range=None, work_dir: str = "s1_download") -> str:
    """
    Full flow: search -> lookup -> download -> extract.
    Returns the path to the extracted `.SAFE` folder, ready to be passed
    as `--input` to preprocess_and_infer.py / run_pipeline.py.

    Also writes scene_metadata.json into `work_dir` (catalog id, real
    acquisition start/stop time from the SAFE manifest) -- the timing
    stage-3 output regions need. See scene_metadata.py.
    """
    print("Requesting CDSE access token...")
    token = get_cdse_access_token(CDSE_USERNAME, CDSE_PASSWORD, CDSE_TOTP)

    print("\nRunning Sentinel-1 GRD Catalog search...")
    item = catalog_search_s1_grd(token, bbox, datetime_range)
    if not item:
        raise RuntimeError("No Sentinel-1 GRD items found for the given BBOX/DATETIME.")

    safe_path = fetch_scene_by_catalog_id(token, item.get("id"), work_dir)

    metadata = build_scene_metadata(item, safe_path)
    save_scene_metadata(metadata, os.path.dirname(safe_path))

    return safe_path


def list_known_event_scenes(event_key: str):
    """
    Prints every Sentinel-1 pass available for a known real-world oil
    spill event OR a control scene (see KNOWN_OIL_SPILL_EVENTS and
    CONTROL_TEST_LOCATIONS), so you can pick one by index with
    fetch_known_event(event_key, pick_index=...).
    """
    ev = _resolve_scene_config(event_key)
    print(f"=== {event_key} ===\n{ev['description']}\n")

    token = get_cdse_access_token(CDSE_USERNAME, CDSE_PASSWORD, CDSE_TOTP)
    return search_scenes_list(token, ev["bbox"], ev["datetime"], limit=10)


def fetch_known_event(event_key: str, pick_index: int = 0, work_dir: str = "s1_download") -> str:
    """
    Downloads a specific pass (by index into the listing) for a known
    real-world oil spill event OR a control scene. Run
    list_known_event_scenes(event_key) first (or
    `python fetch_s1.py --event <key> --list`) to see indices.
    """
    ev = _resolve_scene_config(event_key)

    token = get_cdse_access_token(CDSE_USERNAME, CDSE_PASSWORD, CDSE_TOTP)
    items = search_scenes_list(token, ev["bbox"], ev["datetime"], limit=10)
    if not items:
        raise RuntimeError(f"No passes found for event '{event_key}' in its configured window.")
    if pick_index >= len(items):
        raise IndexError(f"pick_index={pick_index} out of range, only {len(items)} passes found.")

    chosen = items[pick_index]
    print(f"\nSelected pass [{pick_index}]: {chosen.get('id')}")
    safe_path = fetch_scene_by_catalog_id(token, chosen.get("id"), work_dir)

    metadata = build_scene_metadata(chosen, safe_path)
    save_scene_metadata(metadata, os.path.dirname(safe_path))

    return safe_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--event", default=None,
                         help=f"Known event or control scene key, e.g. "
                              f"{list(KNOWN_OIL_SPILL_EVENTS.keys()) + list(CONTROL_TEST_LOCATIONS.keys())}")
    parser.add_argument("--list", action="store_true",
                         help="List available Sentinel-1 passes for --event and exit")
    parser.add_argument("--pick", type=int, default=0,
                         help="Index of the pass to download, from --list output (default 0)")
    parser.add_argument("--work_dir", default="s1_download")
    args = parser.parse_args()

    if args.event:
        if args.list:
            list_known_event_scenes(args.event)
        else:
            safe_path = fetch_known_event(args.event, pick_index=args.pick, work_dir=args.work_dir)
            print(f"\nReady for preprocessing. SAFE folder:\n  {safe_path}")
            print(f"\nRun:\n  python preprocess_and_infer.py --input \"{safe_path}\" --output_dir scene_out")
    else:
        safe_path = fetch_s1_scene(work_dir=args.work_dir)
        print(f"\nReady for preprocessing. SAFE folder:\n  {safe_path}")
        print(f"\nRun:\n  python preprocess_and_infer.py --input \"{safe_path}\" --output_dir scene_out")
