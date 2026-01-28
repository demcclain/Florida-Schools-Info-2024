"""Overture Maps API client for querying Florida map data.

This module provides functions to query Overture Maps GeoParquet data directly
from S3 using DuckDB's httpfs/s3 extension. No local downloads required.

Overture data themes:
- addresses: Address points
- base: Land use, water, infrastructure
- buildings: Building footprints
- divisions: Administrative boundaries
- places: Points of interest (POIs)
- transportation: Roads, paths, etc.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, Tuple

try:
    import duckdb
except ImportError:
    raise ImportError("DuckDB is required. Install with: pip install duckdb")

# Overture release and S3 paths
OVERTURE_RELEASE = "2026-01-21.0"
OVERTURE_S3_BASE = f"s3://overturemaps-us-west-2/release/{OVERTURE_RELEASE}"

# Florida bounding box (xmin, ymin, xmax, ymax)
FLORIDA_BBOX = (-87.634939, 24.396308, -80.031362, 31.000968)

# Available Overture themes and types
OVERTURE_THEMES = {
    "addresses": ["address"],
    "base": ["infrastructure", "land", "land_cover", "land_use", "water"],
    "buildings": ["building"],
    "divisions": ["division", "division_area", "division_boundary"],
    "places": ["place"],
    "transportation": ["connector", "segment"],
}


def _get_connection() -> duckdb.DuckDBPyConnection:
    """Get a DuckDB connection configured for S3 access."""
    con = duckdb.connect(":memory:")

    # Install and load required extensions
    con.execute("INSTALL httpfs")
    con.execute("LOAD httpfs")
    con.execute("INSTALL spatial")
    con.execute("LOAD spatial")

    # Configure S3 for anonymous access
    con.execute("SET s3_region='us-west-2'")
    con.execute("SET s3_access_key_id=''")
    con.execute("SET s3_secret_access_key=''")

    return con


def _build_overture_path(theme: str, ftype: str) -> str:
    """Build the S3 path for an Overture theme/type."""
    return f"{OVERTURE_S3_BASE}/theme={theme}/type={ftype}/*.parquet"


def query_overture_bbox(
    theme: str,
    ftype: str,
    bbox: Tuple[float, float, float, float],
    columns: Optional[List[str]] = None,
    limit: Optional[int] = None,
    where_extra: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Query Overture data within a bounding box.

    Args:
        theme: Overture theme (e.g., 'buildings', 'places')
        ftype: Feature type within theme (e.g., 'building', 'place')
        bbox: Bounding box as (xmin, ymin, xmax, ymax)
        columns: List of columns to select (default: all)
        limit: Maximum number of features to return (None = no limit)
        where_extra: Additional WHERE clause conditions

    Returns:
        List of feature dictionaries with 'geometry' as GeoJSON
    """
    con = _get_connection()

    path = _build_overture_path(theme, ftype)
    xmin, ymin, xmax, ymax = bbox

    # Build column selection
    if columns:
        # Always include geometry
        if "geometry" not in columns:
            columns = list(columns) + ["geometry"]
        col_str = ", ".join(columns)
    else:
        col_str = "*"

    # Build WHERE clause using bbox columns (Overture parquet has bbox.xmin, etc.)
    where_parts = [
        f"bbox.xmin <= {xmax}",
        f"bbox.xmax >= {xmin}",
        f"bbox.ymin <= {ymax}",
        f"bbox.ymax >= {ymin}",
    ]

    if where_extra:
        where_parts.append(f"({where_extra})")

    where_clause = " AND ".join(where_parts)

    # Build LIMIT clause only if limit is specified
    limit_clause = f"LIMIT {limit}" if limit else ""

    # Query with geometry conversion to GeoJSON
    query = f"""
        SELECT {col_str},
               ST_AsGeoJSON(geometry) as geojson
        FROM read_parquet('{path}', filename=true, hive_partitioning=1)
        WHERE {where_clause}
        {limit_clause}
    """

    try:
        result = con.execute(query).fetchall()
        columns_out = [desc[0] for desc in con.description]

        features = []
        for row in result:
            feature = {}
            geojson_str = None
            for i, col in enumerate(columns_out):
                if col == "geojson":
                    geojson_str = row[i]
                elif col != "geometry":  # Skip raw geometry blob
                    val = row[i]
                    # Convert DuckDB structs/maps to Python dicts
                    if hasattr(val, "__iter__") and not isinstance(val, (str, bytes)):
                        try:
                            val = dict(val) if hasattr(val, "items") else list(val)
                        except Exception:
                            val = str(val)
                    feature[col] = val

            if geojson_str:
                feature["geometry"] = json.loads(geojson_str)

            features.append(feature)

        return features

    except Exception as e:
        # If S3/httpfs not available, return empty with error info
        return [{"error": str(e)}]
    finally:
        con.close()


