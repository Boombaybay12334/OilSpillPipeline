# Stage-2 FastAPI Service

Optional HTTP API wrapper for the Stage-2 oil-spill source/time backtracking
pipeline. This is additive: it does **not** alter `stage2_config.py`,
`run_stage2_pipeline.py`, or any other working Stage-2 file.

The service accepts a Stage-1 `oil_regions.geojson`, runs the existing
Stage-2 pipeline in an isolated job directory, and returns the two final
Stage-3-ready artifacts:

- `<event>_stage2_handoff.json`
- `<event>_source_probability.geojson`

If no GeoJSON is uploaded, the API copies and uses the default file:

```text
BacktrackModel/inputs/oil_regions.geojson
```

---

## Files to add

Place these **three new files** beside `run_stage2_pipeline.py` inside your
existing `BacktrackModel/` folder:

```text
api_server.py
requirements_api.txt
README_API.md
```

Do not move or modify existing Stage-2 files.

---

## Install

First ensure the normal Stage-2 package works from this folder:

```text
pip install -r requirements.txt
```

Then install API-only dependencies:

```text
pip install -r requirements_api.txt
```

The API process uses the same Python environment as your working pipeline,
so it must have OpenDrift, CMEMS, CDS API, xarray, NetCDF, Shapely, and
PyProj already installed via the main `requirements.txt`.

CMEMS and CDS credentials remain configured exactly as for CLI execution:

- CMEMS: `copernicusmarine login` or appropriate host environment variables.
- CDS/ERA5: `%USERPROFILE%/.cdsapirc` on Windows, containing your CDS URL
  and Personal Access Token.

The API does not copy secrets into job folders or output files. It launches
subprocesses inheriting the host process environment.

---

## Start the server

Open a terminal in `BacktrackModel/` and run:

```text
uvicorn api_server:app --host 127.0.0.1 --port 8000
```

Then open the interactive API UI in a browser:

```text
http://127.0.0.1:8000/docs
```

`127.0.0.1` means the service is available **only on your own computer**.
That is the recommended default while it has no user authentication.

To stop it, press `Ctrl+C` in the terminal running Uvicorn.

---

## API workflow

### 1. Check service health

`GET /health`

The result reports whether the required Stage-2 source files are present
and whether the default input exists.

Expected important fields:

```json
{
  "status": "ok",
  "default_geojson_exists": true,
  "required_pipeline_files_missing": []
}
```

### 2. Create a job

`POST /jobs` using `multipart/form-data`.

Fields:

| Field | Required? | Meaning |
|---|---:|---|
| `geojson` | No | Upload a Stage-1 `oil_regions.geojson`. If omitted, the normal `inputs/oil_regions.geojson` is copied and used. |
| `event_id` | No | Output/cache label, e.g. `event_2026_09_08`. Defaults to `oil_spill_event`. Allowed characters are sanitized automatically. |

In `/docs`, expand `POST /jobs`, click **Try it out**, optionally choose a
GeoJSON file, enter an event ID, and click **Execute**.

Successful response is HTTP `202 Accepted`, for example:

```json
{
  "job_id": "a_long_unique_id",
  "status": "queued",
  "event_id": "sanchi_2018_api",
  "using_default_input": false,
  "status_url": "/jobs/a_long_unique_id",
  "handoff_url": "/jobs/a_long_unique_id/handoff",
  "probability_geojson_url": "/jobs/a_long_unique_id/probability-geojson",
  "logs_url": "/jobs/a_long_unique_id/logs"
}
```

### 3. Poll job status

`GET /jobs/{job_id}`

Possible statuses:

| Status | Meaning |
|---|---|
| `queued` | Accepted but waiting for the single-job worker slot. |
| `running` | CMEMS/ERA5 retrieval and/or OpenDrift run is in progress. |
| `completed` | Both final artifacts exist and can be downloaded. |
| `failed` | Inspect `/jobs/{job_id}/logs` for the exact Stage-2 failure. |

### 4. Download results

After status becomes `completed`:

| Endpoint | Result |
|---|---|
| `GET /jobs/{job_id}/handoff` | Downloads `<event>_stage2_handoff.json` |
| `GET /jobs/{job_id}/probability-geojson` | Downloads `<event>_source_probability.geojson` |
| `GET /jobs/{job_id}/logs` | Downloads the complete stdout/stderr pipeline log |

---

## Job isolation and outputs

Each API request runs in its own folder:

```text
BacktrackModel/api_jobs/<job_id>/
├── inputs/
│   └── oil_regions.geojson
├── stage2_config.py             # generated only for this job
├── pipeline.log
├── prepare_observation.py        # copied pipeline source
├── ...
└── stage2_outputs/<event_id>/
    ├── env_data/
    ├── trajectories/
    └── reports/
        ├── <event>_stage2_handoff.json
        └── <event>_source_probability.geojson
```

This prevents one uploaded GeoJSON/event from overwriting another event's
output. The API permits one actual Stage‑2 run at a time by default, to
avoid duplicate CMEMS/ERA5 downloads and uncontrolled CPU/RAM contention.
Additional requests remain `queued` until the active job finishes.

The job registry is in memory: restarting Uvicorn clears job status from
the API, but does not delete any `api_jobs/<job_id>/` artifacts from disk.

---

## Default-input request

To run the normal GeoJSON already placed at:

```text
BacktrackModel/inputs/oil_regions.geojson
```

call `POST /jobs` with no uploaded `geojson` field. You can enter only an
`event_id`, or leave both fields blank.

---

## Security and deployment warning

This is intentionally a local-development API.

Do **not** expose it publicly (for example via `--host 0.0.0.0`, port
forwarding, or a public cloud IP) without adding:

- Authentication and authorization.
- Request-size, duration, CPU, RAM, and disk quotas.
- A persistent job queue/database rather than in-memory `JOBS`.
- User/job ownership rules.
- Controlled cleanup of old job folders.
- Rate limiting.
- A reverse proxy with TLS/HTTPS.
- A review of whether CMEMS/CDS credential use is appropriate for a
  multi-user deployment.

The service's outputs are model-derived candidate origin regions. They are
not proof of a vessel's responsibility; preserve the limitations embedded in
the Stage-2 handoff JSON if/when you build Stage 3.
