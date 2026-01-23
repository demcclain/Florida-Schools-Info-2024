"""DuckDB-based school data combining."""
from __future__ import annotations

import duckdb
import polars as pl

from census_app.core import DB_PATH


def combine() -> pl.DataFrame:
    """Load and combine school data from DuckDB, returning a polars DataFrame."""
    con = duckdb.connect(DB_PATH, read_only=True)

    query = """
    WITH base AS (
        SELECT
            s.*,
            n.Latitude,
            n.Longitude,
            g.Grade,
            c.Capacity
        FROM combined_schools s
        LEFT JOIN nces n
            ON s."District #" = n."District #" AND s."School #" = n."School #"
        LEFT JOIN school_grades25 g
            ON s."District #" = g."District #" AND s."School #" = g."School #"
        LEFT JOIN capacity_all c
            ON s."District #" = c."District #" AND s."School #" = c."School #"
    ),
    cleaned AS (
        SELECT
            -- Strip "12-" prefixes from district names
            REGEXP_REPLACE("District Name", '^[0-9]{2}-', '') AS "District Name",
            -- Strip "-1234" suffixes from school names
            REGEXP_REPLACE("School Name", '-[0-9]{4}$', '') AS "School Name",
            "# of Students",
            CAST(Latitude AS DOUBLE) AS Latitude,
            CAST(Longitude AS DOUBLE) AS Longitude,
            Grade,
            CASE
                WHEN Grade IS NOT NULL
                     AND (Capacity IS NULL OR TRIM(CAST(Capacity AS VARCHAR)) = '')
                THEN CAST("# of Students" AS DOUBLE)
                ELSE CAST(Capacity AS DOUBLE)
            END AS Capacity,
            -- Convert percentage-like columns to numeric *100
            CAST("% Eco Disadvantaged" AS DOUBLE) * 100 AS "% Eco Disadvantaged",
            CAST("% ESE" AS DOUBLE) * 100 AS "% ESE",
            CAST("% ESOL" AS DOUBLE) * 100 AS "% ESOL",
            CAST("% Absent 10-21" AS DOUBLE) * 100 AS "% Absent 10-21",
            CAST("% Absent 21+" AS DOUBLE) * 100 AS "% Absent 21+",
            *
        FROM base
        WHERE "# of Students" IS NOT NULL
    ),
    deduped AS (
        SELECT *
        FROM (
            SELECT
                *,
                ROW_NUMBER() OVER (
                    PARTITION BY "School Name", "# of Students", "District Name", Latitude, Longitude
                    ORDER BY "School Name"
                ) AS rn
            FROM cleaned
        )
        WHERE rn = 1
    )
    SELECT * EXCLUDE (
        rn,
        "District #", "School #", "# ESE", "# Eco. Disadvantaged",
        "# ESOL", "# Absent 10-21", "# Absent 21+"
    )
    FROM deduped
    """

    # Use DuckDB's native polars support
    df = con.execute(query).pl()
    con.close()

    # Format percent columns as strings with "%"
    PCT_COLS = ["% Eco Disadvantaged", "% ESE", "% ESOL", "% Absent 10-21", "% Absent 21+"]

    def _fmt_pct(x: float | None) -> str | None:
        if x is None:
            return None
        txt = f"{x:.2f}".rstrip("0").rstrip(".")
        return txt + "%"

    for c in PCT_COLS:
        if c in df.columns:
            df = df.with_columns(
                pl.col(c).map_elements(_fmt_pct, return_dtype=pl.String).alias(c)
            )

    # Drop duplicate/extra columns if present
    drop_cols = [
        "District Name_1",
        "School Name_2",
        "# of Students_3",
        "% Eco Disadvantaged_4",
        "% ESE_5",
        "% ESOL_6",
        "% Absent 10-21_7",
        "% Absent 21+_8",
        "Grade_11",
        "Capacity_12",
    ]
    existing_drop = [c for c in drop_cols if c in df.columns]
    if existing_drop:
        df = df.drop(existing_drop)

    return df
