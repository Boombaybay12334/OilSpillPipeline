"""
region_extraction.py
======================
Stage-3 output brick: turns the classifier+segmentor's pixel probability
mask into a list of discrete, georeferenced oil-spill regions -- the actual
handoff object for a future backtrack-to-origin model.

Each region carries:
    - a polygon outline in (lon, lat), simplified to a reasonable point count
    - a centroid in (lon, lat)
    - an approximate area (km^2)
    - shape descriptors (elongation ratio, circularity) -- the same
      morphological features used for lookalike screening in real systems,
      reported here for whoever consumes this output downstream, not used
      internally to reject anything (this module never says "not oil" --
      that call already happened in the segmentor; this module only
      describes shape, it doesn't gatekeep)
    - mean/max detected probability within the region
    - pixel bounding box (for re-locating the region in the source raster)

This module has ONE job: pixel mask -> structured georeferenced regions.
It doesn't know about SNAP, CFAR, or the models. Keep it that way so it can
be swapped or extended independently (e.g. add a "physical extent in
current-drift-compatible format" method later) without touching detection
code.
"""

import numpy as np
import rasterio
from rasterio.windows import Window
from skimage.measure import label, regionprops, find_contours, approximate_polygon


EARTH_RADIUS_KM = 6371.0088


def _pixel_area_km2(transform, lat_deg: float) -> float:
    """
    Approximate area of one pixel in km^2, given an affine transform and
    the latitude at which to evaluate it (pixel area in degrees varies
    with latitude for a geographic CRS -- longitude degrees shrink toward
    the poles, latitude degrees are ~constant).

    Assumes a geographic (lon/lat degrees) transform, matching this
    pipeline's SNAP graph output (mapProjection=WGS84(DD)). If the CRS
    were ever changed to a projected one (meters), this function would
    need updating -- it is NOT CRS-agnostic as written.
    """
    px_width_deg = abs(transform.a)
    px_height_deg = abs(transform.e)

    km_per_deg_lat = (np.pi / 180.0) * EARTH_RADIUS_KM
    km_per_deg_lon = km_per_deg_lat * np.cos(np.radians(lat_deg))

    return (px_width_deg * km_per_deg_lon) * (px_height_deg * km_per_deg_lat)


