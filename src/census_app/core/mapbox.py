"""Mapbox geocoding and isochrone helpers."""
from __future__ import annotations

from typing import Iterable, Optional

import geopandas as gpd
import requests
from shapely.geometry import shape

from .config import FL_BBOX, MAPBOX_TOKEN, WGS84
from .http_utils import http_get_json


def _feature_is_florida(feat: dict) -> bool:
    """Return True if a Mapbox feature is in Florida (context or bbox)."""
    ctx = feat.get("context", []) or []
    for c in ctx:
        if c.get("id", "").startswith("region.") and c.get("short_code") == "us-fl":
            return True
    try:
        lon, lat = feat["center"]
        return (FL_BBOX[0] - 0.5) <= lon <= (FL_BBOX[2] + 0.5) and (FL_BBOX[1] - 0.5) <= lat <= (FL_BBOX[3] + 0.5)
    except Exception:
        return False


def mapbox_geocode_one(address: str, restrict_to_florida: bool = True) -> Optional[dict]:
    """Geocode a single address and return lon/lat/place_name or None."""
    if not MAPBOX_TOKEN:
        raise RuntimeError("Set your Mapbox token in MAPBOX_TOKEN")
    if not address or not address.strip():
        return None

    url = f"https://api.mapbox.com/geocoding/v5/mapbox.places/{requests.utils.quote(address.strip())}.json"
    params = {
        "access_token": MAPBOX_TOKEN,
        "country": "US",
        "limit": 5,
        "types": "address,place,postcode,poi",
        "autocomplete": "false",
    }

    gj = http_get_json(url, params)
    feats = gj.get("features", []) if isinstance(gj, dict) else []

    if restrict_to_florida:
        fl_feats = [f for f in feats if _feature_is_florida(f)]
        # Pass 2 bounded to FL bbox if needed
        if not fl_feats:
            params2 = dict(params)
            params2["bbox"] = ",".join(map(str, FL_BBOX))
            gj2 = http_get_json(url, params2)
            feats2 = gj2.get("features", []) if isinstance(gj2, dict) else []
            fl_feats = [f for f in feats2 if _feature_is_florida(f)] or feats2
        feats = fl_feats

    if not feats:
        return None

    lon, lat = feats[0]["center"]
    place = feats[0].get("place_name", address)
    return {"lon": float(lon), "lat": float(lat), "place": place}


def mapbox_isochrones(lon: float, lat: float, minutes: Iterable[int] = (5, 10, 15)) -> gpd.GeoDataFrame:
    """Request drive-time isochrones from Mapbox (WGS84)."""
    if not MAPBOX_TOKEN:
        raise RuntimeError("Set your Mapbox token in MAPBOX_TOKEN")

    url = f"https://api.mapbox.com/isochrone/v1/mapbox/driving/{lon},{lat}"
    params = {
        "contours_minutes": ",".join(str(m) for m in minutes),
        "polygons": "true",
        "access_token": MAPBOX_TOKEN,
        "denoise": 1,
    }
    gj = http_get_json(url, params)
    feats = gj.get("features", []) if isinstance(gj, dict) else []

    rows = []
    for f in feats:
        try:
            rows.append({"Time": int(f["properties"]["contour"]), "geometry": shape(f["geometry"])})
        except Exception:
            continue

    if not rows:
        return gpd.GeoDataFrame(columns=["Time", "geometry"], geometry="geometry", crs=WGS84)

    gdf = gpd.GeoDataFrame(rows, geometry="geometry", crs=WGS84)
    try:
        gdf["geometry"] = gdf.geometry.buffer(0)
    except Exception:
        pass

    return gdf.sort_values("Time").reset_index(drop=True)
