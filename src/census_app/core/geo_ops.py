"""Geospatial operations and weighted aggregations."""
from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np
import geopandas as gpd
from shapely.geometry.base import BaseGeometry

from .config import ACS_YEAR, WGS84
from .geo_data import get_tracts_fl


def safe_buffer0(geom: BaseGeometry) -> BaseGeometry:
    """Repair invalid geometries with a 0-distance buffer when possible."""
    try:
        return geom.buffer(0)
    except Exception:
        return geom


def counties_touching(poly_wgs84: BaseGeometry) -> List[str]:
    """Determine county FIPS touched by a polygon using existing tracts."""
    tr_wgs = get_tracts_fl(ACS_YEAR)

    # spatial index prefilter
    try:
        idx = tr_wgs.sindex
        cand_idx = list(idx.query(poly_wgs84, predicate="intersects"))
        cand = tr_wgs.iloc[cand_idx]
    except Exception:
        minx, miny, maxx, maxy = poly_wgs84.bounds
        cand = tr_wgs.cx[minx:maxx, miny:maxy]

    if cand.empty:
        return []

    try:
        inter = gpd.sjoin(
            gpd.GeoDataFrame(geometry=[poly_wgs84], crs=WGS84),
            cand[["GEOID", "geometry"]],
            how="inner",
            predicate="intersects",
        )
        if inter.empty:
            return []
        hit_idx = inter["index_right"].unique()
        hit = cand.iloc[hit_idx]
    except Exception:
        hit = cand

    # county FIPS = chars 3–5 of tract GEOID
    return sorted(hit["GEOID"].astype(str).str.slice(2, 5).unique().tolist())


def weighted_est_and_moe(df: gpd.GeoDataFrame) -> Tuple[Optional[float], Optional[float]]:
    """Weighted mean estimate and approximate 90% MOE."""
    w = df["weight"].to_numpy(dtype="float64")
    y = df["estimate"].to_numpy(dtype="float64")
    m = df["moe"].to_numpy(dtype="float64")

    mask = np.isfinite(w) & (w > 0) & np.isfinite(y)
    if not mask.any():
        return None, None

    w, y, m = w[mask], y[mask], m[mask]
    wsum = w.sum()
    est = float((w * y).sum() / wsum)

    # SE from MOE90: SE = MOE / 1.645; combine for weighted mean; back to MOE90
    se = np.where(np.isfinite(m), m / 1.645, np.nan)
    valid = np.isfinite(se)
    se_comb = np.sqrt(((w[valid] * se[valid]) ** 2).sum()) / wsum if valid.any() else np.nan
    moe90 = float(se_comb * 1.645) if np.isfinite(se_comb) else None

    if est < 0 and abs(est) < 1e-6:
        est = 0.0
    return est, moe90


def weighted_share(df: gpd.GeoDataFrame, col: str) -> Optional[float]:
    """Weighted mean of a % column (0-100) using 'weight'."""
    if col not in df or "weight" not in df:
        return None
    w = df["weight"].to_numpy(dtype="float64")
    x = df[col].to_numpy(dtype="float64")
    mask = np.isfinite(w) & (w > 0) & np.isfinite(x)
    if not mask.any():
        return None
    w, x = w[mask], x[mask]
    return float((w * x).sum() / w.sum())
