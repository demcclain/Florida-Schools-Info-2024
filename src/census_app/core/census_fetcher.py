"""Centralized Census data fetching using pytidycensus.

This module provides a unified interface for fetching ACS and Decennial Census data
using the pytidycensus library, which provides a Python interface similar to R's tidycensus.

Usage:
    from census_app.core.census_fetcher import (
        get_acs_income,
        get_acs_income_shares,
        get_acs_population,
        get_acs_housing_units,
        get_acs_enrollment_bands,
        get_acs_race,
        get_acs_education,
        get_acs_cash_assist,
        get_acs_public_enrollment,
        get_acs_population_bands,
        get_decennial_block_hu,
        get_all_tract_acs,
    )
"""
from __future__ import annotations

from functools import lru_cache
from typing import List, Optional, Union

import numpy as np
import pandas as pd
import pytidycensus as tc

from .config import ACS_YEAR, CENSUS_API_KEY, STATE_FIPS


def _fetch_acs(
    variables: Union[List[str], dict],
    year: int = ACS_YEAR,
    state: str = STATE_FIPS,
    geography: str = "tract",
    survey: str = "acs5",
    output: str = "wide",
) -> pd.DataFrame:
    """
    Fetch ACS data using pytidycensus.

    Args:
        variables: List of Census variable codes or dict of {name: code}
        year: ACS year
        state: State FIPS code or name/abbreviation
        geography: Geographic level ("tract", "county", "block group")
        survey: Survey type ("acs5" for 5-year estimates)
        output: Output format ("wide" or "tidy")

    Returns:
        DataFrame with GEOID and requested variables
    """
    df = tc.get_acs(
        geography=geography,
        variables=variables,
        year=year,
        state=state,
        survey=survey,
        output=output,
        api_key=CENSUS_API_KEY,
    )

    return df


# =============================================================================
# ACS 5-Year Data Fetchers - Tract Level
# =============================================================================

@lru_cache(maxsize=4)
def get_acs_income(year: int = ACS_YEAR, state_fips: str = STATE_FIPS) -> pd.DataFrame:
    """
    Fetch median household income (B19013_001) for all tracts in a state.

    Returns:
        DataFrame with columns: GEOID, estimate, moe
    """
    # Use named variables to get clear column names
    variables = {
        "estimate": "B19013_001"
    }

    df = _fetch_acs(
        variables=variables,
        year=year,
        state=state_fips,
        geography="tract",
        output="wide",
    )

    if df.empty:
        return pd.DataFrame(columns=["GEOID", "estimate", "moe"])

    result = pd.DataFrame({"GEOID": df["GEOID"]})

    # Get estimate column - pytidycensus returns 'estimate' directly with wide output
    if "estimate" in df.columns:
        result["estimate"] = pd.to_numeric(df["estimate"], errors="coerce")
    elif "estimateE" in df.columns:
        result["estimate"] = pd.to_numeric(df["estimateE"], errors="coerce")
    else:
        result["estimate"] = np.nan

    # Get MOE column - pytidycensus returns '{var}_moe' format
    if "estimate_moe" in df.columns:
        result["moe"] = pd.to_numeric(df["estimate_moe"], errors="coerce")
    elif "estimateM" in df.columns:
        result["moe"] = pd.to_numeric(df["moe"], errors="coerce")
    else:
        result["moe"] = np.nan

    # Clean values: negative values and values > $1M are invalid
    result.loc[result["estimate"] < 0, "estimate"] = np.nan
    result.loc[result["estimate"] > 1_000_000, "estimate"] = np.nan
    result.loc[result["moe"] < 0, "moe"] = np.nan

    return result


