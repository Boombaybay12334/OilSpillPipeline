"""
cfar_filter.py
================
Stage-1 pre-filter brick: fast Constant False Alarm Rate (CFAR) style
dark-anomaly detection over the full SAR scene.

WHAT THIS MODULE DOES AND DOES NOT DO (important, keep this honest):
    - It DOES cheaply shortlist regions that are anomalously dark relative
      to their local background -- the same core idea used in real
      operational systems (EMSA CleanSeaNet, the Solberg/Brekke line of
      research) as a fast first pass over a full scene.
    - It does NOT decide whether a candidate is actually oil. CFAR cannot
      tell oil apart from calm water, algae, rain cells, etc -- that
      discrimination is explicitly left to the trained classifier/segmentor
      downstream, exactly like real deployed systems leave it to either a
      human operator or a learned model. Do not add "is it oil" logic here.

This is a bolt-on speed/precision-shortlisting brick: if disabled, the rest
of the pipeline should fall back to scanning every tile (old behavior).

Algorithm: cell-averaging CFAR via an annulus (outer background window minus
inner guard window), implemented with box filters (cv2 or scipy uniform
filters) so it runs in seconds even on a 10000x25000 pixel scene, instead of
a naive per-pixel sliding window loop.
"""

import numpy as np
from scipy.ndimage import uniform_filter, label, find_objects


def _box_mean(arr: np.ndarray, window: int) -> np.ndarray:
    """Fast box-filter mean via scipy uniform_filter (separable, O(N))."""
    return uniform_filter(arr, size=window, mode="reflect")


def compute_local_stats(vv_db: np.ndarray, valid_mask: np.ndarray,
                         background_window: int = 101, guard_window: int = 41):
    """
    Cell-averaging CFAR local mean/std via an annulus:
    background window (large) minus guard window (small, centered on the
    pixel) isolates a ring of "background" pixels around each pixel,
    excluding the pixel's own immediate neighborhood (which might itself be
    part of a real target/slick) from contaminating the background stats.

    Invalid pixels (nodata padding / land, from valid_mask) are excluded
    from the background statistics entirely, not just from the final
    candidate mask -- otherwise a tile near a coastline would have its
    "background" mean dragged toward zero by nearby masked land/padding.

    Returns (local_mean, local_std), same shape as vv_db.
    """
    assert guard_window < background_window, "guard_window must be smaller than background_window"

    valid_f = valid_mask.astype(np.float32)
    vv_masked = np.where(valid_mask, vv_db, 0.0).astype(np.float32)

    # Sums (not means yet) over background and guard windows, so we can
    # subtract guard-window sum from background-window sum to get the
    # annulus-only sum, then divide by the annulus-only valid pixel count.
    bg_sum = _box_mean(vv_masked, background_window) * (background_window ** 2)
    bg_count = _box_mean(valid_f, background_window) * (background_window ** 2)

    guard_sum = _box_mean(vv_masked, guard_window) * (guard_window ** 2)
    guard_count = _box_mean(valid_f, guard_window) * (guard_window ** 2)

    annulus_sum = bg_sum - guard_sum
    annulus_count = np.clip(bg_count - guard_count, 1.0, None)  # avoid div0

    local_mean = annulus_sum / annulus_count

    # Second moment for variance, same annulus-subtraction trick
    vv_sq_masked = np.where(valid_mask, vv_db ** 2, 0.0).astype(np.float32)
    bg_sq_sum = _box_mean(vv_sq_masked, background_window) * (background_window ** 2)
    guard_sq_sum = _box_mean(vv_sq_masked, guard_window) * (guard_window ** 2)
    annulus_sq_sum = bg_sq_sum - guard_sq_sum

    variance = np.clip(annulus_sq_sum / annulus_count - local_mean ** 2, 0.0, None)
    local_std = np.sqrt(variance)

    return local_mean, local_std


