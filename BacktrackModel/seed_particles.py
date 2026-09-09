"""
seed_particles.py
===================
Stage-2, Brick 4: convert an Observation (from prepare_observation.py) into
a flat list of seed particle positions for OpenDrift.

Rules:
  - Polygon features: PARTICLES_PER_FEATURE points sampled UNIFORMLY inside
    the polygon (rejection sampling against its bounding box).
  - Point-like features (degenerate detections that came through as a
    GeoJSON Point): PARTICLES_PER_POINT_FEATURE points sampled in a small
    disk of radius POINT_FEATURE_RADIUS_M around the point.
  - Every seed point carries back its source region_id and whether it came
    from a polygon or a point.

Depends on: pip install shapely pyproj
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

import stage2_config as cfg
from prepare_observation import Observation, load_observation

try:
    from shapely.geometry import Point, Polygon, MultiPolygon
    import pyproj
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "shapely and pyproj are required for seed_particles.py.\n"
        "Install with: pip install shapely pyproj"
    ) from exc


@dataclass
class SeedPoint:
    lon: float
    lat: float
    region_id: object
    source_type: str  # "polygon" or "point"


def _shapely_polygon(geometry: dict) -> Polygon | MultiPolygon | None:
    gtype = geometry.get("type")
    coords = geometry.get("coordinates")
    if gtype == "Polygon":
        try:
            return Polygon(coords[0], coords[1:]) if coords else None
        except Exception:
            return None
    if gtype == "MultiPolygon":
        try:
            polys = [Polygon(p[0], p[1:]) for p in coords if p]
            return MultiPolygon(polys) if polys else None
        except Exception:
            return None
    return None


def _sample_uniform_in_polygon(poly: Polygon | MultiPolygon, n: int,
                                max_attempts_factor: int = 50) -> list[tuple[float, float]]:
    minx, miny, maxx, maxy = poly.bounds
    points: list[tuple[float, float]] = []
    attempts = 0
    max_attempts = max(n * max_attempts_factor, 200)

    while len(points) < n and attempts < max_attempts:
        x = random.uniform(minx, maxx)
        y = random.uniform(miny, maxy)
        attempts += 1
        if poly.contains(Point(x, y)):
            points.append((x, y))

    if not points:
        c = poly.centroid
        points = [(c.x, c.y)] * n

    while len(points) < n:
        points.append(points[len(points) % max(1, len(points))])

    return points[:n]


def _sample_disk_around_point(lon: float, lat: float, n: int, radius_m: float) -> list[tuple[float, float]]:
    proj_local = pyproj.CRS.from_proj4(
        f"+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m"
    )
    to_wgs84 = pyproj.Transformer.from_crs(proj_local, "EPSG:4326", always_xy=True)

    points = []
    for _ in range(n):
        r = radius_m * math.sqrt(random.random())
        theta = random.uniform(0.0, 2.0 * math.pi)
        x = r * math.cos(theta)
        y = r * math.sin(theta)
        lon_out, lat_out = to_wgs84.transform(x, y)
        points.append((lon_out, lat_out))
    return points


def build_seed_points(observation: Observation) -> list[SeedPoint]:
    seeds: list[SeedPoint] = []

    for feature in observation.features:
        if feature.is_point_like:
            samples = _sample_disk_around_point(
                feature.centroid_lon, feature.centroid_lat,
                cfg.PARTICLES_PER_POINT_FEATURE, cfg.POINT_FEATURE_RADIUS_M,
            )
            source_type = "point"
        else:
            poly = _shapely_polygon(feature.geometry)
            if poly is None or poly.is_empty or poly.area == 0:
                samples = [(feature.centroid_lon, feature.centroid_lat)] * cfg.PARTICLES_PER_FEATURE
            else:
                samples = _sample_uniform_in_polygon(poly, cfg.PARTICLES_PER_FEATURE)
            source_type = "polygon"

        for lon, lat in samples:
            seeds.append(SeedPoint(lon=lon, lat=lat, region_id=feature.region_id, source_type=source_type))

    return seeds


def main() -> None:
    random.seed(cfg.SEED_RNG)
    obs = load_observation()
    seeds = build_seed_points(obs)

    n_polygon_seeds = sum(1 for s in seeds if s.source_type == "polygon")
    n_point_seeds = sum(1 for s in seeds if s.source_type == "point")

    print(f"Event:               {obs.event_id}")
    print(f"Observed features:   {len(obs.features)}")
    print(f"Total seed points:   {len(seeds)}")
    print(f"  from polygons:     {n_polygon_seeds}")
    print(f"  from point-like:   {n_point_seeds}")
    print(f"Seed lon range:      {min(s.lon for s in seeds):.4f} to {max(s.lon for s in seeds):.4f}")
    print(f"Seed lat range:      {min(s.lat for s in seeds):.4f} to {max(s.lat for s in seeds):.4f}")


if __name__ == "__main__":
    main()
