"""WSGI entry point for Render deployment."""
import sys
import os
from pathlib import Path

# Add src to path first
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

# Import Flask app
from census_app.web.flask_app import app

# For production
if __name__ != "__main__":
    # Production (gunicorn)
    pass
else:
    # Development
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
