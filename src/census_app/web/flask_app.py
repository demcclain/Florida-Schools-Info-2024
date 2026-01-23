"""Flask application for Census School Data."""
from __future__ import annotations

import os
from typing import Optional

import geopandas as gpd
import numpy as np
import pandas as pd
import polars as pl
import io
import re
from flask import Flask, jsonify, render_template, request, send_file
from shapely.geometry import mapping as shapely_mapping

from census_app.core import (
    ACS_YEAR,
    AREA_CRS,
    WGS84,
    fmt_int,
    fmt_money,
    fmt_pct,
    get_blocks_for_counties,
    get_tracts_table,
    get_tracts_with_acs,
    mapbox_geocode_one,
    mapbox_isochrones,
    weighted_est_and_moe,
    weighted_share,
    counties_touching,
    safe_buffer0,
)
from .school_data import combine

# Initialize Flask app
app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), "templates"),
    static_folder=os.path.join(os.path.dirname(__file__), "static"),
)

# School address mapping
DISPLAY_TO_ADDRESS = {
    "South (Kendall)": "10700 SW 56 Street, Miami, FL 33165",
    "Village Green Elementary (Kendall)": "13300 SW 120 Street, Miami, FL 33186",
    "Village Green Middle-High (Kendall)": "13300 SW 120 Street, Miami, FL 33186",
    "Doral Elementary": "3500 NW 89th Ct, Doral, FL 33172",
    "Doral Middle-High": "3500 NW 89th Ct, Doral, FL 33172",
    "InterAmerican (Miami)": "621 Beacom Blvd, Miami, FL 33135",
    "Greater Miami (Downtown Miami)": "137 NE 19 Street, Miami, FL 33132",
    "North Miami Beach": "18801 NE 22nd Ave, Miami, FL 33180",
    "Miami Gardens": "3520 NW 191st St, Miami Gardens, FL 33056",
    "Hollywood Hills": "1400 N. 46th Avenue, Hollywood, FL 33021",
    "Broward K-8": "1400 N 46th Ave, Hollywood, FL 33021",
    "Palm Beach": "1951 N Military Trl D, West Palm Beach, FL 33409",
    "Collier (Naples)": "3161 Santa Barbara Blvd, Naples, FL 34116",
    "Orange (Orlando)": "5710 La Costa Dr., Orlando, FL 32807",
    "St. Cloud": "3691 Old Canoe Creek Rd. St. Cloud, FL 34769",
    "Osceola": "4851 KOA St, Poinciana, FL 34758",
    "Tampa": "5201 N Armenia Ave, Tampa, FL 33603",
    "Riverview Elementary": "6309 US-301, Riverview, FL 33578",
    "Riverview Middle-High": "6309 US-301, Riverview, FL 33578",
    "Duval (Jacksonville)": "6400 Atlantic Blvd, Jacksonville, FL 32211",
    "Polk (Davenport)": "2045 Florence Villa Grove Rd, Davenport, FL 33897",
}


# ─── MAIN PAGE ROUTE ─────────────────────────────────────────────────────
@app.route("/")
def index():
    """Render the main application page."""
    return render_template(
        "index.html",
        schools=DISPLAY_TO_ADDRESS,
    )


