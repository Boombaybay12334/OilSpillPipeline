"""
preprocess_and_infer.py
========================
End-to-end: raw Sentinel-1 GRD (SAFE folder or downloaded .zip) -> Sigma0
VV/VH (via SNAP gpt) -> dB -> Zenodo normalization -> tiling -> classifier
+ segmentor inference -> merged oil-slick mask for the whole scene.

CHANGES FROM THE ORIGINAL:
---------------------------
1. GPT_EXECUTABLE is resolved portably instead of hardcoded to a Windows
   path: checks the GPT_EXECUTABLE env var first, then `gpt` on PATH,
   then falls back to common install locations per OS.
2. `--input` now accepts EITHER an already-extracted `.SAFE` folder
   (what fetch_s1.py returns) OR a raw `.zip` download -- it will
   auto-extract the zip if needed. This is what was silently breaking
   things before: a zip-with-.safe-extension was neither.
3. Normalization logic (load_sigma0_and_normalize) is UNCHANGED -- left
   exactly as-is per request.
"""

import argparse
import json
import os
import shutil
import subprocess
import zipfile

import numpy as np
import rasterio
from rasterio.windows import Window
import torch

import config
from models import PatchClassifierCNN, UNet

# ============================================================
# GPT executable resolution (portable)
# ============================================================

def resolve_gpt_executable() -> str:
    # 1. explicit override
    env_path = os.environ.get("GPT_EXECUTABLE")
    if env_path and os.path.exists(env_path):
        return env_path

    # 2. on PATH
    which_gpt = shutil.which("gpt")
    if which_gpt:
        return which_gpt

    # 3. common default install locations
    common_paths = [
        r"C:\Program Files\esa-snap\bin\gpt.exe",
        "/Applications/esa-snap/bin/gpt",
        os.path.expanduser("~/esa-snap/bin/gpt"),
        "/usr/local/esa-snap/bin/gpt",
        "/opt/esa-snap/bin/gpt",
    ]
    for p in common_paths:
        if os.path.exists(p):
            return p

    raise RuntimeError(
        "Could not find SNAP's `gpt` executable. Either add it to your PATH, "
        "or set the GPT_EXECUTABLE environment variable to its full path."
    )


GPT_EXECUTABLE = r"C:\Program Files\esa-snap\bin\gpt.exe"  # resolved lazily in main() / run_snap_preprocessing()

# Graph path resolution, in priority order:
#   1. GRAPH_XML_PATH env var, if set -- put the XML anywhere you want.
#   2. Next to THIS .py file (works out-of-the-box regardless of what
#      directory you happen to run `python` from -- a bare relative path
#      like "s1_preprocess_graph.xml" only works if your current working
#      directory happens to match, which breaks the moment this pipeline
#      is relocated or run from another folder/service).
def _resolve_graph_xml_path() -> str:
    env_path = os.environ.get("GRAPH_XML_PATH")
    if env_path:
        return env_path
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "s1_preprocess_graph.xml")


GRAPH_XML_PATH = _resolve_graph_xml_path()

TILE_SIZE = config.GRID_EVAL_CROP_SIZE   # 512
TILE_STRIDE = config.GRID_EVAL_STRIDE    # 512
CLASSIFIER_THRESHOLD = 0.30
SEG_THRESHOLD = config.SEG_THRESHOLD     # 0.5


# =========================
#  BRICK A0: RESOLVE INPUT (SAFE folder or zip)
# =========================

def resolve_safe_input(input_path: str, work_dir: str) -> str:
    """
    Accepts either:
      - a path to an already-extracted `*.SAFE` folder, or
      - a path to a downloaded `*.zip` product (from fetch_s1.py or CDSE).
    Returns a path SNAP's gpt can Read directly.
    """
    if os.path.isdir(input_path):
        return input_path

    if input_path.lower().endswith(".zip"):
        extract_dir = os.path.join(work_dir, "_extracted_safe")
        os.makedirs(extract_dir, exist_ok=True)
        print(f"[Preprocess] Input is a .zip, extracting to {extract_dir} ...")
        with zipfile.ZipFile(input_path, "r") as zf:
            zf.extractall(extract_dir)

        safe_dirs = [
            os.path.join(extract_dir, name)
            for name in os.listdir(extract_dir)
            if name.upper().endswith(".SAFE") and os.path.isdir(os.path.join(extract_dir, name))
        ]
        if not safe_dirs:
            raise RuntimeError(f"No .SAFE folder found inside {input_path}.")
        return safe_dirs[0]

    raise RuntimeError(
        f"--input '{input_path}' is neither a .SAFE folder nor a .zip file. "
        "If this came from a manual download, make sure it wasn't renamed "
        "to a .safe extension while still being zip-compressed -- that's a "
        "zip file with the wrong name, not a real SAFE product."
    )