@lru_cache(maxsize=4)
def get_acs_income_shares(year: int = ACS_YEAR, state_fips: str = STATE_FIPS) -> pd.DataFrame:
    """
    Fetch income distribution shares: % households <$50k and $50-75k (B19001).

    Returns:
        DataFrame with columns: GEOID, p_under50, p_50_75
    """
    # B19001: Household income bins
    variables = {
        "total": "B19001_001",  # total households
        "bin_002": "B19001_002",  # <$10k
        "bin_003": "B19001_003",  # $10k-$14,999
        "bin_004": "B19001_004",  # $15k-$19,999
        "bin_005": "B19001_005",  # $20k-$24,999
        "bin_006": "B19001_006",  # $25k-$29,999
        "bin_007": "B19001_007",  # $30k-$34,999
        "bin_008": "B19001_008",  # $35k-$39,999
        "bin_009": "B19001_009",  # $40k-$44,999
        "bin_010": "B19001_010",  # $45k-$49,999
        "bin_011": "B19001_011",  # $50k-$59,999
        "bin_012": "B19001_012",  # $60k-$74,999
    }

    df = _fetch_acs(
        variables=variables,
        year=year,
        state=state_fips,
        geography="tract",
        output="wide",
    )

    if df.empty:
        return pd.DataFrame(columns=["GEOID", "p_under50", "p_50_75"])

    # Helper to get estimate value - pytidycensus returns named var directly
    def get_est(var_name):
        # pytidycensus with wide output returns the named variable directly
        if var_name in df.columns:
            return pd.to_numeric(df[var_name], errors="coerce").fillna(0)
        # Fallback to _E suffix format
        col = f"{var_name}E"
        if col in df.columns:
            return pd.to_numeric(df[col], errors="coerce").fillna(0)
        return pd.Series([0] * len(df))

    tot = get_est("total").replace({0: np.nan})

    # Sum <$50k bins (002-010)
    under50_vars = ["bin_002", "bin_003", "bin_004", "bin_005",
                    "bin_006", "bin_007", "bin_008", "bin_009", "bin_010"]
    under50 = sum(get_est(v) for v in under50_vars)

    # Sum $50k-$75k bins (011-012)
    mid50_75_vars = ["bin_011", "bin_012"]
    mid50_75 = sum(get_est(v) for v in mid50_75_vars)

    return pd.DataFrame({
        "GEOID": df["GEOID"],
        "p_under50": (under50 / tot) * 100.0,
        "p_50_75": (mid50_75 / tot) * 100.0,
    })


@lru_cache(maxsize=4)
def get_acs_cash_assist(year: int = ACS_YEAR, state_fips: str = STATE_FIPS) -> pd.DataFrame:
    """
    Fetch % households with cash public assistance (B19058).

    Returns:
        DataFrame with columns: GEOID, p_cash_assist
    """
    variables = {
        "total": "B19058_001",
        "with_assist": "B19058_002",
    }

    df = _fetch_acs(
        variables=variables,
        year=year,
        state=state_fips,
        geography="tract",
        output="wide",
    )

    if df.empty:
        return pd.DataFrame(columns=["GEOID", "p_cash_assist"])

    def get_est(var_name):
        # pytidycensus with wide output returns the named variable directly
        if var_name in df.columns:
            return pd.to_numeric(df[var_name], errors="coerce").fillna(0)
        col = f"{var_name}E"
        if col in df.columns:
            return pd.to_numeric(df[col], errors="coerce").fillna(0)
        return pd.Series([0] * len(df))

    tot = get_est("total").replace({0: np.nan})
    with_assist = get_est("with_assist")

    return pd.DataFrame({
        "GEOID": df["GEOID"],
        "p_cash_assist": (with_assist / tot) * 100.0,
    })


@lru_cache(maxsize=4)
def get_acs_population(year: int = ACS_YEAR, state_fips: str = STATE_FIPS) -> pd.DataFrame:
    """
    Fetch total population (B01003_001).

    Returns:
        DataFrame with columns: GEOID, pop_total
    """
    variables = {"pop_total": "B01003_001"}

    df = _fetch_acs(
        variables=variables,
        year=year,
        state=state_fips,
        geography="tract",
        output="wide",
    )

    if df.empty:
        return pd.DataFrame(columns=["GEOID", "pop_total"])

    pop_col = "pop_totalE" if "pop_totalE" in df.columns else "pop_total"
    pop_total = pd.to_numeric(df.get(pop_col, 0), errors="coerce")

    return pd.DataFrame({
        "GEOID": df["GEOID"],
        "pop_total": pop_total,
    })


@lru_cache(maxsize=4)
def get_acs_housing_units(year: int = ACS_YEAR, state_fips: str = STATE_FIPS) -> pd.DataFrame:
    """
    Fetch total housing units (B25001_001).

    Returns:
        DataFrame with columns: GEOID, hu_acs
    """
    variables = {"hu_acs": "B25001_001"}

    df = _fetch_acs(
        variables=variables,
        year=year,
        state=state_fips,
        geography="tract",
        output="wide",
    )

    if df.empty:
        return pd.DataFrame(columns=["GEOID", "hu_acs"])

    hu_col = "hu_acsE" if "hu_acsE" in df.columns else "hu_acs"
    hu_acs = pd.to_numeric(df.get(hu_col, 0), errors="coerce")

    return pd.DataFrame({
        "GEOID": df["GEOID"],
        "hu_acs": hu_acs,
    })