def extract_oil_regions(binary_mask: np.ndarray, prob_source, transform, crs,
                         min_region_px: int = 20, max_polygon_points: int = 60):
    """
    binary_mask: (H,W) uint8/bool, thresholded final oil mask (already
        excludes nodata/land -- see preprocess_and_infer.py's valid_mask).
    prob_source: EITHER an (H,W) float32 ndarray (whole probability map in
        memory) OR a string path to the probability GeoTIFF. If a path is
        given, this function does small per-region windowed reads instead
        of ever holding a full-scene float32 array -- for a large scene
        (e.g. 24000x27000), that array alone would be 2.5GB+, exactly the
        kind of allocation this pipeline had to eliminate elsewhere (see
        preprocess_and_infer.py's strip-based streaming). Prefer passing a
        path on any real-sized scene.
    transform: rasterio Affine transform of the source raster (same one
        the mask GeoTIFF was written with).
    crs: rasterio CRS of the source raster. This function assumes it's
        geographic (lon/lat degrees) -- true for this pipeline's SNAP
        output (WGS84(DD)). Raises if given something else, rather than
        silently producing wrong areas/coordinates.

    IMPORTANT (also a fixed memory bug, not just a style note): earlier
    versions computed `blob_mask = (labeled == prop.label)` and ran
    `find_contours` on that FULL-SCENE array for every single region --
    each call materialized another full-scene float32 array. On a large
    scene with even a handful of detected regions, that alone could OOM
    again after the main inference loop already succeeded. Everything
    below is restricted to each region's small bounding box instead.

    Returns a list of region dicts, one per connected blob of oil pixels.
    """
    if crs is not None and not crs.is_geographic:
        raise ValueError(
            f"extract_oil_regions assumes a geographic CRS (lon/lat degrees), "
            f"got {crs}. If the SNAP graph's mapProjection is changed away "
            f"from WGS84(DD), this function's area/coordinate math must be "
            f"updated to reproject first."
        )

    labeled = label(binary_mask.astype(np.uint8), connectivity=2)
    props = regionprops(labeled)

    prob_is_path = isinstance(prob_source, str)
    prob_ds = rasterio.open(prob_source) if prob_is_path else None

    regions = []
    try:
        for i, prop in enumerate(props):
            if prop.area < min_region_px:
                continue

            # --- centroid, in map (lon, lat) coords ---
            row_c, col_c = prop.centroid
            lon_c, lat_c = transform * (col_c, row_c)

            # --- bounding box, pixel space, for re-locating in the raster ---
            min_row, min_col, max_row, max_col = prop.bbox
            bbox_h, bbox_w = max_row - min_row, max_col - min_col

            # --- shape descriptors (skimage computes these from bbox-local
            # data internally already, no full-scene array needed here) ---
            major = prop.major_axis_length
            minor = prop.minor_axis_length
            elongation_ratio = float(major / minor) if minor > 0 else float("inf")

            perimeter = prop.perimeter if prop.perimeter > 0 else 1.0
            circularity = float(4 * np.pi * prop.area / (perimeter ** 2))

            # --- polygon outline, simplified, in (lon, lat) -- BBOX-LOCAL ---
            local_labeled = labeled[min_row:max_row, min_col:max_col]
            local_blob_mask = (local_labeled == prop.label)

            contours = find_contours(local_blob_mask.astype(np.float32), level=0.5)
            polygon_lonlat = []
            if contours:
                # find_contours can return multiple contours (e.g. holes) --
                # take the longest, which is the outer boundary
                contour = max(contours, key=len)
                simplified = approximate_polygon(contour, tolerance=1.5)
                if len(simplified) > max_polygon_points:
                    idx = np.linspace(0, len(simplified) - 1, max_polygon_points).astype(int)
                    simplified = simplified[idx]
                for row, col in simplified:
                    # contour coords are LOCAL to the bbox -- add the offset
                    # back before converting to map coordinates
                    global_row, global_col = row + min_row, col + min_col
                    lon, lat = transform * (global_col, global_row)
                    polygon_lonlat.append([float(lon), float(lat)])

            # --- probability stats within this region, bbox-local read ---
            if prob_is_path:
                window = Window(col_off=min_col, row_off=min_row, width=bbox_w, height=bbox_h)
                local_prob = prob_ds.read(1, window=window)
            else:
                local_prob = prob_source[min_row:max_row, min_col:max_col]
            region_probs = local_prob[local_blob_mask]
            mean_prob = float(region_probs.mean()) if region_probs.size else 0.0
            max_prob = float(region_probs.max()) if region_probs.size else 0.0

            area_km2 = float(prop.area * _pixel_area_km2(transform, lat_c))

            regions.append({
                "region_id": i,
                "centroid_lon": float(lon_c),
                "centroid_lat": float(lat_c),
                "area_px": int(prop.area),
                "area_km2": round(area_km2, 4),
                "elongation_ratio": round(elongation_ratio, 3),
                "circularity": round(circularity, 3),
                "mean_probability": round(mean_prob, 4),
                "max_probability": round(max_prob, 4),
                "pixel_bbox": {
                    "min_row": int(min_row), "min_col": int(min_col),
                    "max_row": int(max_row), "max_col": int(max_col),
                },
                "polygon_lonlat": polygon_lonlat,
            })
    finally:
        if prob_ds is not None:
            prob_ds.close()

    regions.sort(key=lambda r: r["area_km2"], reverse=True)
    print(f"[Regions] {len(props)} raw blobs -> {len(regions)} kept "
          f"(>= {min_region_px}px)")
    return regions


def regions_to_geojson(regions: list, scene_metadata: dict | None = None) -> dict:
    """
    Wraps region dicts into a standard GeoJSON FeatureCollection, so any
    downstream tool (GIS software, a future drift-backtracking model, a
    map viewer) can consume it without needing to know this pipeline's
    internal region-dict shape.
    """
    features = []
    for r in regions:
        if len(r["polygon_lonlat"]) >= 3:
            # GeoJSON polygons must be closed (first point == last point)
            coords = r["polygon_lonlat"]
            if coords[0] != coords[-1]:
                coords = coords + [coords[0]]
            geometry = {"type": "Polygon", "coordinates": [coords]}
        else:
            # Degenerate/too-small region: fall back to a point geometry
            geometry = {"type": "Point", "coordinates": [r["centroid_lon"], r["centroid_lat"]]}

        properties = {k: v for k, v in r.items() if k != "polygon_lonlat"}
        features.append({"type": "Feature", "geometry": geometry, "properties": properties})

    geojson = {"type": "FeatureCollection", "features": features}
    if scene_metadata:
        geojson["metadata"] = scene_metadata
    return geojson
