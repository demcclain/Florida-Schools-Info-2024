"""Flask routes for Overture Maps data.

This module provides API endpoints for querying Overture Maps data
(buildings, places, roads, etc.) within a bounding box or around a point.
"""
from __future__ import annotations

from flask import Blueprint, jsonify, request
from shapely.geometry import mapping as shapely_mapping
from shapely.geometry import shape
from shapely.ops import unary_union

from census_app.core.mapbox import mapbox_isochrones
from census_app.core.overture import (
    bbox_from_center,
    features_to_geojson,
    get_addresses,
    get_buildings,
    get_places,
    OVERTURE_THEMES,
)

# Create Blueprint for Overture routes
overture_bp = Blueprint("overture", __name__, url_prefix="/api/overture")


@overture_bp.route("/themes", methods=["GET"])
def list_themes():
    """List available Overture themes and types."""
    return jsonify({"themes": OVERTURE_THEMES})


@overture_bp.route("/buildings", methods=["POST"])
def api_buildings():
    """Get building footprints within a bounding box or around a point.

    Request JSON:
        - bbox: [xmin, ymin, xmax, ymax] (optional if lon/lat provided)
        - lon, lat: Center point (optional if bbox provided)
        - radius_km: Radius in km for point-based query (default: 1.0)
        - limit: Max features to return (optional, no limit if not provided)
    """
    data = request.get_json() or {}

    bbox = _get_bbox(data)
    if bbox is None:
        return jsonify({"error": "Provide bbox or lon/lat"}), 400

    limit = data.get("limit")  # None means no limit

    try:
        features = get_buildings(bbox, limit=limit)
        iso_geom = _get_isochrone_geometry(data)
        if iso_geom is not None:
            features = _clip_features_to_isochrone(features, iso_geom)
        if features and "error" in features[0]:
            return jsonify({"error": features[0]["error"]}), 500
        return jsonify(features_to_geojson(features))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@overture_bp.route("/places", methods=["POST"])
def api_places():
    """Get points of interest within a bounding box or around a point.

    Request JSON:
        - bbox: [xmin, ymin, xmax, ymax] (optional if lon/lat provided)
        - lon, lat: Center point (optional if bbox provided)
        - radius_km: Radius in km for point-based query (default: 2.0)
        - categories: List of category filters (optional)
        - limit: Max features to return (optional, no limit if not provided)
    """
    data = request.get_json() or {}

    bbox = _get_bbox(data, default_radius=2.0)
    if bbox is None:
        return jsonify({"error": "Provide bbox or lon/lat"}), 400

    limit = data.get("limit")  # None means no limit
    categories = data.get("categories")

    try:
        features = get_places(bbox, categories=categories, limit=limit)
        iso_geom = _get_isochrone_geometry(data)
        if iso_geom is not None:
            features = _clip_features_to_isochrone(features, iso_geom)
        if features and "error" in features[0]:
            return jsonify({"error": features[0]["error"]}), 500
        return jsonify(features_to_geojson(features))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# roads endpoint removed — roads are not displayed


@overture_bp.route("/addresses", methods=["POST"])
def api_addresses():
    """Get address points within a bounding box or around a point.

    Request JSON:
        - bbox: [xmin, ymin, xmax, ymax] (optional if lon/lat provided)
        - lon, lat: Center point (optional if bbox provided)
        - radius_km: Radius in km for point-based query (default: 1.0)
        - limit: Max features to return (default: 1000)
    """
    data = request.get_json() or {}

    bbox = _get_bbox(data, default_radius=1.0)
    if bbox is None:
        return jsonify({"error": "Provide bbox or lon/lat"}), 400

    limit = data.get("limit", 1000)

    try:
        features = get_addresses(bbox, limit=limit)
        if features and "error" in features[0]:
            return jsonify({"error": features[0]["error"]}), 500
        return jsonify(features_to_geojson(features))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _get_bbox(data: dict, default_radius: float = 1.0):
    """Extract bounding box from request data.

    Supports either explicit bbox or lon/lat + radius_km.
    """
    if "bbox" in data:
        bbox = data["bbox"]
        if isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            return tuple(float(x) for x in bbox)

    lon = data.get("lon")
    lat = data.get("lat")

    if lon is not None and lat is not None:
        radius = data.get("radius_km", default_radius)
        return bbox_from_center(float(lon), float(lat), float(radius))

    return None


def _get_isochrone_geometry(data: dict):
    """Get a unified isochrone polygon geometry from request data.

    Prefers provided GeoJSON (isochrones) to avoid re-calling Mapbox.
    Falls back to calling Mapbox if lon/lat are provided.
    Returns a shapely geometry or None.
    """
    isochrones = data.get("isochrones")
    if isinstance(isochrones, dict):
        features = isochrones.get("features") or []
        if features:
            times = [
                f.get("properties", {}).get("Time")
                for f in features
                if isinstance(f, dict)
            ]
            max_time = max([t for t in times if isinstance(t, (int, float))], default=None)
            if max_time is not None:
                features = [f for f in features if f.get("properties", {}).get("Time") == max_time]
            geoms = [shape(f["geometry"]) for f in features if f.get("geometry")]
            if geoms:
                try:
                    return unary_union(geoms).buffer(0)
                except Exception:
                    return unary_union(geoms)

    lon = data.get("lon")
    lat = data.get("lat")
    if lon is None or lat is None:
        return None

    try:
        gdf = mapbox_isochrones(float(lon), float(lat), minutes=(5, 10, 15))
        if gdf.empty:
            return None
        max_time = gdf["Time"].max()
        geoms = gdf[gdf["Time"] == max_time].geometry.tolist()
        if not geoms:
            return None
        try:
            return unary_union(geoms).buffer(0)
        except Exception:
            return unary_union(geoms)
    except Exception:
        return None


def _clip_features_to_isochrone(features, iso_geom):
    """Clip Overture features to an isochrone polygon geometry."""
    if not iso_geom:
        return features

    clipped = []
    for f in features:
        if "error" in f:
            clipped.append(f)
            continue

        geom_json = f.get("geometry")
        if not geom_json:
            continue

        try:
            geom = shape(geom_json)
            if geom.is_empty:
                continue

            if not iso_geom.intersects(geom):
                continue

            clipped_geom = geom.intersection(iso_geom)
            if clipped_geom.is_empty:
                continue

            f["geometry"] = shapely_mapping(clipped_geom)
            clipped.append(f)
        except Exception:
            # If clipping fails, skip the feature to avoid leaking outside geometry
            continue

    return clipped