# ─── API: GEOCODE ────────────────────────────────────────────────────────
@app.route("/api/geocode", methods=["POST"])
def api_geocode():
    """Geocode an address and return coordinates."""
    data = request.get_json()
    address = data.get("address", "").strip()

    if not address:
        return jsonify({"error": "No address provided"}), 400

    try:
        result = mapbox_geocode_one(address)
        if result:
            return jsonify(result)
        return jsonify({"error": "Address not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── API: ISOCHRONES ─────────────────────────────────────────────────────
@app.route("/api/isochrones", methods=["POST"])
def api_isochrones():
    """Get drive-time isochrones for a location."""
    data = request.get_json()
    lon = data.get("lon")
    lat = data.get("lat")

    if lon is None or lat is None:
        return jsonify({"error": "Missing coordinates"}), 400

    try:
        gdf = mapbox_isochrones(float(lon), float(lat), minutes=(5, 10, 15))
        gdf = gdf.sort_values("Time").reset_index(drop=True)

        # Convert to GeoJSON
        features = []
        for _, row in gdf.iterrows():
            features.append({
                "type": "Feature",
                "properties": {"Time": int(row["Time"])},
                "geometry": shapely_mapping(row["geometry"]),
            })

        return jsonify({"type": "FeatureCollection", "features": features})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── HELPER: Get isochrone GeoDataFrame ──────────────────────────────────
def _get_isochrone_gdf(lon: float, lat: float) -> Optional[gpd.GeoDataFrame]:
    """Helper to get isochrone GeoDataFrame."""
    try:
        gdf = mapbox_isochrones(lon, lat, minutes=(5, 10, 15))
        return gdf.sort_values("Time").reset_index(drop=True)
    except Exception:
        return None


# ─── API: INCOME DATA ────────────────────────────────────────────────────
@app.route("/api/income", methods=["POST"])
def api_income():
    """Get income/economic profile data for drive-time rings."""
    data = request.get_json()
    lon, lat = data.get("lon"), data.get("lat")

    if lon is None or lat is None:
        return jsonify({"error": "Missing coordinates"}), 400

    try:
        iso_df = _get_isochrone_gdf(float(lon), float(lat))
        if iso_df is None or iso_df.empty:
            return jsonify({"rows": _empty_income_rows()})

        result = _calculate_income_data(iso_df, float(lon), float(lat))
        return jsonify({"rows": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _empty_income_rows():
    """Return empty income data rows."""
    return [
        {"zone": f"{t}-min", "med_income": "No data", "under50k": "No data", "50_75k": "No data", "cash_assist": "No data"}
        for t in (5, 10, 15)
    ]


def _calculate_income_data(iso_df: gpd.GeoDataFrame, lon: float, lat: float) -> list:
    """Calculate income statistics for each drive-time ring."""
    tracts = get_tracts_with_acs(ACS_YEAR)

    has_u50 = "p_under50" in tracts.columns
    has_50_75 = "p_50_75" in tracts.columns
    has_cash = "p_cash_assist" in tracts.columns

    # Point → tract → county FIPS
    pt = gpd.GeoDataFrame(
        [{"id": "pt"}],
        geometry=gpd.points_from_xy([lon], [lat]),
        crs=4326,
    ).to_crs(tracts.crs)

    pt_in_tract = gpd.sjoin(
        pt, tracts[["GEOID", "geometry"]], how="left", predicate="within"
    ).drop(columns=["index_right"])

    geoid = None if pt_in_tract.empty else str(pt_in_tract["GEOID"].iloc[0])
    NO = {"estimate": None, "pct_under50": None, "pct_50_75": None, "pct_cash_assist": None}

    if not geoid or geoid == "None":
        return _empty_income_rows()

    county_fips_list = [geoid[2:5]]

    # Blocks + HU weights
    blocks = get_blocks_for_counties(county_fips_list)
    if blocks.empty:
        return _empty_income_rows()

    if "GEOID20" not in blocks.columns and "GEOID" in blocks.columns:
        blocks = blocks.rename(columns={"GEOID": "GEOID20"})

    weight_col = "HU20"
    tracts_proj = tracts.to_crs(AREA_CRS)
    blocks_proj = blocks.to_crs(AREA_CRS).copy()
    blocks_proj["blk_area"] = blocks_proj.geometry.area

    if weight_col not in blocks_proj.columns or blocks_proj[weight_col].dropna().empty:
        weight_col = "__AREA_WT__"
        blocks_proj[weight_col] = 1.0

    right_cols = ["GEOID", "estimate", "moe", "geometry"]
    if has_u50:
        right_cols.append("p_under50")
    if has_50_75:
        right_cols.append("p_50_75")
    if has_cash:
        right_cols.append("p_cash_assist")

    res = {}
    for T, geom in iso_df[["Time", "geometry"]].itertuples(index=False):
        poly_proj = gpd.GeoDataFrame([{"geometry": geom}], crs=4326).to_crs(AREA_CRS).geometry.iloc[0]
        try:
            poly_proj = poly_proj.buffer(0)
        except Exception:
            pass

        minx, miny, maxx, maxy = poly_proj.bounds
        blocks_clip = blocks_proj.cx[minx:maxx, miny:maxy].copy()

        if blocks_clip.empty:
            res[T] = NO.copy()
            continue

        try:
            blocks_clip["geometry"] = blocks_clip.geometry.buffer(0)
        except Exception:
            pass

        try:
            inter = gpd.overlay(
                blocks_clip[["GEOID20", weight_col, "blk_area", "geometry"]],
                gpd.GeoDataFrame([{"geometry": poly_proj}], crs=AREA_CRS),
                how="intersection",
            )
        except Exception:
            res[T] = NO.copy()
            continue

        if inter.empty:
            res[T] = NO.copy()
            continue

        inter = inter[inter["blk_area"] > 0]
        if inter.empty:
            res[T] = NO.copy()
            continue

        inter["part_area"] = inter.geometry.area
        inter["area_frac"] = (inter["part_area"] / inter["blk_area"]).clip(lower=0, upper=1)
        inter["weight"] = inter[weight_col].abs().fillna(0) * inter["area_frac"]

        inter = gpd.sjoin(
            inter, tracts_proj[right_cols], predicate="within", how="left"
        ).drop(columns=["index_right"])

        inter = inter[np.isfinite(inter["estimate"]) & (inter["weight"] > 0)]
        if inter.empty:
            res[T] = NO.copy()
            continue

        est, moe = weighted_est_and_moe(inter)
        if est is not None and est < 0:
            est = 0.0

        u50 = weighted_share(inter, "p_under50") if has_u50 else None
        m50_75 = weighted_share(inter, "p_50_75") if has_50_75 else None
        cash = weighted_share(inter, "p_cash_assist") if has_cash else None

        res[T] = {"estimate": est, "pct_under50": u50, "pct_50_75": m50_75, "pct_cash_assist": cash}

    for t in (5, 10, 15):
        res.setdefault(t, NO.copy())

    # Format output
    rows = []
    for t in (5, 10, 15):
        d = res.get(t, {})
        rows.append({
            "zone": f"{t}-min",
            "med_income": fmt_money(d.get("estimate")),
            "under50k": fmt_pct(d.get("pct_under50")),
            "50_75k": fmt_pct(d.get("pct_50_75")),
            "cash_assist": fmt_pct(d.get("pct_cash_assist")),
        })
    return rows


# ─── API: POPULATION DATA ────────────────────────────────────────────────
@app.route("/api/population", methods=["POST"])
def api_population():
    """Get population data for drive-time rings."""
    data = request.get_json()
    lon, lat = data.get("lon"), data.get("lat")

    if lon is None or lat is None:
        return jsonify({"error": "Missing coordinates"}), 400

    try:
        iso_df = _get_isochrone_gdf(float(lon), float(lat))
        if iso_df is None or iso_df.empty:
            return jsonify({"rows": _empty_population_rows()})

        result = _calculate_population_data(iso_df, float(lon), float(lat))
        return jsonify({"rows": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _empty_population_rows():
    """Return empty population data rows."""
    return [
        {"zone": f"{t}-min", "total_pop": "No data", "pop_k": "No data", "pop_1_4": "No data",
         "pop_5_8": "No data", "pop_9_12": "No data", "pct_nonwhite": "No data", "pct_ba_plus": "No data"}
        for t in (5, 10, 15)
    ]


def _calculate_population_data(iso_df: gpd.GeoDataFrame, lon: float, lat: float) -> list:
    """Calculate population statistics for each drive-time ring."""
    tracts = get_tracts_table()
    tracts_proj = tracts.to_crs(AREA_CRS)

    BLANK = {
        "pop_total": None, "pop_k": None, "pop_1_4": None, "pop_5_8": None,
        "pop_9_12": None, "pct_nonwhite": None, "pct_ba_plus": None,
    }
    out = {}

    for T, geom_wgs in iso_df[["Time", "geometry"]].itertuples(index=False):
        poly_wgs = safe_buffer0(geom_wgs)
        if poly_wgs.is_empty:
            out[T] = BLANK.copy()
            continue

        county_fips_list = counties_touching(poly_wgs)
        if not county_fips_list:
            out[T] = BLANK.copy()
            continue

        blocks = get_blocks_for_counties(county_fips_list)
        if blocks.empty:
            out[T] = BLANK.copy()
            continue

        weight_col = "HU20"
        poly_proj = gpd.GeoSeries([poly_wgs], crs=WGS84).to_crs(AREA_CRS).iloc[0]
        blocks_proj = blocks.to_crs(AREA_CRS).copy()

        try:
            blocks_proj["geometry"] = blocks_proj.geometry.buffer(0)
        except Exception:
            pass
        blocks_proj["blk_area"] = blocks_proj.geometry.area

        try:
            idx = blocks_proj.sindex
            cand_idx = list(idx.query(poly_proj, predicate="intersects"))
            blocks_clip = blocks_proj.iloc[cand_idx].copy()
        except Exception:
            minx, miny, maxx, maxy = poly_proj.bounds
            blocks_clip = blocks_proj.cx[minx:maxx, miny:maxy].copy()

        if blocks_clip.empty:
            out[T] = BLANK.copy()
            continue

        if weight_col not in blocks_clip.columns or blocks_clip[weight_col].dropna().empty:
            weight_col = "__AREA_WT__"
            blocks_clip[weight_col] = 1.0

        try:
            inter = gpd.overlay(
                blocks_clip[["GEOID20", weight_col, "blk_area", "geometry"]],
                gpd.GeoDataFrame([{"geometry": poly_proj}], crs=AREA_CRS),
                how="intersection",
            )
        except Exception:
            out[T] = BLANK.copy()
            continue

        if inter.empty:
            out[T] = BLANK.copy()
            continue

        inter = inter[inter["blk_area"] > 0]
        if inter.empty:
            out[T] = BLANK.copy()
            continue

        inter["part_area"] = inter.geometry.area
        inter["area_frac"] = (inter["part_area"] / inter["blk_area"]).clip(0, 1)
        inter["weight"] = inter[weight_col].abs().fillna(0) * inter["area_frac"]

        inter = gpd.sjoin(
            inter,
            tracts_proj[[
                "GEOID", "geometry", "pop_total_per_hu", "pop_k_per_hu", "pop_1_4_per_hu",
                "pop_5_8_per_hu", "pop_9_12_per_hu", "race_total_per_hu", "white_alone_per_hu",
                "pop_25plus_per_hu", "ba_plus_per_hu",
            ]],
            predicate="within",
            how="left",
        ).drop(columns=["index_right"])

        if inter.empty or inter["weight"].fillna(0).sum() == 0:
            out[T] = BLANK.copy()
            continue

        def hu_sum(col: str):
            x = inter[col].to_numpy(dtype="float64")
            w = inter["weight"].to_numpy(dtype="float64")
            m = np.isfinite(x) & np.isfinite(w) & (w > 0)
            return None if not m.any() else float((x[m] * w[m]).sum())

        pop_total = hu_sum("pop_total_per_hu")
        pop_k = hu_sum("pop_k_per_hu")
        pop_1_4 = hu_sum("pop_1_4_per_hu")
        pop_5_8 = hu_sum("pop_5_8_per_hu")
        pop_9_12 = hu_sum("pop_9_12_per_hu")

        race_total = hu_sum("race_total_per_hu")
        white_only = hu_sum("white_alone_per_hu")
        pct_nonwhite = None
        if race_total and np.isfinite(race_total) and race_total > 0 and white_only is not None:
            pct_nonwhite = 100.0 * max(race_total - white_only, 0.0) / race_total

        pop_25plus = hu_sum("pop_25plus_per_hu")
        ba_plus = hu_sum("ba_plus_per_hu")
        pct_ba_plus = None
        if pop_25plus and np.isfinite(pop_25plus) and pop_25plus > 0 and ba_plus is not None:
            pct_ba_plus = 100.0 * max(ba_plus, 0.0) / pop_25plus

        out[T] = {
            "pop_total": None if not np.isfinite(pop_total) else float(pop_total),
            "pop_k": None if not np.isfinite(pop_k) else float(pop_k),
            "pop_1_4": None if not np.isfinite(pop_1_4) else float(pop_1_4),
            "pop_5_8": None if not np.isfinite(pop_5_8) else float(pop_5_8),
            "pop_9_12": None if not np.isfinite(pop_9_12) else float(pop_9_12),
            "pct_nonwhite": pct_nonwhite if pct_nonwhite and np.isfinite(pct_nonwhite) else None,
            "pct_ba_plus": pct_ba_plus if pct_ba_plus and np.isfinite(pct_ba_plus) else None,
        }

    for t in (5, 10, 15):
        out.setdefault(t, BLANK.copy())

    rows = []
    for t in (5, 10, 15):
        d = out.get(t, {})
        rows.append({
            "zone": f"{t}-min",
            "total_pop": fmt_int(d.get("pop_total")),
            "pop_k": fmt_int(d.get("pop_k")),
            "pop_1_4": fmt_int(d.get("pop_1_4")),
            "pop_5_8": fmt_int(d.get("pop_5_8")),
            "pop_9_12": fmt_int(d.get("pop_9_12")),
            "pct_nonwhite": fmt_pct(d.get("pct_nonwhite")),
            "pct_ba_plus": fmt_pct(d.get("pct_ba_plus")),
        })
    return rows


# ─── API: PUBLIC SCHOOL ENROLLMENT ───────────────────────────────────────
@app.route("/api/publicschool", methods=["POST"])
def api_publicschool():
    """Get public school enrollment percentages for drive-time rings."""
    data = request.get_json()
    lon, lat = data.get("lon"), data.get("lat")

    if lon is None or lat is None:
        return jsonify({"error": "Missing coordinates"}), 400

    try:
        iso_df = _get_isochrone_gdf(float(lon), float(lat))
        if iso_df is None or iso_df.empty:
            return jsonify({"rows": _empty_publicschool_rows()})

        result = _calculate_publicschool_data(iso_df, float(lon), float(lat))
        return jsonify({"rows": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _empty_publicschool_rows():
    """Return empty public school data rows."""
    return [
        {"zone": f"{t}-min", "pct_k": "No data", "pct_1_4": "No data", "pct_5_8": "No data", "pct_9_12": "No data"}
        for t in (5, 10, 15)
    ]


def _calculate_publicschool_data(iso_df: gpd.GeoDataFrame, lon: float, lat: float) -> list:
    """Calculate public school enrollment percentages for each drive-time ring."""
    tracts = get_tracts_table()

    pt = gpd.GeoDataFrame(
        [{"id": "pt"}],
        geometry=gpd.points_from_xy([lon], [lat]),
        crs=4326,
    ).to_crs(tracts.crs)

    pt_in_tract = gpd.sjoin(
        pt, tracts[["GEOID", "geometry"]], how="left", predicate="within"
    ).drop(columns=["index_right"])

    geoid = None if pt_in_tract.empty else str(pt_in_tract["GEOID"].iloc[0])
    NO = {"pct_pub_k": None, "pct_pub_1_4": None, "pct_pub_5_8": None, "pct_pub_9_12": None}

    if not geoid or geoid == "None":
        return _empty_publicschool_rows()

    county_fips_list = [geoid[2:5]]
    blocks = get_blocks_for_counties(county_fips_list)
    if blocks.empty:
        return _empty_publicschool_rows()

    if "GEOID20" not in blocks.columns and "GEOID" in blocks.columns:
        blocks = blocks.rename(columns={"GEOID": "GEOID20"})

    weight_col = "HU20"
    tracts_proj = tracts.to_crs(AREA_CRS)
    blocks_proj = blocks.to_crs(AREA_CRS).copy()
    blocks_proj["blk_area"] = blocks_proj.geometry.area

    if weight_col not in blocks_proj.columns or blocks_proj[weight_col].dropna().empty:
        weight_col = "__AREA_WT__"
        blocks_proj[weight_col] = 1.0

    res = {}
    for T, geom in iso_df[["Time", "geometry"]].itertuples(index=False):
        poly_proj = gpd.GeoDataFrame([{"geometry": geom}], crs=4326).to_crs(AREA_CRS).geometry.iloc[0]
        try:
            poly_proj = poly_proj.buffer(0)
        except Exception:
            pass

        minx, miny, maxx, maxy = poly_proj.bounds
        blocks_clip = blocks_proj.cx[minx:maxx, miny:maxy].copy()

        if blocks_clip.empty:
            res[T] = NO.copy()
            continue

        try:
            blocks_clip["geometry"] = blocks_clip.geometry.buffer(0)
        except Exception:
            pass

        try:
            inter = gpd.overlay(
                blocks_clip[["GEOID20", weight_col, "blk_area", "geometry"]],
                gpd.GeoDataFrame([{"geometry": poly_proj}], crs=AREA_CRS),
                how="intersection",
            )
        except Exception:
            res[T] = NO.copy()
            continue

        if inter.empty:
            res[T] = NO.copy()
            continue

        inter = inter[inter["blk_area"] > 0]
        if inter.empty:
            res[T] = NO.copy()
            continue

        inter["part_area"] = inter.geometry.area
        inter["area_frac"] = (inter["part_area"] / inter["blk_area"]).clip(lower=0, upper=1)
        inter["weight"] = inter[weight_col].abs().fillna(0) * inter["area_frac"]

        keep_cols = ["GEOID", "geometry", "p_pub_k", "p_pub_1_4", "p_pub_5_8", "p_pub_9_12"]
        inter = gpd.sjoin(
            inter, tracts_proj[keep_cols], predicate="within", how="left"
        ).drop(columns=["index_right"])

        inter = inter[inter["weight"] > 0]
        if inter.empty:
            res[T] = NO.copy()
            continue

        res[T] = {
            "pct_pub_k": weighted_share(inter, "p_pub_k"),
            "pct_pub_1_4": weighted_share(inter, "p_pub_1_4"),
            "pct_pub_5_8": weighted_share(inter, "p_pub_5_8"),
            "pct_pub_9_12": weighted_share(inter, "p_pub_9_12"),
        }

    for t in (5, 10, 15):
        res.setdefault(t, NO.copy())

    rows = []
    for t in (5, 10, 15):
        d = res.get(t, {})
        rows.append({
            "zone": f"{t}-min",
            "pct_k": fmt_pct(d.get("pct_pub_k")),
            "pct_1_4": fmt_pct(d.get("pct_pub_1_4")),
            "pct_5_8": fmt_pct(d.get("pct_pub_5_8")),
            "pct_9_12": fmt_pct(d.get("pct_pub_9_12")),
        })
    return rows


# ─── API: SCHOOLS DATA ───────────────────────────────────────────────────
@app.route("/api/schools", methods=["POST"])
def api_schools():
    """Get competing schools data filtered by drive-time rings."""
    data = request.get_json()
    lon, lat = data.get("lon"), data.get("lat")

    if lon is None or lat is None:
        return jsonify({"error": "Missing coordinates"}), 400

    try:
        iso_df = _get_isochrone_gdf(float(lon), float(lat))
        if iso_df is None or iso_df.empty:
            return jsonify({"schools": [], "summary": []})

        schools_df = _get_schools_in_rings(iso_df)
        if schools_df is None or schools_df.empty:
            return jsonify({"schools": [], "summary": []})

        # Calculate summary stats
        summary = _calculate_school_summary(iso_df, schools_df)

        # Format schools for display
        schools_list = schools_df.to_dict("records")

        return jsonify({"schools": schools_list, "summary": summary})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _get_schools_in_rings(iso_df: gpd.GeoDataFrame) -> Optional[pd.DataFrame]:
    """Get schools filtered to those within isochrone rings."""
    pl_df = combine()
    if pl_df is None or pl_df.is_empty():
        return None

    cols = [c for c in pl_df.columns]
    lat_cands = [c for c in cols if c.lower().startswith("latitude")]
    lon_cands = [c for c in cols if c.lower().startswith("longitude")]
    if not lat_cands or not lon_cands:
        return None

    def _best_candidate(cands: list) -> str:
        bestc = None
        bestn = -1
        for c in cands:
            try:
                n = pl_df.filter(pl.col(c).is_not_null()).height
            except Exception:
                n = 0
            if n > bestn:
                bestn = n
                bestc = c
        return bestc

    lat_col = _best_candidate(lat_cands)
    lon_col = _best_candidate(lon_cands)
    if lat_col is None or lon_col is None:
        return None

    df0 = (
        pl_df.with_columns([
            pl.col(lat_col).cast(pl.Float64, strict=False).alias("Latitude"),
            pl.col(lon_col).cast(pl.Float64, strict=False).alias("Longitude"),
        ])
        .filter(pl.col("Latitude").is_not_null() & pl.col("Longitude").is_not_null())
        .to_pandas()
    )

    if df0.empty:
        return None

    pts = gpd.GeoDataFrame(
        df0,
        geometry=gpd.points_from_xy(df0["Longitude"], df0["Latitude"]),
        crs=4326,
    )

    j = gpd.sjoin(pts, iso_df[["Time", "geometry"]], how="inner", predicate="within")
    if j.empty:
        return None

    closest = j.groupby(j.index)["Time"].min()
    result = df0.loc[closest.index].copy()
    result["DriveTimeMin"] = closest.values

    # Clean up for display
    result = result.drop(columns=["geometry", "Latitude", "Longitude"], errors="ignore")

    # Sort by drive time then school name
    result["DriveTimeMin"] = pd.Categorical(result["DriveTimeMin"], categories=[5, 10, 15], ordered=True)
    name_col = next((c for c in ["School", "School Name", "Name"] if c in result.columns), None)
    sort_cols = ["DriveTimeMin"] + ([name_col] if name_col else [])
    result = result.sort_values(sort_cols, kind="stable").reset_index(drop=True)

    # Rename columns for display
    rename_cols = {
        "District Name": "District",
        "School Name": "School",
        "DriveTimeMin": "Drive Time",
        "# of Students": "Student #",
        "% Eco Disadvantaged": "% Eco. Disadv.",
        "% Absent 10-21": "% Abs. 10-21",
        "% Absent 21+": "% Abs. 21+",
    }
    result = result.rename(columns=rename_cols)

    # Fill missing capacity with student count
    if "Capacity" in result.columns and "Student #" in result.columns:
        result["Capacity"] = result["Capacity"].mask(
            result["Capacity"].isna() | (result["Capacity"] == 0), result["Student #"]
        )

    return result


def _calculate_school_summary(iso_df: gpd.GeoDataFrame, schools_df: pd.DataFrame) -> list:
    """Calculate enrollment and capacity summary by drive time."""
    pl_df = combine()
    if pl_df is None or pl_df.is_empty():
        return []

    cols = [c for c in pl_df.columns]
    lat_cands = [c for c in cols if c.lower().startswith("latitude")]
    lon_cands = [c for c in cols if c.lower().startswith("longitude")]

    def _best_candidate(cands: list) -> str:
        bestc = None
        bestn = -1
        for c in cands:
            try:
                n = pl_df.filter(pl.col(c).is_not_null()).height
            except Exception:
                n = 0
            if n > bestn:
                bestn = n
                bestc = c
        return bestc

    lat_col = _best_candidate(lat_cands)
    lon_col = _best_candidate(lon_cands)

    try:
        iso = iso_df.copy()
        if getattr(iso, "crs", None) is None or iso.crs.to_epsg() != 4326:
            iso = iso.set_crs(4326, allow_override=True)
        iso["geometry"] = iso["geometry"].buffer(0)
        iso = iso.explode(index_parts=False, ignore_index=True)

        df = (
            pl_df.with_columns([
                pl.col(lat_col).cast(pl.Float64, strict=False).alias("Latitude"),
                pl.col(lon_col).cast(pl.Float64, strict=False).alias("Longitude"),
                pl.col("# of Students").cast(pl.Float64, strict=False),
                pl.col("Capacity").cast(pl.Float64, strict=False),
            ])
            .filter(pl.col("Latitude").is_not_null() & pl.col("Longitude").is_not_null())
            .to_pandas()
        )

        pts = gpd.GeoDataFrame(
            df.dropna(subset=["Latitude", "Longitude"]),
            geometry=gpd.points_from_xy(df["Longitude"], df["Latitude"]),
            crs=4326,
        )

        def ring_sums(T: int):
            sel = iso[iso["Time"] == T]
            if sel.empty:
                return 0, 0
            poly = gpd.GeoDataFrame([{"geometry": sel.iloc[0]["geometry"]}], crs=4326)
            try:
                j = gpd.sjoin(pts, poly, how="inner", predicate="intersects")
            except Exception:
                return 0, 0
            if j.empty:
                return 0, 0
            enr = j["# of Students"].fillna(0).sum()
            cap = j["Capacity"].fillna(0).sum()
            return int(enr), int(cap)

        rows = []
        for T in (5, 10, 15):
            enr, cap = ring_sums(T)
            ratio = f"{(cap / enr):.2f}:1" if enr > 0 and cap > 0 else ("∞" if enr == 0 and cap > 0 else "—")
            rows.append({
                "drive_time": f"{T}-min",
                "enrollment": f"{enr:,}",
                "capacity": f"{cap:,}",
                "cap_enroll": ratio,
            })
        return rows

    except Exception:
        return []


# ─── API: SCHOOLS FOR MAP ────────────────────────────────────────────────
@app.route("/api/schools_map", methods=["POST"])
def api_schools_map():
    """Get school locations for map markers."""
    data = request.get_json()
    lon, lat = data.get("lon"), data.get("lat")

    if lon is None or lat is None:
        return jsonify({"error": "Missing coordinates"}), 400

    try:
        iso_df = _get_isochrone_gdf(float(lon), float(lat))
        if iso_df is None or iso_df.empty:
            return jsonify({"schools": []})

        pl_df = combine()
        if pl_df is None or pl_df.is_empty():
            return jsonify({"schools": []})

        cols = [c for c in pl_df.columns]
        lat_cands = [c for c in cols if c.lower().startswith("latitude")]
        lon_cands = [c for c in cols if c.lower().startswith("longitude")]
        if not lat_cands or not lon_cands:
            return jsonify({"schools": []})

        def _best_candidate(cands: list) -> str:
            bestc = None
            bestn = -1
            for c in cands:
                try:
                    n = pl_df.filter(pl.col(c).is_not_null()).height
                except Exception:
                    n = 0
                if n > bestn:
                    bestn = n
                    bestc = c
            return bestc

        lat_col = _best_candidate(lat_cands)
        lon_col = _best_candidate(lon_cands)

        df0 = (
            pl_df.with_columns([
                pl.col(lat_col).cast(pl.Float64, strict=False).alias("Latitude"),
                pl.col(lon_col).cast(pl.Float64, strict=False).alias("Longitude"),
            ])
            .filter(pl.col("Latitude").is_not_null() & pl.col("Longitude").is_not_null())
            .to_pandas()
        )

        if df0.empty:
            return jsonify({"schools": []})

        pts = gpd.GeoDataFrame(
            df0,
            geometry=gpd.points_from_xy(df0["Longitude"], df0["Latitude"]),
            crs=4326,
        )

        j = gpd.sjoin(pts, iso_df[["Time", "geometry"]], how="inner", predicate="within")
        if j.empty:
            return jsonify({"schools": []})

        closest = j.groupby(j.index)["Time"].min()
        result = df0.loc[closest.index].copy()
        result["DriveTimeMin"] = closest.values

        name_col = next((c for c in ["School", "School Name", "Name"] if c in result.columns), None)

        schools = []
        for _, row in result.iterrows():
            schools.append({
                "lat": float(row["Latitude"]),
                "lon": float(row["Longitude"]),
                "name": str(row[name_col]) if name_col else "School",
                "drive_time": int(row["DriveTimeMin"]),
            })

        return jsonify({"schools": schools})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── API: EXPORTS (XLSX) ───────────────────────────────────────────────
def _df_to_excel_response(df: pd.DataFrame, filename: str):
    """Convert a DataFrame to an in-memory XLSX response."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Sheet1")
    output.seek(0)
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def _sanitize_name_part(s: Optional[str]) -> Optional[str]:
    """Sanitize a name part for use in a filename: take first comma-separated part,
    strip leading numbers, replace spaces with underscores, and remove unsafe chars."""
    if not s:
        return None
    part = str(s).split(',')[0].strip()
    # remove leading house number or symbols
    part = re.sub(r'^[\d#\s]+', '', part)
    part = re.sub(r'\s+', '_', part)
    part = re.sub(r'[^A-Za-z0-9_-]', '', part)
    return part or None


def _profile_df_to_wide(df: pd.DataFrame) -> pd.DataFrame:
    """Convert a profile DataFrame with a 'zone' column into a wide format
    where each zone becomes a column and rows are metrics.

    Example input:
      zone | med_income | under50k
      5-min| $50,000    | 30%
      10-min| ...

    Output:
      Metric      | 5-min | 10-min | 15-min
      med_income  | $50k  | ...
      under50k    | 30%   | ...
    """
    if df is None or df.empty or "zone" not in df.columns:
        return df if df is not None else pd.DataFrame()

    # Ensure zone values are strings and unique
    tmp = df.copy()
    tmp["zone"] = tmp["zone"].astype(str)

    try:
        wide = tmp.set_index("zone").T.reset_index()
        wide = wide.rename(columns={"index": "Metric"})
    except Exception:
        # Fallback: construct manually
        zones = [z for z in ["5-min", "10-min", "15-min"] if z in tmp["zone"].values]
        rows = []
        keys = [c for c in tmp.columns if c != "zone"]
        for k in keys:
            row = {"Metric": k}
            for z in zones:
                val = tmp.loc[tmp["zone"] == z, k]
                row[z] = val.iloc[0] if not val.empty else None
            rows.append(row)
        wide = pd.DataFrame(rows)

    # Reorder columns: Metric, 5-min, 10-min, 15-min (if present)
    cols = [c for c in ["Metric", "5-min", "10-min", "15-min"] if c in wide.columns]
    # include any other columns after those
    other = [c for c in wide.columns if c not in cols]
    wide = wide[cols + other]
    return wide


@app.route("/api/export/income", methods=["POST"])
def api_export_income():
    data = request.get_json()
    lon, lat = data.get("lon"), data.get("lat")
    name_hint = data.get("name") or data.get("place")
    if lon is None or lat is None:
        return jsonify({"error": "Missing coordinates"}), 400
    try:
        iso_df = _get_isochrone_gdf(float(lon), float(lat))
        rows = _calculate_income_data(iso_df, float(lon), float(lat)) if iso_df is not None else []
        df = pd.DataFrame(rows)
        # Pivot so zones are columns
        df_out = _profile_df_to_wide(df)
        base = "income_profile"
        part = _sanitize_name_part(name_hint)
        fname = f"{base}_{part}.xlsx" if part else f"{base}.xlsx"
        return _df_to_excel_response(df_out, fname)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/export/population", methods=["POST"])
def api_export_population():
    data = request.get_json()
    lon, lat = data.get("lon"), data.get("lat")
    name_hint = data.get("name") or data.get("place")
    if lon is None or lat is None:
        return jsonify({"error": "Missing coordinates"}), 400
    try:
        iso_df = _get_isochrone_gdf(float(lon), float(lat))
        rows = _calculate_population_data(iso_df, float(lon), float(lat)) if iso_df is not None else []
        df = pd.DataFrame(rows)
        df_out = _profile_df_to_wide(df)
        base = "population_profile"
        part = _sanitize_name_part(name_hint)
        fname = f"{base}_{part}.xlsx" if part else f"{base}.xlsx"
        return _df_to_excel_response(df_out, fname)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/export/publicschool", methods=["POST"])
def api_export_publicschool():
    data = request.get_json()
    lon, lat = data.get("lon"), data.get("lat")
    name_hint = data.get("name") or data.get("place")
    if lon is None or lat is None:
        return jsonify({"error": "Missing coordinates"}), 400
    try:
        iso_df = _get_isochrone_gdf(float(lon), float(lat))
        rows = _calculate_publicschool_data(iso_df, float(lon), float(lat)) if iso_df is not None else []
        df = pd.DataFrame(rows)
        df_out = _profile_df_to_wide(df)
        base = "publicschool_profile"
        part = _sanitize_name_part(name_hint)
        fname = f"{base}_{part}.xlsx" if part else f"{base}.xlsx"
        return _df_to_excel_response(df_out, fname)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/export/schools", methods=["POST"])
def api_export_schools():
    data = request.get_json()
    lon, lat = data.get("lon"), data.get("lat")
    name_hint = data.get("name") or data.get("place")
    if lon is None or lat is None:
        return jsonify({"error": "Missing coordinates"}), 400
    try:
        iso_df = _get_isochrone_gdf(float(lon), float(lat))
        base = "schools"
        part = _sanitize_name_part(name_hint)
        fname = f"{base}_{part}.xlsx" if part else f"{base}.xlsx"

        if iso_df is None or iso_df.empty:
            df = pd.DataFrame(columns=["Drive Time", "School", "District", "Student #", "Capacity", "Grade"])
            return _df_to_excel_response(df, fname)

        schools_df = _get_schools_in_rings(iso_df)
        if schools_df is None or schools_df.empty:
            df = pd.DataFrame(columns=["Drive Time", "School", "District", "Student #", "Capacity", "Grade"])
            return _df_to_excel_response(df, fname)

        return _df_to_excel_response(schools_df, fname)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/export/schools_summary", methods=["POST"])
def api_export_schools_summary():
    data = request.get_json()
    lon, lat = data.get("lon"), data.get("lat")
    name_hint = data.get("name") or data.get("place")
    if lon is None or lat is None:
        return jsonify({"error": "Missing coordinates"}), 400
    try:
        iso_df = _get_isochrone_gdf(float(lon), float(lat))
        base = "schools_summary"
        part = _sanitize_name_part(name_hint)
        fname = f"{base}_{part}.xlsx" if part else f"{base}.xlsx"

        if iso_df is None or iso_df.empty:
            df = pd.DataFrame(columns=["drive_time", "enrollment", "capacity", "cap_enroll"])
            return _df_to_excel_response(df, fname)

        schools_df = _get_schools_in_rings(iso_df)
        if schools_df is None or schools_df.empty:
            df = pd.DataFrame(columns=["drive_time", "enrollment", "capacity", "cap_enroll"])
            return _df_to_excel_response(df, fname)

        summary = _calculate_school_summary(iso_df, schools_df)
        df = pd.DataFrame(summary)
        return _df_to_excel_response(df, fname)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
