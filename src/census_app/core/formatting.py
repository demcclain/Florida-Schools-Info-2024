"""Formatting helpers shared by data grids and text outputs."""
from __future__ import annotations

from typing import Dict, List

import numpy as np
import polars as pl


def fmt_int(v) -> str:
    """Format an integer-like value with commas, or return 'No data'."""
    return "No data" if (v is None or not np.isfinite(v)) else f"{int(round(v)):,}"


def fmt_pct(v) -> str:
    """Format a percentage (0-100) with no decimals, or return 'No data'."""
    return "No data" if (v is None or not np.isfinite(v)) else f"{int(round(v))}%"


def fmt_money(v) -> str:
    """Format currency with $ and commas, or return 'No data'."""
    return "No data" if (v is None or not np.isfinite(v)) else f"${int(round(v)):,}"


def make_ring_grid(rows: List[Dict], zone_key: str = "Zone") -> pl.DataFrame:
    """Pivot rows keyed by zone into a transposed display grid."""
    df = pl.DataFrame(rows)
    # Transpose: pivot so zone values become columns
    # First get all columns except zone_key
    value_cols = [c for c in df.columns if c != zone_key]

    # Build transposed data manually for simplicity
    transposed_rows = []
    for col in value_cols:
        row_data = {zone_key: col}
        for zone_row in rows:
            zone_val = str(zone_row[zone_key])
            row_data[zone_val] = zone_row.get(col)
        transposed_rows.append(row_data)

    return pl.DataFrame(transposed_rows)
