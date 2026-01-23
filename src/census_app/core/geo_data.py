"""DuckDB data access helpers for geometry tables."""
from __future__ import annotations

from functools import lru_cache
from typing import List

import duckdb
import geopandas as gpd
import pandas as pd
from shapely import wkb

from .config import ACS_YEAR, DB_PATH


def _wkb_to_geom(val):
    if isinstance(val, (bytes, bytearray, memoryview)):
        return wkb.loads(bytes(val))
    return val


def _to_geodf(df: pd.DataFrame, geometry: str = "geometry", crs: int = 4326) -> gpd.GeoDataFrame:
    """Convert a DuckDB dataframe with WKB geometry to GeoDataFrame."""
    if geometry in df.columns:
        df[geometry] = df[geometry].apply(_wkb_to_geom)
    return gpd.GeoDataFrame(df, geometry=geometry, crs=crs)


def duckdb_query(sql: str) -> pd.DataFrame:
    """Execute a query against the local DuckDB and return a DataFrame."""
    con = duckdb.connect(DB_PATH, read_only=True)
    df = con.execute(sql).df()
    con.close()
    return df


@lru_cache(maxsize=1)
def get_tracts_fl(year: int = ACS_YEAR) -> gpd.GeoDataFrame:
    """Load tract geometries from DuckDB and convert WKB → shapely."""
    df = duckdb_query(f"SELECT GEOID, geometry FROM geo_tracts_fl_{year}")
    return _to_geodf(df, geometry="geometry", crs=4326)


@lru_cache(maxsize=1)
def get_tracts_with_acs(year: int = ACS_YEAR) -> gpd.GeoDataFrame:
    """Load Florida tracts with all ACS attributes from the precomputed tracts table."""
    df = duckdb_query("SELECT * FROM tracts")
    return _to_geodf(df, geometry="geometry", crs=4326)


@lru_cache(maxsize=1)
def get_tracts_table() -> gpd.GeoDataFrame:
    """Load the precomputed tracts table (stats + geometry)."""
    df = duckdb_query("SELECT * FROM tracts")
    return _to_geodf(df, geometry="geometry", crs=4326)


def get_blocks_for_counties(county_fips_list: List[str]) -> gpd.GeoDataFrame:
    """Load blocks (geometry + HU20) from DuckDB for given counties."""
    if not county_fips_list:
        return gpd.GeoDataFrame(columns=["GEOID20", "HU20", "geometry"], crs=4326)

    in_clause = ",".join(repr(cf) for cf in county_fips_list)
    sql = f"""
    SELECT GEOID20, HU20, geometry
    FROM blocks
    WHERE SUBSTRING(GEOID20, 3, 3) IN ({in_clause})
    """
    df = duckdb_query(sql)
    return _to_geodf(df, geometry="geometry", crs=4326)
