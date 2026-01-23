"""Centralized configuration and constants for the app."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Database - resolve relative to project root (Project folder)
# Walk up from this file: config.py -> core -> census_app -> src -> Project
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    _PROJECT_ROOT = Path(sys._MEIPASS)  # PyInstaller bundle temp dir
else:
    _PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DB_PATH = os.getenv("CENSUS_DB_PATH", str(_PROJECT_ROOT / "census_app.duckdb"))

# API keys/tokens (required via environment)
MAPBOX_TOKEN = os.getenv("MAPBOX_TOKEN")
CENSUS_API_KEY = os.getenv("CENSUS_API_KEY")

# Geography + app defaults
STATE_ABBR = "FL"  # Florida
STATE_FIPS = "12"  # FL = 12
ACS_YEAR = 2023    # ACS 5-year (2019–2023)
BLOCK_YEAR = 2020  # 2020 Redistricting (PL) blocks
AREA_CRS = 5070    # USA Contiguous Albers Equal Area (meters)
WGS84 = 4326
TIMEOUT = 30

# Loose FL bbox for sanity checks (minx, miny, maxx, maxy)
FL_BBOX = (-87.6349, 24.3963, -80.0314, 31.0009)