@lru_cache(maxsize=4)
def get_acs_enrollment_bands(year: int = ACS_YEAR, state_fips: str = STATE_FIPS) -> pd.DataFrame:
    """
    Fetch school enrollment by grade band (B14002): K, 1-4, 5-8, 9-12.
    This fetches PUBLIC school enrollment only.

    Returns:
        DataFrame with columns: GEOID, pop_k, pop_1_4, pop_5_8, pop_9_12
    """
    # B14002: School enrollment - public school by grade
    # Male public school: 008 (K), 011 (1-4), 014 (5-8), 017 (9-12)
    # Female public school: 032 (K), 035 (1-4), 038 (5-8), 041 (9-12)
    variables = {
        "k_male": "B14002_008",
        "k_female": "B14002_032",
        "g1_4_male": "B14002_011",
        "g1_4_female": "B14002_035",
        "g5_8_male": "B14002_014",
        "g5_8_female": "B14002_038",
        "g9_12_male": "B14002_017",
        "g9_12_female": "B14002_041",
    }

    df = _fetch_acs(
        variables=variables,
        year=year,
        state=state_fips,
        geography="tract",
        output="wide",
    )

    if df.empty:
        return pd.DataFrame(columns=["GEOID", "pop_k", "pop_1_4", "pop_5_8", "pop_9_12"])

    def get_est(var_name):
        # pytidycensus with wide output returns the named variable directly
        if var_name in df.columns:
            return pd.to_numeric(df[var_name], errors="coerce").fillna(0)
        col = f"{var_name}E"
        if col in df.columns:
            return pd.to_numeric(df[col], errors="coerce").fillna(0)
        return pd.Series([0] * len(df))

    return pd.DataFrame({
        "GEOID": df["GEOID"],
        "pop_k": get_est("k_male") + get_est("k_female"),
        "pop_1_4": get_est("g1_4_male") + get_est("g1_4_female"),
        "pop_5_8": get_est("g5_8_male") + get_est("g5_8_female"),
        "pop_9_12": get_est("g9_12_male") + get_est("g9_12_female"),
    })


@lru_cache(maxsize=4)
def get_acs_race(year: int = ACS_YEAR, state_fips: str = STATE_FIPS) -> pd.DataFrame:
    """
    Fetch race data (B02001): total and white alone.

    Returns:
        DataFrame with columns: GEOID, race_total, white_alone
    """
    variables = {
        "race_total": "B02001_001",
        "white_alone": "B02001_002",
    }

    df = _fetch_acs(
        variables=variables,
        year=year,
        state=state_fips,
        geography="tract",
        output="wide",
    )

    if df.empty:
        return pd.DataFrame(columns=["GEOID", "race_total", "white_alone"])

    def get_est(var_name):
        # pytidycensus with wide output returns the named variable directly
        if var_name in df.columns:
            return pd.to_numeric(df[var_name], errors="coerce").fillna(0)
        col = f"{var_name}E"
        if col in df.columns:
            return pd.to_numeric(df[col], errors="coerce").fillna(0)
        return pd.Series([0] * len(df))

    return pd.DataFrame({
        "GEOID": df["GEOID"],
        "race_total": get_est("race_total"),
        "white_alone": get_est("white_alone"),
    })


@lru_cache(maxsize=4)
def get_acs_education(year: int = ACS_YEAR, state_fips: str = STATE_FIPS) -> pd.DataFrame:
    """
    Fetch educational attainment (B15003): total 25+ and BA+.

    Returns:
        DataFrame with columns: GEOID, pop_25plus, ba_plus
    """
    # B15003: Educational attainment for population 25+
    # 001 = total, 022 = Bachelor's, 023 = Master's, 024 = Professional, 025 = Doctorate
    variables = {
        "total_25plus": "B15003_001",
        "bachelors": "B15003_022",
        "masters": "B15003_023",
        "professional": "B15003_024",
        "doctorate": "B15003_025",
    }

    df = _fetch_acs(
        variables=variables,
        year=year,
        state=state_fips,
        geography="tract",
        output="wide",
    )

    if df.empty:
        return pd.DataFrame(columns=["GEOID", "pop_25plus", "ba_plus"])

    def get_est(var_name):
        # pytidycensus with wide output returns the named variable directly
        if var_name in df.columns:
            return pd.to_numeric(df[var_name], errors="coerce").fillna(0)
        col = f"{var_name}E"
        if col in df.columns:
            return pd.to_numeric(df[col], errors="coerce").fillna(0)
        return pd.Series([0] * len(df))

    ba_plus = (
        get_est("bachelors") +
        get_est("masters") +
        get_est("professional") +
        get_est("doctorate")
    )

    return pd.DataFrame({
        "GEOID": df["GEOID"],
        "pop_25plus": get_est("total_25plus"),
        "ba_plus": ba_plus,
    })


