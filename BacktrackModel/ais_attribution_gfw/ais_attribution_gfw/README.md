# AIS Attribution Stage — Global Fishing Watch

This module is the **next stage after the existing oil-spill Stage-2 handoff**.

It does NOT try to "find the origin" of the spill.

Your existing pipeline gives an hourly backward-transport probability field:

```text
observed slick
      ↓
backward Lagrangian simulation
      ↓
possible oil locations at -1h, -2h, ... -69h
      ↓
probability cells for each hour
      ↓
THIS MODULE
      ↓
historical AIS vessel presence
      ↓
vessel/source compatibility ranking
```

The output is a ranked list of vessels whose AIS presence is spatially and
temporally compatible with the modeled backtracked source field.

## Why Global Fishing Watch?

This implementation uses:

```text
public-global-presence:latest
```

Global Fishing Watch describes this as global vessel presence derived from AIS.
It includes all vessel types and provides one AIS-derived position per vessel
per hour. It is therefore a good fit for the existing hourly backtracking field.

This is **not a continuous raw AIS track**. The returned coordinates represent
the spatial cell used by the selected GFW resolution.

GFW API access is currently non-commercial and requires a personal API token.

## 1. Get a GFW API token

Create a Global Fishing Watch account and create an API access token.

Then copy:

```text
.env.example
```

to:

```text
.env
```

and set:

```env
GFW_API_TOKEN=YOUR_TOKEN
```

Do NOT commit `.env`.

## 2. Install

Windows:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

Linux/macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 3. Put your existing files in the project

The important input is your existing:

```text
sanchi_2018_stage2_handoff.json
```

This code was written around that schema.

It reads:

```text
event_id
observation
backtracking
origin_hypotheses[]
    └── time_utc
    └── hours_before_observation
    └── top_cells[]
         ├── lon_center
         ├── lat_center
         ├── particle_count
         └── probability
```

The Stage-2 handoff is the source of truth for the modeled probability field.

### Optional observation summary

If you also give it:

```text
sanchi_2018_observation_summary.json
```

the code uses:

```text
search_window_start_utc
search_window_end_utc
padded_bbox_wsen
```

This is preferable because it uses the same AOI/time padding that your
existing pipeline already calculated.

## 4. Configure the paths

Edit `.env`:

```env
INPUT_HANDOFF_PATH=./sanchi_2018_stage2_handoff.json
INPUT_OBSERVATION_SUMMARY_PATH=./sanchi_2018_observation_summary.json
OUTPUT_DIR=./ais_attribution_output
```

You can point these at any event.

Example:

```env
INPUT_HANDOFF_PATH=D:/oilspill/events/sanchi_2018_stage2_handoff.json
INPUT_OBSERVATION_SUMMARY_PATH=D:/oilspill/events/sanchi_2018_observation_summary.json
OUTPUT_DIR=D:/oilspill/events/sanchi_2018/ais
```

## 5. Dry run first

Before touching the API:

```powershell
python ais_attribution.py --dry-run
```

You should see something like:

```text
Event: sanchi_2018
Source-probability hours: 70
AIS AOI: W=119.809062, S=23.240994, E=127.425051, N=31.287006
AIS time: 2018-01-22T12:42:34Z -> 2018-01-26T09:42:34Z
```

The exact values come from your input files/configuration.

## 6. Run

```powershell
python ais_attribution.py
```

The program submits **one** GFW report.

It does NOT launch 70 API calls.

This is intentional because GFW's report endpoint permits only one concurrent
report per user.

If the report returns a gateway timeout or another "already running" response,
the code uses GFW's `last-report` endpoint and waits for the existing report
instead of submitting duplicate reports.

## Output

You get:

```text
ais_attribution_output/
├── sanchi_2018_gfw_raw.json
└── sanchi_2018_ais_attribution.json
```

### Main output structure

