import os
import sys
from pathlib import Path
from urllib.request import urlopen

# Ensure src package path is available
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_PATH = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_PATH))

# DB path used by the app config
DB_PATH = Path(os.getenv("CENSUS_DB_PATH", str(PROJECT_ROOT / "census_app.duckdb")))
DB_URL = os.getenv("CENSUS_DB_URL", "").strip()

def ensure_db():
    # If DB already exists and is non-trivial size, keep it
    if DB_PATH.exists() and DB_PATH.stat().st_size > 10_000_000:
        print(f"[DB] Using existing local database: {DB_PATH} ({DB_PATH.stat().st_size / 1e6:.1f} MB)")
        return

    if not DB_URL:
        raise RuntimeError("Missing CENSUS_DB_URL and local DB file not found")

    print(f"[DB] Downloading database from OneDrive...")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with urlopen(DB_URL, timeout=300) as r:
        data = r.read()
    
    print(f"[DB] Downloaded {len(data) / 1e6:.1f} MB")

    # Guard against HTML error pages from OneDrive/SharePoint
    head = data[:2048].lower()
    if b"<html" in head or b"<!doctype" in head:
        raise RuntimeError("CENSUS_DB_URL returned HTML instead of a DuckDB file")

    if len(data) < 10_000_000:
        raise RuntimeError("Downloaded DB looks too small; check CENSUS_DB_URL")

    DB_PATH.write_bytes(data)
    print(f"[DB] Database saved to {DB_PATH}")

ensure_db()
print("[DB] Database initialization complete")

from census_app.web.flask_app import app

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