@lru_cache(maxsize=4)
def get_acs_public_enrollment(year: int = ACS_YEAR, state_fips: str = STATE_FIPS) -> pd.DataFrame:
    """
    Fetch public school enrollment percentages by grade band (B14002).

    Returns:
        DataFrame with columns: GEOID, p_pub_k, p_pub_1_4, p_pub_5_8, p_pub_9_12
    """
    # B14002: School enrollment
    # For each grade band, we need total enrolled and public school enrolled
    variables = {
        # K: total enrolled (007+031), public (008+032)
        "k_tot_male": "B14002_007",
        "k_pub_male": "B14002_008",
        "k_tot_female": "B14002_031",
        "k_pub_female": "B14002_032",
        # 1-4: total enrolled (010+034), public (011+035)
        "g1_4_tot_male": "B14002_010",
        "g1_4_pub_male": "B14002_011",
        "g1_4_tot_female": "B14002_034",
        "g1_4_pub_female": "B14002_035",
        # 5-8: total enrolled (013+037), public (014+038)
        "g5_8_tot_male": "B14002_013",
        "g5_8_pub_male": "B14002_014",
        "g5_8_tot_female": "B14002_037",
        "g5_8_pub_female": "B14002_038",
        # 9-12: total enrolled (016+040), public (017+041)
        "g9_12_tot_male": "B14002_016",
        "g9_12_pub_male": "B14002_017",
        "g9_12_tot_female": "B14002_040",
        "g9_12_pub_female": "B14002_041",
    }

    df = _fetch_acs(
        variables=variables,
        year=year,
        state=state_fips,
        geography="tract",
        output="wide",
    )

    if df.empty:
        return pd.DataFrame(columns=["GEOID", "p_pub_k", "p_pub_1_4", "p_pub_5_8", "p_pub_9_12"])

    def get_est(var_name):
        # pytidycensus with wide output returns the named variable directly
        if var_name in df.columns:
            return pd.to_numeric(df[var_name], errors="coerce").fillna(0)
        col = f"{var_name}E"
        if col in df.columns:
            return pd.to_numeric(df[col], errors="coerce").fillna(0)
        return pd.Series([0] * len(df))

    # Calculate total enrolled and public enrolled for each band
    tot_k = (get_est("k_tot_male") + get_est("k_tot_female")).replace({0: np.nan})
    pub_k = get_est("k_pub_male") + get_est("k_pub_female")

    tot_1_4 = (get_est("g1_4_tot_male") + get_est("g1_4_tot_female")).replace({0: np.nan})
    pub_1_4 = get_est("g1_4_pub_male") + get_est("g1_4_pub_female")

    tot_5_8 = (get_est("g5_8_tot_male") + get_est("g5_8_tot_female")).replace({0: np.nan})
    pub_5_8 = get_est("g5_8_pub_male") + get_est("g5_8_pub_female")

    tot_9_12 = (get_est("g9_12_tot_male") + get_est("g9_12_tot_female")).replace({0: np.nan})
    pub_9_12 = get_est("g9_12_pub_male") + get_est("g9_12_pub_female")

    return pd.DataFrame({
        "GEOID": df["GEOID"],
        "p_pub_k": (pub_k / tot_k) * 100.0,
        "p_pub_1_4": (pub_1_4 / tot_1_4) * 100.0,
        "p_pub_5_8": (pub_5_8 / tot_5_8) * 100.0,
        "p_pub_9_12": (pub_9_12 / tot_9_12) * 100.0,
    })