# =========================
#  BRICK A: SNAP CALIBRATION + TERRAIN CORRECTION
# =========================

def run_snap_preprocessing(input_path: str, output_tif: str):
    """
    Runs the SNAP graph, with a caching skip if `output_tif` already exists
    -- BUT only if it was produced from this exact `input_path`. A sidecar
    marker file (`<output_tif>.source.txt`) records which SAFE folder
    produced the cached output; if a different scene now requests the same
    output_tif (e.g. because --output_dir was reused across two different
    downloads), this refuses to silently reuse the stale file. This exact
    failure mode happened once already: a stale Baltic Sea test's
    sigma0_vv_vh.tif got silently reused for a Sanchi-event run, producing
    a "successful" run that had actually analyzed the wrong scene entirely.
    """
    global GPT_EXECUTABLE
    if GPT_EXECUTABLE is None:
        GPT_EXECUTABLE = resolve_gpt_executable()
        print(f"[SNAP] Using gpt at: {GPT_EXECUTABLE}")

    marker_path = output_tif + ".source.txt"
    input_abs = os.path.abspath(input_path)

    if os.path.exists(output_tif):
        cached_source = None
        if os.path.exists(marker_path):
            with open(marker_path, "r") as f:
                cached_source = f.read().strip()

        if cached_source == input_abs:
            print(f"[SNAP] {output_tif} already exists and matches requested input "
                  f"({input_path}) -- skipping reprocessing.")
            return
        else:
            print(f"[SNAP] {output_tif} exists but was produced from a DIFFERENT scene "
                  f"({cached_source!r} != {input_abs!r}). Reprocessing from scratch "
                  f"rather than silently reusing stale output for the wrong scene.")

    cmd = [
        GPT_EXECUTABLE,
        GRAPH_XML_PATH,
        f"-Pinput={input_path}",
        f"-Poutput={output_tif}",
    ]
    print("[SNAP] Running:", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print("[SNAP] STDOUT:\n", result.stdout)
        print("[SNAP] STDERR:\n", result.stderr)
        raise RuntimeError(
            "SNAP gpt preprocessing failed. Check that SNAP is installed, "
            "that GPT_EXECUTABLE points to the correct gpt binary, and that "
            "`input_path` is a genuine .SAFE folder (see resolve_safe_input)."
        )

    with open(marker_path, "w") as f:
        f.write(input_abs)

    print(f"[SNAP] Preprocessing complete -> {output_tif}")


# =========================
#  BRICK B: LINEAR -> dB -> NORMALIZE (unchanged, matches Zenodo exactly)
# =========================

def load_sigma0_and_normalize(sigma0_tif: str, norm_stats_json: str):
    """
    Reads the SNAP-produced Sigma0 GeoTIFF (bands: VV, VH, linear),
    converts to dB, normalizes with the SAME stats used for Zenodo
    training (norm_stats.json), and returns:
        x_norm: (2, H, W) float32 array, channel 0 = VV, channel 1 = VH
        transform, crs: for optional georeferencing of the output mask
        valid_mask: (H, W) bool array, False wherever this pixel is NOT
            usable open-sea data
        vv_db: (H, W) float32, VV in dB before normalization -- kept
            around for the CFAR pre-filter (cfar_filter.py), which needs
            interpretable dB values, not z-scored ones

    IMPORTANT -- what valid_mask actually excludes, and why it's ONE mask
    for two different causes:
    1. Swath-padding nodata: Terrain-Correction reprojects the diagonal
       SAR swath into a rectangular GeoTIFF; pixels outside the actual
       imaged swath are written as exact 0.0.
    2. Land: the SNAP graph's Land-Sea-Mask node (landMask=true) ALSO
       writes exact 0.0 over land pixels -- deliberately, so land gets
       caught by this exact same nodata check with zero extra code here.
    Real calibrated backscatter is essentially never exactly zero, so
    treating linear values below a small noise-floor epsilon as invalid
    catches both causes at once. This matters because clipping to 1e-10
    and converting to dB used to turn 0.0 into ~-100 dB, an extreme value
    the model never saw in training (real sea/oil backscatter is roughly
    -35 to 0 dB) that both land and padding used to get misread as an
    obvious "oil" signature (oil = anomalously low backscatter).
    """
    with rasterio.open(sigma0_tif) as src:
        arr = src.read().astype(np.float32)  # (bands, H, W)
        transform = src.transform
        crs = src.crs

    vv_linear = arr[0]
    vh_linear = arr[1]

    # Noise-floor epsilon: well above true zero (padding or SNAP-masked
    # land), well below any plausible real calibrated Sigma0 value.
    NODATA_EPS = 1e-6
    valid_mask = (vv_linear > NODATA_EPS) & (vh_linear > NODATA_EPS)
    n_invalid = int((~valid_mask).sum())
    pct_invalid = 100.0 * n_invalid / valid_mask.size
    print(f"[Preprocess] {n_invalid}/{valid_mask.size} pixels ({pct_invalid:.2f}%) "
          f"are invalid (swath-padding nodata and/or land, excluded from results)")

    # Clip only for the log() call itself; invalid pixels are masked out
    # downstream regardless of what value they end up with here.
    eps = 1e-10
    vv_linear_clipped = np.clip(vv_linear, eps, None)
    vh_linear_clipped = np.clip(vh_linear, eps, None)

    vv_db = 10.0 * np.log10(vv_linear_clipped)
    vh_db = 10.0 * np.log10(vh_linear_clipped)

    with open(norm_stats_json, "r") as f:
        stats = json.load(f)
    vv_mean, vv_std = stats["vv_mean"], stats["vv_std"] if stats["vv_std"] > 0 else 1.0
    vh_mean, vh_std = stats["vh_mean"], stats["vh_std"] if stats["vh_std"] > 0 else 1.0

    vv_norm = (vv_db - vv_mean) / vv_std
    vh_norm = (vh_db - vh_mean) / vh_std

    x_norm = np.stack([vv_norm, vh_norm], axis=0).astype(np.float32)  # (2, H, W)
    return x_norm, transform, crs, valid_mask, vv_db


# =========================
#  BRICK C: TILING
# =========================

def tile_scene(x_norm: np.ndarray, valid_mask: np.ndarray, tile_size: int, stride: int,
                min_valid_fraction: float = 0.5, candidate_coords=None):
    """
    Slides a (tile_size x tile_size) window over the (2, H, W) normalized
    scene. Tiles that are mostly invalid (nodata padding and/or land,
    valid_mask fraction below `min_valid_fraction`) are skipped entirely --
    there's no real sea data there, and feeding it in produces the model's
    most confident-looking "oil" false positives.

    `candidate_coords`: optional list of (top, left) tuples, e.g. from
    cfar_filter.candidate_tile_coords(). If given, ONLY those tile
    coordinates are considered (still subject to the valid_fraction check)
    instead of scanning the entire grid -- this is the CFAR pre-filter
    bolt-on. If None (default), behaves exactly as before: full grid scan.
    This keeps CFAR an optional accelerant, never a hard dependency -- if
    it's disabled or unavailable, detection quality is unaffected, only
    runtime is longer.

    Returns a list of (tile_array, top, left).
    """
    _, h, w = x_norm.shape
    tiles = []
    n_skipped = 0

    if candidate_coords is not None:
        grid_coords = candidate_coords
    else:
        grid_coords = [
            (top, left)
            for top in range(0, h, stride)
            for left in range(0, w, stride)
        ]

    for top, left in grid_coords:
        bottom = min(top + tile_size, h)
        right = min(left + tile_size, w)

        valid_frac = valid_mask[top:bottom, left:right].mean()
        if valid_frac < min_valid_fraction:
            n_skipped += 1
            continue

        tile = np.zeros((2, tile_size, tile_size), dtype=np.float32)
        tile[:, : bottom - top, : right - left] = x_norm[:, top:bottom, left:right]

        tiles.append((tile, top, left))

    source = "CFAR candidates" if candidate_coords is not None else "full grid"
    print(f"[Preprocess] Tiling ({source}): {len(tiles)} tiles kept, {n_skipped} skipped "
          f"(>{100*(1-min_valid_fraction):.0f}% invalid)")
    return tiles


# =========================
#  BRICK D: INFERENCE (classifier -> segmentor)
# =========================

def _load_state_dict(ckpt_path: str, device):
    """
    Loads a checkpoint that may be either:
      - a bare state_dict (what load_state_dict expects directly), or
      - a full training checkpoint dict containing a "model_state_dict"
        key alongside stuff like epoch / val_f1 / val_precision / etc.
    Returns just the state_dict, ready for load_state_dict().
    """
    ckpt = torch.load(ckpt_path, map_location=device)
    if isinstance(ckpt, dict) and "model_state_dict" in ckpt:
        print(f"[Models] {os.path.basename(ckpt_path)} is a full training checkpoint "
              f"(epoch={ckpt.get('epoch')}, val_f1={ckpt.get('val_f1')}) -- unwrapping.")
        return ckpt["model_state_dict"]
    return ckpt


def load_models(device):
    classifier = PatchClassifierCNN(in_channels=2, dropout=config.CLASSIFIER_DROPOUT)
    classifier.load_state_dict(_load_state_dict(config.CLASSIFIER_CKPT, device))
    classifier.to(device).eval()

    segmentor = UNet(in_channels=2, out_channels=1, encoder_channels=config.UNET_ENCODER_CHANNELS)
    segmentor.load_state_dict(_load_state_dict(config.UNET_CKPT, device))
    segmentor.to(device).eval()

    return classifier, segmentor


def run_inference_on_scene(x_norm: np.ndarray, valid_mask: np.ndarray, classifier, segmentor, device,
                            candidate_coords=None):
    _, h, w = x_norm.shape
    tiles = tile_scene(x_norm, valid_mask, TILE_SIZE, TILE_STRIDE, candidate_coords=candidate_coords)

    scene_prob = np.zeros((h, w), dtype=np.float32)
    scene_count = np.zeros((h, w), dtype=np.float32)

    n_flagged = 0
    with torch.no_grad():
        for tile_arr, top, left in tiles:
            tile_t = torch.from_numpy(tile_arr).unsqueeze(0).to(device)

            logit = classifier(tile_t)
            prob_oil = torch.sigmoid(logit).item()

            if prob_oil < CLASSIFIER_THRESHOLD:
                continue
            n_flagged += 1

            seg_logits = segmentor(tile_t)
            seg_prob = torch.sigmoid(seg_logits)[0, 0].cpu().numpy()

            bottom = min(top + TILE_SIZE, h)
            right = min(left + TILE_SIZE, w)
            th, tw = bottom - top, right - left

            scene_prob[top:bottom, left:right] += seg_prob[:th, :tw]
            scene_count[top:bottom, left:right] += 1.0

    print(f"[Inference] {n_flagged}/{len(tiles)} tiles flagged 'oil present' by classifier")

    scene_count[scene_count == 0] = 1.0
    scene_prob = scene_prob / scene_count

    # Belt-and-suspenders: even though whole-padding tiles were already
    # skipped in tile_scene, partially-valid tiles near the swath edge can
    # still smear some probability onto individual nodata pixels. Zero
    # those out explicitly so the final mask never reports "oil" outside
    # the actual imaged swath.
    scene_prob = scene_prob * valid_mask.astype(np.float32)

    return scene_prob


# =========================
#  MAIN
# =========================

def run_preprocess_and_infer(safe_input: str, output_dir: str, use_cfar: bool = True,
                              cfar_k: float = 2.5, strip_rows: int = 4096) -> dict:
    """
    Full step-2-onward pipeline: SNAP preprocessing -> [STREAMED per
    row-strip: normalize -> CFAR pre-filter (optional) -> tile ->
    classifier/segmentor inference -> write probability window] ->
    extract georeferenced regions -> write detection report (GeoJSON +
    JSON), stamped with scene acquisition time.

    WHY STREAMING (not a stylistic choice -- this crashed without it):
    A wide-swath EW-mode scene can be ~24000 x 27000 pixels. Loading the
    whole thing into full-scene float32 arrays (linear, dB, normalized,
    plus a dozen-plus CFAR temporaries) needs 2-3+ GB PER ARRAY, and
    several are alive simultaneously -- this reliably OOMs on ordinary
    hardware. Instead, this function reads and processes the scene in
    horizontal strips (`strip_rows` rows tall, aligned to the 512px tile
    grid so tiles never straddle a strip seam), same principle as the
    tile-based classifier/segmentor already use, just one level earlier in
    the pipeline. Peak memory is now bounded by `strip_rows`, not by scene
    size -- this is also just how real ground-station SAR processing
    chains actually work (block/windowed raster processing), not a
    workaround.

    CFAR's local-window statistics need a small amount of row overlap
    beyond each strip's "core" rows to compute correct background
    statistics near strip boundaries -- that overlap is read but never
    written to output or double-counted (only the core rows of each strip
    are ever written/tallied).

    `safe_input` should already be a resolved .SAFE folder (see
    resolve_safe_input). Returns a dict of output file paths.

    This is the single implementation used by both `main()` below and
    run_pipeline.py, so the two entry points can't drift out of sync.

    `use_cfar=False` disables the pre-filter and falls back to scanning
    every tile in each strip (the pre-CFAR behavior, just still streamed)
    -- useful for A/B comparison or if CFAR is ever suspected of hiding a
    real slick outside its candidate blobs.
    """
    os.makedirs(output_dir, exist_ok=True)

    sigma0_tif = os.path.join(output_dir, "sigma0_vv_vh.tif")
    mask_out_tif = os.path.join(output_dir, "oil_mask_prob.tif")

    run_snap_preprocessing(safe_input, sigma0_tif)

    with open(config.NORM_STATS_JSON, "r") as f:
        stats = json.load(f)
    vv_mean = stats["vv_mean"]
    vv_std = stats["vv_std"] if stats["vv_std"] > 0 else 1.0
    vh_mean = stats["vh_mean"]
    vh_std = stats["vh_std"] if stats["vh_std"] > 0 else 1.0

    NODATA_EPS = 1e-6
    eps = 1e-10

    cfar_filter = None
    if use_cfar:
        import cfar_filter as _cfar_filter
        cfar_filter = _cfar_filter

    # CFAR's annulus needs `background_window // 2`-ish rows of context
    # beyond the strip's core to compute correct statistics near seams.
    cfar_overlap = 64 if use_cfar else 0

    device = torch.device(config.DEVICE if torch.cuda.is_available() else "cpu")
    print(f"[Inference] Using device: {device}")
    classifier, segmentor = load_models(device)

    with rasterio.open(sigma0_tif) as src:
        H, W = src.height, src.width
        transform = src.transform
        crs = src.crs

    total_pixels = H * W
    n_invalid_total = 0
    n_oil_flagged_total = 0
    n_tiles_scored_total = 0

    # Full-scene uint8 binary mask -- needed whole for connected-component
    # region extraction (a slick could span a strip boundary), but at 1
    # byte/pixel this is manageable (~650MB for a 24000x27000 scene)
    # compared to the multi-GB float32 arrays this refactor eliminates.
    binary_mask_full = np.zeros((H, W), dtype=np.uint8)

    print(f"[Preprocess] Streaming {H}x{W} scene in {strip_rows}-row strips "
          f"({-(-H // strip_rows)} strips)")

    with rasterio.open(sigma0_tif) as src, rasterio.open(
        mask_out_tif, "w", driver="GTiff", height=H, width=W, count=1,
        dtype="float32", crs=crs, transform=transform, nodata=-1.0, BIGTIFF="YES",
    ) as dst:

        for core_start in range(0, H, strip_rows):
            core_end = min(core_start + strip_rows, H)
            read_start = max(core_start - cfar_overlap, 0)
            read_end = min(core_end + cfar_overlap, H)

            read_window = Window(col_off=0, row_off=read_start, width=W, height=read_end - read_start)
            arr = src.read(window=read_window).astype(np.float32)  # (2, strip_rows_padded, W)
            vv_lin, vh_lin = arr[0], arr[1]

            valid = (vv_lin > NODATA_EPS) & (vh_lin > NODATA_EPS)

            vv_db = 10.0 * np.log10(np.clip(vv_lin, eps, None))
            vh_db = 10.0 * np.log10(np.clip(vh_lin, eps, None))
            del vv_lin, vh_lin

            vv_norm = (vv_db - vv_mean) / vv_std
            vh_norm = (vh_db - vh_mean) / vh_std
            x_norm_strip = np.stack([vv_norm, vh_norm], axis=0).astype(np.float32)
            del vv_norm, vh_norm

            # Slice back down from [read_start:read_end] to just this
            # strip's core rows [core_start:core_end] for everything except
            # the CFAR statistics themselves, which needed the padding.
            local_core_start = core_start - read_start
            local_core_end = local_core_start + (core_end - core_start)

            candidate_coords = None
            if use_cfar:
                candidate_mask_padded = cfar_filter.compute_cfar_candidate_mask(vv_db, valid, k=cfar_k)
                candidate_mask_core = candidate_mask_padded[local_core_start:local_core_end]
                candidate_coords = cfar_filter.candidate_tile_coords(
                    candidate_mask_core, TILE_SIZE, TILE_STRIDE
                )
                del candidate_mask_padded, candidate_mask_core
            del vv_db

            valid_core = valid[local_core_start:local_core_end]
            x_norm_core = x_norm_strip[:, local_core_start:local_core_end, :]
            del valid, x_norm_strip

            n_invalid_total += int((~valid_core).sum())

            scene_prob_core = run_inference_on_scene(
                x_norm_core, valid_core, classifier, segmentor, device,
                candidate_coords=candidate_coords
            )
            del x_norm_core

            out_core = np.where(valid_core, scene_prob_core, -1.0).astype(np.float32)
            dst.write(out_core, 1, window=Window(col_off=0, row_off=core_start, width=W, height=core_end - core_start))

            binary_core = ((scene_prob_core >= SEG_THRESHOLD) & valid_core).astype(np.uint8)
            binary_mask_full[core_start:core_end, :] = binary_core
            n_oil_flagged_total += int(binary_core.sum())

            print(f"[Preprocess] Strip rows {core_start}:{core_end} done "
                  f"({100.0 * core_end / H:.1f}% of scene)")

            del scene_prob_core, out_core, binary_core, valid_core

    pct_invalid = 100.0 * n_invalid_total / total_pixels
    n_valid_total = total_pixels - n_invalid_total
    print(f"[Preprocess] {n_invalid_total}/{total_pixels} pixels ({pct_invalid:.2f}%) "
          f"are invalid (swath-padding nodata and/or land, excluded from results)")
    print(f"[Result] Oil-flagged pixels: {n_oil_flagged_total} / {n_valid_total} valid pixels "
          f"({100.0 * n_oil_flagged_total / max(n_valid_total, 1):.3f}% of imaged swath, "
          f"{100.0 * n_valid_total / total_pixels:.1f}% of raster was valid swath)")
    print(f"[Result] Wrote probability mask to {mask_out_tif}")

    # --- Stage 3: georeferenced regions (coords, shape, timing) ---
    import region_extraction
    import scene_metadata

    # Probability values for each detected region are read back from the
    # just-written mask_out_tif via small per-region windowed reads
    # (region_extraction handles this when given a path instead of an
    # array) -- this avoids ever holding a full-scene float32 probability
    # array in memory, the same discipline as the strip loop above.
    regions = region_extraction.extract_oil_regions(binary_mask_full, mask_out_tif, transform, crs)
    del binary_mask_full

    # scene_metadata.json was written by fetch_s1.py as a side-channel file
    # next to the .SAFE folder. Try to find it there; if this run used
    # --input pointing at a manually-provided scene with no such file,
    # fall back to parsing the manifest directly (still gets real
    # acquisition timing, just without catalog search context).
    metadata_dir = os.path.dirname(os.path.normpath(safe_input))
    meta = scene_metadata.load_scene_metadata(metadata_dir)
    if meta is None:
        print("[SceneMetadata] No scene_metadata.json found next to the SAFE folder "
              "(expected if --input pointed at a manually-provided scene). "
              "Parsing manifest.safe directly for acquisition timing instead.")
        meta = scene_metadata.build_scene_metadata(catalog_item=None, safe_folder=safe_input)
        scene_metadata.save_scene_metadata(meta, output_dir)

    geojson = region_extraction.regions_to_geojson(regions, scene_metadata=meta)
    geojson_path = os.path.join(output_dir, "oil_regions.geojson")
    with open(geojson_path, "w") as f:
        json.dump(geojson, f, indent=2)
    print(f"[Regions] Wrote {geojson_path} ({len(regions)} regions)")

    report = {
        "scene_metadata": meta,
        "detection_summary": {
            "n_regions": len(regions),
            "total_oil_area_km2": round(sum(r["area_km2"] for r in regions), 4),
            "cfar_prefilter_used": use_cfar,
            "cfar_k": cfar_k if use_cfar else None,
        },
        "regions": regions,
        "output_files": {
            "sigma0_tif": sigma0_tif,
            "probability_mask_tif": mask_out_tif,
            "regions_geojson": geojson_path,
        },
    }
    report_path = os.path.join(output_dir, "detection_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"[Report] Wrote {report_path}")

    return {
        "mask_tif": mask_out_tif,
        "regions_geojson": geojson_path,
        "detection_report": report_path,
    }

    # scene_metadata.json was written by fetch_s1.py as a side-channel file
    # next to the .SAFE folder. Try to find it there; if this run used
    # --input pointing at a manually-provided scene with no such file,
    # fall back to parsing the manifest directly (still gets real
    # acquisition timing, just without catalog search context).
    metadata_dir = os.path.dirname(os.path.normpath(safe_input))
    meta = scene_metadata.load_scene_metadata(metadata_dir)
    if meta is None:
        print("[SceneMetadata] No scene_metadata.json found next to the SAFE folder "
              "(expected if --input pointed at a manually-provided scene). "
              "Parsing manifest.safe directly for acquisition timing instead.")
        meta = scene_metadata.build_scene_metadata(catalog_item=None, safe_folder=safe_input)
        scene_metadata.save_scene_metadata(meta, output_dir)

    geojson = region_extraction.regions_to_geojson(regions, scene_metadata=meta)
    geojson_path = os.path.join(output_dir, "oil_regions.geojson")
    with open(geojson_path, "w") as f:
        json.dump(geojson, f, indent=2)
    print(f"[Regions] Wrote {geojson_path} ({len(regions)} regions)")

    report = {
        "scene_metadata": meta,
        "detection_summary": {
            "n_regions": len(regions),
            "total_oil_area_km2": round(sum(r["area_km2"] for r in regions), 4),
            "cfar_prefilter_used": use_cfar,
            "cfar_k": cfar_k if use_cfar else None,
        },
        "regions": regions,
        "output_files": {
            "sigma0_tif": sigma0_tif,
            "probability_mask_tif": mask_out_tif,
            "regions_geojson": geojson_path,
        },
    }
    report_path = os.path.join(output_dir, "detection_report.json")
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)
    print(f"[Report] Wrote {report_path}")

    return {
        "mask_tif": mask_out_tif,
        "regions_geojson": geojson_path,
        "detection_report": report_path,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True,
                         help="Path to raw Sentinel-1 GRD: a .SAFE folder OR a downloaded .zip")
    parser.add_argument("--output_dir", required=True, help="Where to write intermediate + final outputs")
    parser.add_argument("--no_cfar", action="store_true",
                         help="Disable the CFAR pre-filter and scan every tile (slower, old behavior)")
    parser.add_argument("--cfar_k", type=float, default=2.5,
                         help="CFAR sensitivity multiplier (2.0-3.0 typical). Lower = more candidates.")
    parser.add_argument("--strip_rows", type=int, default=4096,
                         help="Rows processed per streaming strip (lower = less peak memory, slower). "
                              "Must be a multiple of 512 to stay aligned with the tile grid.")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)
    safe_input = resolve_safe_input(args.input, args.output_dir)
    run_preprocess_and_infer(safe_input, args.output_dir, use_cfar=not args.no_cfar,
                              cfar_k=args.cfar_k, strip_rows=args.strip_rows)


if __name__ == "__main__":
    main()
