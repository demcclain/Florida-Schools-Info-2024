"""Core utilities for the Census App.

Import individual modules directly for specific functionality:
    from census_app.core.config import DB_PATH, ACS_YEAR
    from census_app.core.formatting import fmt_money
    etc.

Or import from this module to get everything (requires all dependencies):
    from census_app.core import *
"""


def __getattr__(name):
    """Lazy import to avoid loading heavy dependencies until needed."""
    # Config exports
    if name in (
        "ACS_YEAR", "AREA_CRS", "BLOCK_YEAR", "CENSUS_API_KEY", "DB_PATH",
        "FL_BBOX", "MAPBOX_TOKEN", "STATE_ABBR", "STATE_FIPS", "TIMEOUT", "WGS84"
    ):
        from . import config
        return getattr(config, name)

    # Formatting exports
    if name in ("fmt_int", "fmt_money", "fmt_pct", "make_ring_grid"):
        from . import formatting
        return getattr(formatting, name)

    # Geo data exports
    if name in (
        "duckdb_query", "get_blocks_for_counties", "get_tracts_fl",
        "get_tracts_table", "get_tracts_with_acs"
    ):
        from . import geo_data
        return getattr(geo_data, name)

    # Geo ops exports
    if name in ("counties_touching", "safe_buffer0", "weighted_est_and_moe", "weighted_share"):
        from . import geo_ops
        return getattr(geo_ops, name)

    # HTTP utils exports
    if name == "http_get_json":
        from . import http_utils
        return http_utils.http_get_json

    # Mapbox exports
    if name in ("mapbox_geocode_one", "mapbox_isochrones"):
        from . import mapbox
        return getattr(mapbox, name)

    # Census fetcher exports (tidycensus wrappers)
    if name in (
        "get_acs_income", "get_acs_income_shares", "get_acs_cash_assist",
        "get_acs_population", "get_acs_housing_units", "get_acs_enrollment_bands",
        "get_acs_race", "get_acs_education", "get_acs_public_enrollment",
        "get_acs_population_bands", "get_decennial_block_hu", "get_all_tract_acs"
    ):
        from . import census_fetcher
        return getattr(census_fetcher, name)

    # Overture Maps exports
    if name in (
        "get_buildings", "get_places", "get_roads", "get_infrastructure",
        "get_addresses", "query_overture_bbox", "features_to_geojson",
        "bbox_from_center", "OVERTURE_THEMES", "FLORIDA_BBOX"
    ):
        from . import overture
        return getattr(overture, name)

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    # config
    "ACS_YEAR",
    "AREA_CRS",
    "BLOCK_YEAR",
    "CENSUS_API_KEY",
    "DB_PATH",
    "FL_BBOX",
    "MAPBOX_TOKEN",
    "STATE_ABBR",
    "STATE_FIPS",
    "TIMEOUT",
    "WGS84",
    # formatting
    "fmt_int",
    "fmt_money",
    "fmt_pct",
    "make_ring_grid",
    # geo_data
    "duckdb_query",
    "get_blocks_for_counties",
    "get_tracts_fl",
    "get_tracts_table",
    "get_tracts_with_acs",
    # geo_ops
    "counties_touching",
    "safe_buffer0",
    "weighted_est_and_moe",
    "weighted_share",
    # http_utils
    "http_get_json",
    # mapbox
    "mapbox_geocode_one",
    "mapbox_isochrones",
    # census_fetcher (tidycensus wrappers)
    "get_acs_income",
    "get_acs_income_shares",
    "get_acs_cash_assist",
    "get_acs_population",
    "get_acs_housing_units",
    "get_acs_enrollment_bands",
    "get_acs_race",
    "get_acs_education",
    "get_acs_public_enrollment",
    "get_acs_population_bands",
    "get_decennial_block_hu",
    "get_all_tract_acs",
    # overture
    "get_buildings",
    "get_places",
    "get_roads",
    "get_infrastructure",
    "get_addresses",
    "query_overture_bbox",
    "features_to_geojson",
    "bbox_from_center",
    "OVERTURE_THEMES",
    "FLORIDA_BBOX",
]

