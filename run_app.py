#!/usr/bin/env python
"""Run the Flask Census App."""
import sys
from pathlib import Path

# Add src to path for development and handle PyInstaller bundles
src_path = Path(__file__).parent / "src"
if src_path.exists():
    sys.path.insert(0, str(src_path))

# When frozen, ensure bundled paths are on sys.path
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    sys.path.insert(0, str(Path(sys._MEIPASS)))
    sys.path.insert(0, str(Path(sys._MEIPASS) / "src"))

from census_app.web.flask_app import app

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
