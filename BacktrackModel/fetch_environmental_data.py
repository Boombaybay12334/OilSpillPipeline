"""
fetch_environmental_data.py
=============================
Stage-2, Brick 2: download historical ocean currents (Copernicus Marine /
CMEMS GLORYS12V1) and 10m winds (ERA5 via the Copernicus Climate Data
Store) for EXACTLY the padded bbox + search time window computed by
prepare_observation.py for one event.

This is a NETWORK-DEPENDENT script. Requires:
  pip install copernicusmarine cdsapi

Credentials:
  Copernicus Marine: run `copernicusmarine login` once (recommended), OR
  set COPERNICUSMARINE_SERVICE_USERNAME / _PASSWORD.

  CDS (ERA5): create %USERPROFILE%\\.cdsapirc (Windows) or ~/.cdsapirc
  (Linux/Mac) with:
      url: https://cds.climate.copernicus.eu/api
      key: <your Personal Access Token from https://cds.climate.copernicus.eu/profile>
  Also accept the ERA5 dataset terms once on the CDS website before your
  first request.

Run directly to fetch both datasets for the event configured in
stage2_config.py:
    python fetch_environmental_data.py

Each dataset is only re-downloaded if the target file does not already
exist, to avoid needless re-fetching during iterative development.
"""

from __future__ import annotations

import os

import stage2_config as cfg
from prepare_observation import load_observation


def _export_cds_env_vars() -> None:
    if cfg.CDSAPI_URL:
        os.environ.setdefault("CDSAPI_URL", cfg.CDSAPI_URL)
    if cfg.CDSAPI_KEY:
        os.environ.setdefault("CDSAPI_KEY", cfg.CDSAPI_KEY)


def fetch_currents(west: float, south: float, east: float, north: float,
                    start_iso: str, end_iso: str) -> None:
    """Downloads ocean current components (uo, vo) from CMEMS GLOBAL_MULTIYEAR
    reanalysis (GLORYS12V1) via the `copernicusmarine` Python client.

    Swap dataset_id below for a regional product if one exists for your
    study area -- GLORYS12 is the global fallback used here because it
    always has historical coverage.
    """
    if cfg.CURRENTS_NC.exists():
        print(f"[fetch_currents] Already exists, skipping: {cfg.CURRENTS_NC}")
        return

    try:
        import copernicusmarine
    except ImportError as exc:
        raise SystemExit(
            "The 'copernicusmarine' package is required.\n"
            "Install with: pip install copernicusmarine"
        ) from exc

    print(f"[fetch_currents] Requesting uo/vo for bbox=({west},{south},{east},{north}), "
          f"time=({start_iso} to {end_iso})")

    copernicusmarine.subset(
        dataset_id="cmems_mod_glo_phy_my_0.083deg_P1D-m",  # GLORYS12V1 daily
        variables=["uo", "vo"],
        minimum_longitude=west,
        maximum_longitude=east,
        minimum_latitude=south,
        maximum_latitude=north,
        start_datetime=start_iso,
        end_datetime=end_iso,
        minimum_depth=0.0,
        maximum_depth=1.0,  # surface currents only; widen if you need subsurface
        output_filename=str(cfg.CURRENTS_NC.name),
        output_directory=str(cfg.CURRENTS_NC.parent),
        username=cfg.CMEMS_USERNAME,
        password=cfg.CMEMS_PASSWORD,
    )
    print(f"[fetch_currents] Wrote -> {cfg.CURRENTS_NC}")


def fetch_winds(west: float, south: float, east: float, north: float,
                 start_iso: str, end_iso: str) -> None:
    """Downloads ERA5 10m u/v wind components via the `cdsapi` client."""
    if cfg.WINDS_NC.exists():
        print(f"[fetch_winds] Already exists, skipping: {cfg.WINDS_NC}")
        return

    try:
        import cdsapi
    except ImportError as exc:
        raise SystemExit(
            "The 'cdsapi' package is required.\n"
            "Install with: pip install cdsapi"
        ) from exc

    from datetime import datetime, timedelta

    _export_cds_env_vars()

    start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
    end_dt = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))

    days = sorted({(start_dt + timedelta(days=d)).strftime("%Y-%m-%d")
                    for d in range((end_dt.date() - start_dt.date()).days + 1)})
    years = sorted({d[:4] for d in days})
    months = sorted({d[5:7] for d in days})
    day_nums = sorted({d[8:10] for d in days})
    times = [f"{h:02d}:00" for h in range(24)]

    print(f"[fetch_winds] Requesting 10m u/v wind for bbox=({west},{south},{east},{north}), "
          f"years={years}, months={months}, days={day_nums}")

    client = cdsapi.Client()
    client.retrieve(
        "reanalysis-era5-single-levels",
        {
            "product_type": "reanalysis",
            "variable": ["10m_u_component_of_wind", "10m_v_component_of_wind"],
            "year": years,
            "month": months,
            "day": day_nums,
            "time": times,
            # CDS area format is [north, west, south, east]
            "area": [north, west, south, east],
            "format": "netcdf",
        },
        str(cfg.WINDS_NC),
    )
    print(f"[fetch_winds] Wrote -> {cfg.WINDS_NC}")


def main() -> None:
    obs = load_observation()
    west, south, east, north = obs.padded_bbox
    window_start, window_end = obs.search_time_window
    start_iso = window_start.isoformat().replace("+00:00", "Z")
    end_iso = window_end.isoformat().replace("+00:00", "Z")

    print(f"Event:        {obs.event_id}")
    print(f"Bbox (WSEN):  {west}, {south}, {east}, {north}")
    print(f"Time window:  {start_iso}  to  {end_iso}\n")

    fetch_currents(west, south, east, north, start_iso, end_iso)
    fetch_winds(west, south, east, north, start_iso, end_iso)

    print("\nNEXT: run inspect_environmental_data.py to verify coverage before "
          "wiring these into OpenDrift readers.")


if __name__ == "__main__":
    main()