def compute_cfar_candidate_mask(vv_db: np.ndarray, valid_mask: np.ndarray,
                                 k: float = 2.5, background_window: int = 101,
                                 guard_window: int = 41) -> np.ndarray:
    """
    T(x,y) = local_mean(x,y) - k * local_std(x,y)
    A pixel is a CFAR candidate if vv_db < T(x,y) AND it's a valid (sea)
    pixel. k in [2.0, 3.0] is the standard literature range -- higher k =
    fewer, more confident candidates (less recall, fewer false positives
    downstream); lower k = more candidates passed on to the classifier.

    HONEST LIMITATION, verified by test (see cfar_filter tests): classic
    cell-averaging CFAR degrades when the real dark anomaly is LARGER than
    the guard window -- the "background" annulus statistics get
    contaminated by the anomaly itself, inflating local_std and hiding the
    real signal. At this pipeline's ~20m/pixel resolution, `guard_window=41`
    covers anomalies up to roughly 800m across before this effect kicks in;
    a slick several km wide will likely only get flagged at its edges, not
    as one coherent blob. This is a genuine, published limitation of
    classic CA-CFAR itself, not a bug specific to this implementation --
    real deployed systems hit the same wall and compensate with either
    much larger adaptive windows, order-statistic (OS-CFAR) variants, or
    (as here) leaning on a downstream model that re-examines the WHOLE
    tile once any part of it is flagged, not just the CFAR-selected pixels
    (see candidate_tile_coords' margin_px). Window sizes here are a
    starting point, not a validated constant -- tune and verify against a
    real labeled scene (e.g. the Sanchi test case) before trusting them,
    the same standard we're holding everyone else's unvalidated numbers to.

    Returns a boolean candidate_mask, same shape as vv_db. This mask is
    intentionally generous (a shortlist) -- the classifier/segmentor make
    the real decision on each candidate, this is not the final answer.
    """
    local_mean, local_std = compute_local_stats(
        vv_db, valid_mask, background_window, guard_window
    )
    threshold = local_mean - k * local_std
    candidate_mask = (vv_db < threshold) & valid_mask
    return candidate_mask


def candidate_tile_coords(candidate_mask: np.ndarray, tile_size: int, stride: int,
                           min_candidate_pixels: int = 50, margin_px: int = 64):
    """
    Converts a pixel-level CFAR candidate mask into a list of (top, left)
    512x512-grid tile coordinates worth sending to the classifier/segmentor,
    instead of scanning every tile in the scene uniformly.

    First runs connected-component labeling on the candidate mask so tiny
    isolated speckle pixels (sensor noise, not real anomalies) don't each
    spawn a candidate tile -- only connected blobs with at least
    `min_candidate_pixels` pixels count. Each surviving blob's bounding box
    is expanded by `margin_px` (so the model sees context around the dark
    spot, not just its exact edge) and then converted into the set of
    tile-grid (top, left) coordinates it overlaps.

    Returns: sorted list of unique (top, left) tuples.
    """
    labeled, n_labels = label(candidate_mask)
    if n_labels == 0:
        return []

    slices = find_objects(labeled)
    h, w = candidate_mask.shape

    tile_coords = set()
    n_kept_blobs = 0

    for lbl_idx, sl in enumerate(slices, start=1):
        if sl is None:
            continue
        blob_pixels = int(np.sum(labeled[sl] == lbl_idx))
        if blob_pixels < min_candidate_pixels:
            continue
        n_kept_blobs += 1

        row_slice, col_slice = sl
        top = max(row_slice.start - margin_px, 0)
        bottom = min(row_slice.stop + margin_px, h)
        left = max(col_slice.start - margin_px, 0)
        right = min(col_slice.stop + margin_px, w)

        # Every tile-grid cell this expanded bbox overlaps
        tile_top_start = (top // stride) * stride
        tile_left_start = (left // stride) * stride
        for t in range(tile_top_start, bottom, stride):
            for l in range(tile_left_start, right, stride):
                if t < h and l < w:
                    tile_coords.add((t, l))

    print(f"[CFAR] {n_labels} raw blobs -> {n_kept_blobs} kept "
          f"(>= {min_candidate_pixels}px) -> {len(tile_coords)} candidate tiles")

    return sorted(tile_coords)
