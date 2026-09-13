"""
quickview.py
=============
Bolt-on rendering brick: turns this pipeline's raw GeoTIFF outputs into
ordinary 8-bit PNGs a human can actually look at, no GIS software or
manual percentile-stretch required.

WHY THIS IS NEEDED (not just a nice-to-have):
    - `sigma0_vv_vh.tif` is LINEAR-scale calibrated Sigma0 backscatter.
      Values span several orders of magnitude (a handful of very bright
      pixels next to a huge range of near-zero ones); opened directly in
      a normal image viewer it renders as almost solid black. It has to
      be converted to dB and percentile-stretched to be visible at all --
      exactly the step `load_sigma0_and_normalize` already does for the
      MODEL's benefit in preprocess_and_infer.py, just redone here purely
      for a human's benefit, independently, so this module never has to
      hold a full-scene array (see `_decimated_read`).
    - `oil_mask_prob.tif` is a float32 probability raster in [0, 1] with
      -1.0 as nodata -- also not directly viewable, and "probability"
      alone doesn't visually communicate "where's the oil" without a
      colormap.

This module produces three PNGs per run:
    - quickview_sar.png      grayscale SAR context (VV, dB, stretched)
    - quickview_mask.png     colorized oil-probability heatmap
    - quickview_overlay.png  SAR grayscale + flagged-oil pixels in red --
                              the fastest single image for "does this
                              detection look right" at a glance

THIS MODULE HAS ONE JOB: raster -> PNG. It never re-derives or modifies
detection results -- it only reads files that already exist on disk
(written by preprocess_and_infer.py) and renders them. Every function
here is safe to skip entirely (see `generate_quickview=False` in
preprocess_and_infer.run_preprocess_and_infer) without affecting
detection in any way.

Reads are DECIMATED at the rasterio level (`out_shape` + averaging
resampling), not "read full array then downsample in numpy" -- for a
24000x27000 scene that distinction is the difference between a
sub-second read and materializing another multi-GB array purely to
throw most of it away. See preprocess_and_infer.py's own streaming
docstring for why full-scene arrays are avoided throughout this
pipeline; this module holds the same line.
"""

import numpy as np
import rasterio
from rasterio.enums import Resampling
from PIL import Image

DEFAULT_MAX_DIM = 2048
NODATA_EPS = 1e-6
DB_CLIP_EPS = 1e-10


def _decimated_read(tif_path: str, band_indexes, max_dim: int = DEFAULT_MAX_DIM) -> np.ndarray:
    """Reads `band_indexes` (1-based, rasterio convention) from `tif_path`
    already downsampled to at most `max_dim` on the long side, via
    rasterio's own windowed/overview-aware decimated read + area-average
    resampling -- never reads the full-resolution array into memory."""
    with rasterio.open(tif_path) as src:
        h, w = src.height, src.width
        scale = min(1.0, max_dim / float(max(h, w)))
        out_h, out_w = max(1, round(h * scale)), max(1, round(w * scale))
        arr = src.read(
            band_indexes, out_shape=(len(band_indexes), out_h, out_w),
            resampling=Resampling.average,
        ).astype(np.float32)
    return arr


def _percentile_stretch_to_u8(arr: np.ndarray, valid: np.ndarray,
                               lo_pct: float = 2.0, hi_pct: float = 98.0) -> np.ndarray:
    """Standard SAR-quicklook percentile stretch: clip to the [lo_pct,
    hi_pct] range of VALID pixels only (so a handful of extreme bright
    targets or the invalid/nodata population don't blow out the stretch),
    then linearly map to 0-255. Invalid pixels are forced to 0 (black)
    regardless of their underlying value."""
    out = np.zeros(arr.shape, dtype=np.uint8)
    vals = arr[valid]
    if vals.size == 0:
        return out
    lo, hi = np.percentile(vals, [lo_pct, hi_pct])
    if hi <= lo:
        hi = lo + 1.0
    stretched = np.clip((arr - lo) / (hi - lo), 0.0, 1.0)
    out = (stretched * 255).astype(np.uint8)
    out[~valid] = 0
    return out


# Cheap piecewise-linear viridis-ish ramp -- a handful of RGB stops
# interpolated by hand, so this module doesn't need matplotlib as a
# dependency just to colorize one probability raster.
_RAMP_STOPS = [
    (0.00, (68, 1, 84)),
    (0.25, (59, 82, 139)),
    (0.50, (33, 145, 140)),
    (0.75, (94, 201, 98)),
    (1.00, (253, 231, 37)),
]