@lru_cache(maxsize=4)
def get_acs_population_bands(year: int = ACS_YEAR, state_fips: str = STATE_FIPS) -> pd.DataFrame:
    """
    Fetch comprehensive population/housing/demographic data for tracts.
    This is the main data fetch that combines population, housing units,
    enrollment bands, race, and education.

    Returns:
        DataFrame with per-housing-unit densities for all variables.
    """
    variables = {
        # Population + housing units
        "pop_total": "B01003_001",
        "hu_acs": "B25001_001",
        # Enrollment bands (public school)
        "k_male": "B14002_008",
        "k_female": "B14002_032",
        "g1_4_male": "B14002_011",
        "g1_4_female": "B14002_035",
        "g5_8_male": "B14002_014",
        "g5_8_female": "B14002_038",
        "g9_12_male": "B14002_017",
        "g9_12_female": "B14002_041",
        # Race
        "race_total": "B02001_001",
        "white_alone": "B02001_002",
        # Education
        "total_25plus": "B15003_001",
        "bachelors": "B15003_022",
        "masters": "B15003_023",
        "professional": "B15003_024",
        "doctorate": "B15003_025",
    }

    df = _fetch_acs(
        variables=variables,
        year=year,
        state=state_fips,
        geography="tract",
        output="wide",
    )

    if df.empty:
        return pd.DataFrame()

    def get_est(var_name):
        # pytidycensus with wide output returns the named variable directly
        if var_name in df.columns:
            return pd.to_numeric(df[var_name], errors="coerce").fillna(0)
        col = f"{var_name}E"
        if col in df.columns:
            return pd.to_numeric(df[col], errors="coerce").fillna(0)
        return pd.Series([0] * len(df))

    # Calculate raw values
    pop_total = get_est("pop_total")
    hu_acs = get_est("hu_acs")
    pop_k = get_est("k_male") + get_est("k_female")
    pop_1_4 = get_est("g1_4_male") + get_est("g1_4_female")
    pop_5_8 = get_est("g5_8_male") + get_est("g5_8_female")
    pop_9_12 = get_est("g9_12_male") + get_est("g9_12_female")
    race_total = get_est("race_total")
    white_alone = get_est("white_alone")
    pop_25plus = get_est("total_25plus")
    ba_plus = (
        get_est("bachelors") +
        get_est("masters") +
        get_est("professional") +
        get_est("doctorate")
    )

    # Calculate per-housing-unit densities
    hu = hu_acs.replace({0: np.nan})

    return pd.DataFrame({
        "GEOID": df["GEOID"],
        "pop_total_per_hu": pop_total / hu,
        "pop_k_per_hu": pop_k / hu,
        "pop_1_4_per_hu": pop_1_4 / hu,
        "pop_5_8_per_hu": pop_5_8 / hu,
        "pop_9_12_per_hu": pop_9_12 / hu,
        "race_total_per_hu": race_total / hu,
        "white_alone_per_hu": white_alone / hu,
        "pop_25plus_per_hu": pop_25plus / hu,
        "ba_plus_per_hu": ba_plus / hu,
    })


# =============================================================================
# Decennial Census Data Fetchers
# =============================================================================

def get_decennial_block_hu(county_fips: str, state_fips: str = STATE_FIPS, year: int = 2020) -> pd.DataFrame:
    """
    Fetch housing units at block level from Decennial Census (H1_001N).

    Note: pytidycensus doesn't support block-level, so we use direct API requests.

    Returns:
        DataFrame with columns: GEOID20, HU20
    """
    import requests

    url = f"https://api.census.gov/data/{year}/dec/pl"
    params = {
        "get": "H1_001N",
        "for": "block:*",
        "in": f"state:{state_fips} county:{county_fips}",
        "key": CENSUS_API_KEY,
    }

    r = requests.get(url, params=params, timeout=120)
    r.raise_for_status()
    rows = r.json()

    df = pd.DataFrame(rows[1:], columns=rows[0])
    df["GEOID20"] = df["state"] + df["county"] + df["tract"] + df["block"]
    df["HU20"] = pd.to_numeric(df["H1_001N"], errors="coerce")

    return df[["GEOID20", "HU20"]]


# =============================================================================
# Convenience: fetch all tract-level ACS data in one merged DataFrame
# =============================================================================

@lru_cache(maxsize=4)
def get_all_tract_acs(year: int = ACS_YEAR, state_fips: str = STATE_FIPS) -> pd.DataFrame:
    """
    Fetch and merge all tract-level ACS data into a single DataFrame.

    Returns:
        DataFrame with all ACS variables merged on GEOID
    """
    income = get_acs_income(year, state_fips)
    shares = get_acs_income_shares(year, state_fips)
    cash = get_acs_cash_assist(year, state_fips)
    pop = get_acs_population(year, state_fips)
    hu = get_acs_housing_units(year, state_fips)
    enroll = get_acs_enrollment_bands(year, state_fips)
    race = get_acs_race(year, state_fips)
    edu = get_acs_education(year, state_fips)
    pub_enroll = get_acs_public_enrollment(year, state_fips)
    pop_bands = get_acs_population_bands(year, state_fips)

    # Start with income and merge all others
    result = income
    for df in [shares, cash, pop, hu, enroll, race, edu, pub_enroll, pop_bands]:
        if not df.empty and "GEOID" in df.columns:
            result = result.merge(df, on="GEOID", how="outer")

    return result
