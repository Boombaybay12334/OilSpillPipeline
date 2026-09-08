"""
run_pipeline.py
================
CLI wrapper over oilspill_service.py -- this file does NO orchestration of
its own anymore; it only parses args, builds a DetectionRequest, calls
detect(), and prints the result. All actual logic (fetch, SNAP, CFAR,
inference, regions) lives in oilspill_service.py and the bricks it wraps.
Kept deliberately thin so the CLI and any other integration (API, batch
script) can never drift out of sync with each other again.

Usage:
    python run_pipeline.py --output_dir scene_out --event sanchi_2018 --pick 0
    python run_pipeline.py --output_dir scene_out --event sanchi_2018 --list
    python run_pipeline.py --output_dir scene_out --bbox 11.0 55.0 13.0 56.0 \
        --datetime "2018-01-10T00:00:00Z/2018-01-10T23:59:59Z"
    python run_pipeline.py --output_dir scene_out --input path/to/existing.SAFE
"""

import argparse
import json

import oilspill_service as svc
from fetch_s1 import KNOWN_OIL_SPILL_EVENTS, CONTROL_TEST_LOCATIONS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output_dir", required=True)
    parser.add_argument("--input", default=None,
                         help="Skip fetching and use an existing .SAFE folder or .zip")
    parser.add_argument("--bbox", nargs=4, type=float, default=None,
                         metavar=("WEST", "SOUTH", "EAST", "NORTH"))
    parser.add_argument("--datetime", default=None,
                         help="e.g. 2018-01-10T00:00:00Z/2018-01-10T23:59:59Z")
    parser.add_argument("--event", default=None,
                         help=f"Fetch a known real oil spill event OR a control scene instead of "
                              f"--bbox/--datetime. Events: {list(KNOWN_OIL_SPILL_EVENTS.keys())}. "
                              f"Controls: {list(CONTROL_TEST_LOCATIONS.keys())}")
    parser.add_argument("--list", action="store_true",
                         help="With --event, just list available passes and exit (no download/inference)")
    parser.add_argument("--pick", type=int, default=0,
                         help="With --event, index of the pass to use (see --list output)")
    parser.add_argument("--no_cfar", action="store_true",
                         help="Disable the CFAR pre-filter and scan every tile (slower, old behavior)")
    parser.add_argument("--cfar_k", type=float, default=2.5,
                         help="CFAR sensitivity multiplier (2.0-3.0 typical). Lower = more candidates.")
    parser.add_argument("--strip_rows", type=int, default=4096,
                         help="Rows processed per streaming strip (lower = less peak memory, slower).")
    parser.add_argument("--json", action="store_true",
                         help="Print the full DetectionResult as JSON instead of a human summary "
                              "(useful when this CLI is itself called from another script).")
    args = parser.parse_args()

    if args.event and args.list:
        scenes = svc.search(svc.SearchRequest(event_key=args.event, limit=10))
        for i, s in enumerate(scenes):
            print(f"  [{i}] {s.catalog_id}")
            print(f"       datetime={s.datetime}  orbit={s.orbit_state}")
        return

    request = svc.DetectionRequest(
        output_dir=args.output_dir,
        input_safe_path=args.input,
        event_key=args.event,
        pick_index=args.pick,
        bbox=args.bbox,
        datetime_range=args.datetime,
        use_cfar=not args.no_cfar,
        cfar_k=args.cfar_k,
        strip_rows=args.strip_rows,
    )

    result = svc.detect(request)

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
        return

    if not result.success:
        print(f"\n=== FAILED ===\n{result.error}")
        raise SystemExit(1)

    print(f"\n=== DONE ===")
    print(f"Regions detected:    {result.n_regions}")
    print(f"Total oil area:      {result.total_oil_area_km2} km^2")
    print(f"Probability mask:    {result.probability_mask_tif}")
    print(f"Regions (GeoJSON):   {result.regions_geojson}")
    print(f"Full report (JSON):  {result.detection_report_json}")


if __name__ == "__main__":
    main()