```json
{
  "schema_version": "1.0",
  "event_id": "sanchi_2018",

  "observation": {
    "...": "copied from Stage-2 handoff"
  },

  "backtracking": {
    "method": "OpenDrift/OpenOil deterministic backward Lagrangian tracking",
    "simulation_start_utc": "2018-01-23T00:42:34.259036Z",
    "simulation_end_utc": "2018-01-25T21:42:34.259036Z",
    "backtrack_hours": 69
  },

  "ais": {
    "provider": "Global Fishing Watch",
    "dataset": "public-global-presence:latest",
    "spatial_resolution": "HIGH",
    "temporal_resolution": "HOURLY",
    "group_by": "MMSI",
    "search_window_start_utc": "...",
    "search_window_end_utc": "...",
    "aoi_wsen": [
      119.809062,
      23.240994,
      127.425051,
      31.287006
    ]
  },

  "source_probability_field": {
    "num_hourly_steps": 70,
    "num_probability_cells": 700
  },

  "summary": {
    "ais_rows_received": 12345,
    "candidate_vessels": 234,
    "top_candidate_mmsi": "..."
  },

  "candidates": [
    {
      "rank": 1,
      "mmsi": "...",
      "vessel_id": "...",
      "vessel_name": "...",
      "imo": "...",
      "callsign": "...",
      "flag": "...",
      "vessel_type": "TANKER",
      "geartype": "...",

      "matched_hours": 8,
      "type_prior": 1.0,
      "temporal_coverage_fraction": 0.114,

      "source_compatibility_score": 0.123,
      "final_source_compatibility_score": 0.081,

      "strongest_match": {
        "time_utc": "...",
        "ais_lat": 27.99,
        "ais_lon": 122.17,
        "source_lat": 27.9958,
        "source_lon": 122.1712,
        "distance_km": 1.2,
        "source_probability": 0.05586,
        "spatial_weight": 0.9968,
        "match_score": 0.05568
      },

      "top_matches": []
    }
  ]
}
```

## How the score works

For each AIS vessel position:

1. Convert the AIS timestamp to a UTC hour.
2. Find the Stage-2 source-probability cells for that same hour.
3. Calculate the distance from the AIS cell to every source-probability cell.
4. Apply a Gaussian distance weight.
5. Multiply that by the source probability.
6. Keep the vessel's best match for that hour.
7. Accumulate compatibility over time.
8. Apply a temporal-coverage factor.
9. Apply a weak vessel-type prior.

Conceptually:

```text
hourly_match =
    source_probability
    × spatial_distance_weight
```

Then:

```text
source_compatibility =
    Σ hourly_match
```

The final ranking additionally considers:

```text
temporal coverage
vessel type prior
```

## Important: this is NOT a guilt probability

Do not interpret:

```text
final_source_compatibility_score = 0.8
```

as:

```text
80% chance this ship caused the spill
```

It means the vessel's available AIS presence is highly compatible with the
backtracked source field under this scoring model.

A ship can be compatible without causing the spill.

A ship can also be absent from AIS because of incomplete coverage/transmission
and therefore should not automatically be ruled out.

## Why the model uses the whole backtrack

The model does NOT assume that:

```text
top cell at -69h = actual spill origin
```

Instead it compares vessels against the evolving field:

```text
t=-69h → possible source distribution
t=-68h → possible source distribution
...
t=-1h  → possible source distribution
t=0    → observed condition
```

This is the correct interpretation of the existing Stage-2 handoff.

## Tuning

### Spatial matching

```env
MATCH_SIGMA_KM=15
```

Smaller:

```env
MATCH_SIGMA_KM=5
```

makes the matching much stricter.

Larger:

```env
MATCH_SIGMA_KM=30
```

allows larger spatial disagreement.

This is a scoring parameter, not a statement that AIS itself is accurate to
that many kilometers.

### GFW spatial resolution

```env
GFW_SPATIAL_RESOLUTION=HIGH
```

Use HIGH for the attribution stage if the resulting report is manageable.

If a large event becomes slow/heavy:

```env
GFW_SPATIAL_RESOLUTION=LOW
```

is a fallback.

### Search window

If the observation summary is available, use it.

Otherwise:

```env
TIME_PADDING_HOURS=12
SPATIAL_PADDING_DEG=2
```

are used around the Stage-2 simulation window/AOI.

## What this version intentionally does NOT do yet

It does not claim to reconstruct a continuous vessel trajectory between GFW
hourly presence cells.

It does not infer spill release volume.

It does not infer oil type.

It does not create a legal/forensic accusation.

It does not treat the highest-ranked vessel as "the perpetrator".

Those should be later layers.

## Recommended next layer

Once this produces candidate vessels, the next improvement should be:

```text
AIS source compatibility
        +
ship trajectory consistency
        +
speed/course consistency
        +
vessel type
        +
known route / port context
        +
AIS gaps
        +
environmental drift uncertainty
        ↓
final attribution ranking
```

For candidate identity enrichment, the GFW Vessels API can resolve vessel identity
information from AIS plus public registries.

## Git

Add `.env` to `.gitignore`.

Never commit:

```text
.env
```

or your API token.
