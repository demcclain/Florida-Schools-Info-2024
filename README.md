# 🗺️ Geospatial School Data Information App

**Status:** 🚧 *Still in active development*

An interactive **Flask** web application that integrates **geospatial, demographic, and educational datasets** to visualize socioeconomic and school data across Florida. Users can search for or select a location to explore data within **5-, 10-, and 15-minute drive-time zones** based on travel time.

---

## 🌟 Features

### 🧭 Interactive Map Visualization
- Built on **Mapbox Isochrone API** and **Leaflet**.
- Generates 5-, 10-, and 15-minute drive-time polygons around an address.
- Dynamically plots nearby schools and their key metrics.
- Resizable panels with a draggable divider and an expand/collapse mode for the full schools grid.

### 📊 Multi-Domain Data Layers
- **Economic Profile:** Median income, income distribution, and cash-assistance share from the ACS.
- **Population Profile:** Total population, race, age bands, and education attainment.
- **Public School Enrollment:** Percent of students enrolled in public schools by grade group.
- **Competing School Data:** Enrollment, demographics, attendance, and capacity metrics from DOE & NCES sources.

### 📥 Exports
- Per-panel Excel downloads for economic, population, public school, schools list, and schools summary.
- Filenames include a street-name suffix when available.

### 🏫 Integrated School Datasets
Combines multiple sources:
- **Advanced Reports** (enrollment, economic disadvantage, ESE, ESOL, attendance)
- **NCES** (Master School Directory, coordinates)
- **Florida DOE School Grades**
- **District Facility Capacity Reports**

---

## 🧮 Data Sources

- **U.S. Census Bureau APIs** (ACS 5-Year, 2020 Decennial PL)
- **Mapbox Geocoding & Isochrone APIs**
- **Florida Department of Education** (Advanced Reports, School Grades)
- **National Center for Education Statistics (NCES)**

---

## ⚡ UV (fast Python dependency manager)

This project now includes a UV lock setup for reproducible installs.

1. Create/refresh the lock file (uses your local Python):
	- `uv lock --project "C:/Users/danny/Documents/Geospatial School Data/Project" --python <path-to-python>`
2. Install dependencies from the lock:
	- `uv sync --project "C:/Users/danny/Documents/Geospatial School Data/Project"`

Run the app:
	- `python run_app.py`

---

## 🔧 Configuration

Environment variables:

- `MAPBOX_TOKEN`: Mapbox token for geocoding + isochrones. (required)
- `CENSUS_API_KEY`: Census API key (ACS). (required)
- `CENSUS_DB_PATH`: Override path to `census_app.duckdb`. (optional)

Create a local .env file (not committed) based on .env.example.

---

## 🧊 Windows EXE Packaging (PyInstaller)

This project can be bundled into a standalone Windows EXE with templates, static assets, and the DuckDB file included.

1. Build the executable using the spec file:
	- `pyinstaller --clean --noconfirm CensusSchoolData.spec`
2. The EXE will be in `dist/CensusSchoolData.exe`.

Note: the EXE is intended for Windows x64. If a target machine is missing the Microsoft Visual C++ runtime, install the VC++ Redistributable.

---

## 📁 Project Structure

```
Project/
├── pyproject.toml           # Package configuration
├── run_app.py               # Development entry point
├── census_app.duckdb        # Local DuckDB database
├── src/
│   └── census_app/          # Main package
│       ├── __init__.py
│       ├── core/            # Core utilities
│       │   ├── config.py    # Configuration & constants
│       │   ├── formatting.py
│       │   ├── geo_data.py  # DuckDB data access
│       │   ├── geo_ops.py   # Geospatial operations
│       │   ├── http_utils.py
│       │   └── mapbox.py    # Mapbox API helpers
│       └── web/             # Flask web app
│           ├── flask_app.py # App entry point
│           ├── school_data.py
│           ├── templates/
│           └── static/
├── data/                    # Data processing scripts
├── scripts/                 # Build/utility scripts
└── Competing_Schools/       # School data processing
```