def get_buildings(
    bbox: Tuple[float, float, float, float],
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Get building footprints within a bounding box.

    Args:
        bbox: Bounding box as (xmin, ymin, xmax, ymax)
        limit: Maximum buildings to return (None = no limit)

    Returns:
        List of building features with geometry and properties
    """
    columns = ["id", "names", "height", "num_floors", "class", "subtype"]
    return query_overture_bbox("buildings", "building", bbox, columns=columns, limit=limit)


def get_places(
    bbox: Tuple[float, float, float, float],
    categories: Optional[List[str]] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Get points of interest (places) within a bounding box.

    Args:
        bbox: Bounding box as (xmin, ymin, xmax, ymax)
        categories: Optional list of category filters
        limit: Maximum places to return (None = no limit)

    Returns:
        List of place features with geometry and properties
    """
    columns = ["id", "names", "categories", "confidence", "websites", "phones", "addresses"]

    where_extra = None
    if categories:
        cat_list = ", ".join([f"'{c}'" for c in categories])
        where_extra = f"list_has_any(categories.primary, [{cat_list}])"

    return query_overture_bbox("places", "place", bbox, columns=columns, limit=limit, where_extra=where_extra)


def get_roads(
    bbox: Tuple[float, float, float, float],
    road_classes: Optional[List[str]] = None,
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Get road segments within a bounding box.

    Args:
        bbox: Bounding box as (xmin, ymin, xmax, ymax)
        road_classes: Optional list of road class filters (e.g., ['primary', 'secondary'])
        limit: Maximum segments to return (None = no limit)

    Returns:
        List of road segment features
    """
    columns = ["id", "names", "class", "subclass", "surface", "speed_limits"]

    where_extra = None
    if road_classes:
        class_list = ", ".join([f"'{c}'" for c in road_classes])
        where_extra = f"class IN ({class_list})"

    return query_overture_bbox("transportation", "segment", bbox, columns=columns, limit=limit, where_extra=where_extra)


def get_infrastructure(
    bbox: Tuple[float, float, float, float],
    limit: int = 500,
) -> List[Dict[str, Any]]:
    """Get infrastructure features within a bounding box.

    Args:
        bbox: Bounding box as (xmin, ymin, xmax, ymax)
        limit: Maximum features to return

    Returns:
        List of infrastructure features
    """
    columns = ["id", "names", "class", "subtype"]
    return query_overture_bbox("base", "infrastructure", bbox, columns=columns, limit=limit)


def get_addresses(
    bbox: Tuple[float, float, float, float],
    limit: int = 1000,
) -> List[Dict[str, Any]]:
    """Get address points within a bounding box.

    Args:
        bbox: Bounding box as (xmin, ymin, xmax, ymax)
        limit: Maximum addresses to return

    Returns:
        List of address features
    """
    columns = ["id", "number", "street", "unit", "postcode"]
    return query_overture_bbox("addresses", "address", bbox, columns=columns, limit=limit)


def features_to_geojson(features: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Convert a list of features to a GeoJSON FeatureCollection.

    Args:
        features: List of feature dicts with 'geometry' key

    Returns:
        GeoJSON FeatureCollection dict
    """
    geojson_features = []

    for f in features:
        if "error" in f:
            continue

        geom = f.pop("geometry", None)
        if geom is None:
            continue

        geojson_features.append({
            "type": "Feature",
            "geometry": geom,
            "properties": f,
        })

    return {
        "type": "FeatureCollection",
        "features": geojson_features,
    }


def bbox_from_center(lon: float, lat: float, radius_km: float = 2.0) -> Tuple[float, float, float, float]:
    """Create a bounding box around a center point.

    Args:
        lon: Center longitude
        lat: Center latitude
        radius_km: Approximate radius in kilometers

    Returns:
        Bounding box as (xmin, ymin, xmax, ymax)
    """
    # Approximate degrees per km at given latitude
    km_per_deg_lat = 111.0
    km_per_deg_lon = 111.0 * abs(cos_deg(lat))

    delta_lat = radius_km / km_per_deg_lat
    delta_lon = radius_km / km_per_deg_lon if km_per_deg_lon > 0 else radius_km / 111.0

    return (
        lon - delta_lon,
        lat - delta_lat,
        lon + delta_lon,
        lat + delta_lat,
    )


def cos_deg(degrees: float) -> float:
    """Cosine of angle in degrees."""
    import math
    return math.cos(math.radians(degrees))
