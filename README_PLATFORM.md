# Oil Spill Investigation Platform

This workspace now includes an offline-first orchestration shell around the existing `Model` Stage 1 and `BacktrackModel` Stage 2/3 code. The platform owns event directories, manifests, SQLite progress, artifact discovery, safe serving, local imports, and raster quickviews. Scientific outputs remain unchanged.

## Windows PowerShell

```powershell
py -3.11 -m venv .venv-platform
.\.venv-platform\Scripts\Activate.ps1
python -m pip install -r backend\requirements.txt
$env:PYTHONPATH = "$PWD\backend"
uvicorn app.main:app --app-dir backend --reload --port 8000
```

Open `frontend\index.html` in a browser. The backend is the source of truth; the frontend uses only its local API. For a same-origin deployment, serve `frontend` with any local static server and set `window.OIL_PIPELINE_API` to `/api`.

## Supported workflows

Create an event with `POST /api/investigations`, then import an existing stage output directory by posting `{"existing_output_dir":"C:\\path\\to\\outputs","mode":"replay"}` to the stage run endpoint. Discovery is recursive and idempotent. TIFF/GeoTIFF sources are retained and quickviews are derived under the event's stage `quickviews` folder when rasterio and Pillow are installed.

Live Stage 1 calls the existing `Model/oilspill_service.py` contract. Stage 2 and Stage 3 live execution are deliberately reported as unavailable until their config-driven scripts are given an event-isolated adapter; local replay/import is fully supported without network access. Offline and replay runners never call external services.

## Import the current real outputs

1. Start the backend and frontend, create an investigation, and choose `replay` mode.
2. In the **Stage 1** panel, paste the folder containing the existing Stage 1 files, for example:

	```text
	C:\Users\abhin\Desktop\OilSpillPipeline\Model\outfinal
	```

	The viewer discovers `oil_regions.geojson`, `detection_report.json`, TIFF rasters, metadata, and generated quickviews.
3. In the **Stage 2** panel, paste the Stage 2 event folder:

	```text
	C:\Users\abhin\Desktop\OilSpillPipeline\BacktrackModel\ais_attribution_gfw\ais_attribution_gfw
	```

	This is where the currently checked-in `sanchi_2018_stage2_handoff.json` and `sanchi_2018_source_probability.geojson` actually live. The viewer recognizes those files and displays the observation time, simulation window, origin hypotheses, top probability cells, and limitations. If a future Stage 2 run has a complete `stage2_outputs\\<event>\\reports` folder, import that event folder instead. The currently checked-in `stage2_outputs\\sanchi_2018` folder contains no reports yet.
4. In the **Stage 3** panel, paste the output folder created by `test2.py`, normally:

	```text
	C:\Users\abhin\Desktop\OilSpillPipeline\BacktrackModel\ais_attribution_gfw\ais_attribution_gfw\ais_attribution_output
	```

	If you configured `OUTPUT_DIR` differently, paste that configured folder instead. The viewer recognizes the final ships/ranking JSON and renders the top candidates with the investigative-only disclaimer. Supporting JSON, CSV, GeoJSON, and logs remain downloadable in the artifact list.

The browser cannot read arbitrary Windows folders by itself. The path is entered into the local backend, which copies the files into the event folder; after that, replay is self-contained and the original folders are never exposed directly.

## Layout and safety

`DATA_ROOT` defaults to `./data`. Each event gets `event.json`, `manifest.json`, stage-specific folders, and a SQLite record. APIs accept only registered artifact IDs, resolve paths inside the event directory, and never expose arbitrary filesystem paths. Credentials are read from the process environment only and are never copied into events.

See `artifact_rules.yaml` for initial raster-role rules. The complete existing scientific limitations, including the Stage 2 candidate-origin caveats and Stage 3 non-culpability disclaimer, remain in the source handoff artifacts and should be displayed by a future richer summary adapter.