def _colorize(x01: np.ndarray) -> np.ndarray:
    """x01: (H, W) float array in [0, 1] -> (H, W, 3) uint8 RGB."""
    x01 = np.clip(x01, 0.0, 1.0)
    out = np.zeros(x01.shape + (3,), dtype=np.float32)
    for (p0, c0), (p1, c1) in zip(_RAMP_STOPS[:-1], _RAMP_STOPS[1:]):
        seg = (x01 >= p0) & (x01 <= p1)
        if not np.any(seg):
            continue
        span = max(p1 - p0, 1e-6)
        t = (x01[seg] - p0) / span
        for ch in range(3):
            out[..., ch][seg] = c0[ch] + t * (c1[ch] - c0[ch])
    return out.astype(np.uint8)


def _sar_grayscale_u8(sigma0_tif: str, max_dim: int) -> tuple:
    """Shared by generate_sar_quickview and generate_overlay_quickview so
    the two never drift apart on how the base SAR image is rendered.
    Returns (gray_u8, out_shape) -- out_shape lets the caller resample the
    mask onto exactly this grid."""
    vv_linear = _decimated_read(sigma0_tif, [1], max_dim=max_dim)[0]
    valid = vv_linear > NODATA_EPS
    db = 10.0 * np.log10(np.clip(vv_linear, DB_CLIP_EPS, None))
    gray_u8 = _percentile_stretch_to_u8(db, valid)
    return gray_u8, gray_u8.shape


def generate_sar_quickview(sigma0_tif: str, out_png: str, max_dim: int = DEFAULT_MAX_DIM) -> str:
    """Grayscale VV-band quicklook (dB, percentile-stretched). Useful on
    its own to sanity-check a scene (does it look like open water? is the
    swath mostly land/nodata?) independent of anything the model decided."""
    gray_u8, _ = _sar_grayscale_u8(sigma0_tif, max_dim)
    Image.fromarray(gray_u8, mode="L").save(out_png)
    return out_png


def generate_mask_quickview(mask_tif: str, out_png: str, max_dim: int = DEFAULT_MAX_DIM) -> str:
    """Colorized oil-probability heatmap (viridis-ish ramp). nodata
    (written as -1.0 by preprocess_and_infer.py) renders as solid black,
    matching the SAR quickview's treatment of invalid pixels."""
    prob = _decimated_read(mask_tif, [1], max_dim=max_dim)[0]
    valid = prob >= 0.0
    rgb = _colorize(np.where(valid, prob, 0.0))
    rgb[~valid] = (0, 0, 0)
    Image.fromarray(rgb, mode="RGB").save(out_png)
    return out_png


def generate_overlay_quickview(sigma0_tif: str, mask_tif: str, out_png: str,
                                threshold: float = 0.5, max_dim: int = DEFAULT_MAX_DIM) -> str:
    """SAR grayscale base with flagged-oil pixels (probability >=
    `threshold`) painted solid red on top -- the single most useful image
    for eyeballing "does this detection make sense" without opening a GIS
    tool. `threshold` should match the pipeline's SEG_THRESHOLD (the same
    cutoff the binary mask used for region extraction) so this picture
    agrees with the actual reported regions."""
    gray_u8, out_shape = _sar_grayscale_u8(sigma0_tif, max_dim)
    rgb = np.stack([gray_u8] * 3, axis=-1)

    with rasterio.open(mask_tif) as src:
        prob = src.read(1, out_shape=out_shape, resampling=Resampling.nearest)

    flagged = prob >= threshold
    rgb[flagged] = (220, 30, 30)
    Image.fromarray(rgb, mode="RGB").save(out_png)
    return out_png


def generate_all_quickviews(sigma0_tif: str, mask_tif: str, out_dir: str,
                             threshold: float = 0.5, max_dim: int = DEFAULT_MAX_DIM) -> dict:
    """Convenience wrapper: generates all three quickviews into `out_dir`
    using the pipeline's standard filenames. Returns a dict of the three
    paths -- this is what preprocess_and_infer.py calls."""
    import os
    return {
        "quickview_sar_png": generate_sar_quickview(
            sigma0_tif, os.path.join(out_dir, "quickview_sar.png"), max_dim=max_dim),
        "quickview_mask_png": generate_mask_quickview(
            mask_tif, os.path.join(out_dir, "quickview_mask.png"), max_dim=max_dim),
        "quickview_overlay_png": generate_overlay_quickview(
            sigma0_tif, mask_tif, os.path.join(out_dir, "quickview_overlay.png"),
            threshold=threshold, max_dim=max_dim),
    }
