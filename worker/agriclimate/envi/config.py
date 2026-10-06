"""Project-wide constants and paths for the El Niño Vulnerability Index (ENVI)."""
from __future__ import annotations

import glob
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # worker/
# Sample inputs: the repo's "sample data/sample input" folder (DA-RFO-CAR), else the copy bundled with the worker
_REPO_SAMPLES = ROOT.parent / "sample data" / "sample input"
DATA_INPUT = Path(os.environ.get("SAMPLE_INPUT_DIR") or (_REPO_SAMPLES if _REPO_SAMPLES.exists()
                                                         else ROOT / "data" / "sample"))
GIS_DIR = ROOT / "data" / "gis"
GIS_TEMPLATE_DIR = ROOT / "data" / "gis_template"
QGZ_PATH = GIS_TEMPLATE_DIR / "drought_forecast.qgz"
QPT_PATH = GIS_TEMPLATE_DIR / "droug_forecast_layout_template.qpt"
ASSETS = ROOT / "assets"
LOGO_DIR = ASSETS / "logos"
FONT_DIR = ASSETS / "fonts"
FONT_FAMILY = "Montserrat"          # used in maps, presentation, Excel and the web UIs
OUTPUTS = Path(os.environ.get("OUTPUT_DIR", ROOT / "outputs"))

MUNI_SHP = GIS_DIR / "Regional_Map_Municipal_Boundary.shp"
PROV_SHP = GIS_DIR / "Regional_Map_Provincial_Boundary.shp"

# Default sample inputs (the files shipped in data/input/)
DEFAULT_FILES = {
    "drought": DATA_INPUT / "drought forecast.csv",
    "damage": DATA_INPUT / "historical damage.xlsx",
    "crops": DATA_INPUT / "standing crops ao sept 15 2026.xlsx",
}

# ---------------------------------------------------------------- labels ---
APP_TITLE = "El Niño Vulnerability Index (ENVI) – Cordillera Administrative Region (CAR)"
MAP_TITLE = "El Niño Vulnerability Index – CAR"

INDICATORS = {
    # key: (short label, long label, unit)
    "hazard": ("Drought forecast", "Drought forecast (PAGASA)", "score"),
    "damage": ("Historical damage", "Historical El Niño / drought crop damage", "ha"),
    "crops": ("Standing crops", "Standing crop area", "ha"),
}

CLASS_NAMES = ["Very Low", "Low", "Moderate", "High", "Very High"]
CLASS_COLORS = {
    "Very Low": "#1a9850",
    "Low": "#91cf60",
    "Moderate": "#fee08b",
    "High": "#fc8d59",
    "Very High": "#d73027",
}
NO_DATA_LABEL = "No data"
NO_DATA_COLOR = "#d9d9d9"

# Ordinal scale for categorical drought forecasts (PAGASA terminology).
# Higher = drier = more vulnerable.
DROUGHT_CATEGORY_SCORES = {
    "not affected": 0,
    "no": 0,
    "none": 0,
    "normal": 0,
    "near normal": 0,
    "dry condition": 1,
    "dry spell": 2,
    "drought": 3,
}
DROUGHT_MAX_SCORE = 3

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]

DEFAULT_SETTINGS = {
    # DA-RFO-CAR weighting: drought forecast 50 %, historical damage 25 %, standing crops 25 %
    "weights": {"hazard": 0.5, "damage": 0.25, "crops": 0.25},
    "classification": "equal",          # equal | quantile | jenks
    "hazard_numeric_mode": "rainfall_pct_normal",  # used only if the forecast is numeric
    "hazard_scaling": "minmax",         # minmax | fixed (score / max possible score)
    "missing_policy": "nodata",         # nodata | zero
    "layout": "qgz",                    # qgz (full DA layout) | qpt (compact template)
    "renderer": "auto",                 # auto | qgis | matplotlib
    "basemap": False,
    "manual_matches": {},               # {"dataset|raw name": "PROVINCE|MUNICIPALITY"}
    # reporting period (also collected by the upload portal)
    "reporting_month": "2026-09",       # month the report is issued ("as of"), YYYY-MM
    "period_start": "2026-10",          # first month covered by the data / forecast
    "period_end": "2027-03",            # last month covered
    "crops_as_of": "2026-09-15",        # standing crops inventory date, YYYY-MM-DD
    "recommendations": "",              # agricultural recommendations (free text, editable)
}


def month_label(ym: str) -> str:
    """'2026-10' -> 'October 2026' (returns the input unchanged if it is not YYYY-MM)."""
    try:
        y, m = (int(x) for x in str(ym).split("-")[:2])
        return f"{MONTHS[m - 1]} {y}"
    except (ValueError, IndexError):
        return str(ym or "")


def date_label(ymd: str) -> str:
    """'2026-09-15' -> 'September 15, 2026'."""
    try:
        y, m, d = (int(x) for x in str(ymd).split("-"))
        return f"{MONTHS[m - 1]} {d}, {y}"
    except (ValueError, IndexError):
        return str(ymd or "")


def period_labels(settings: dict | None = None) -> dict:
    """Human-readable period texts used on the map, presentation and exports."""
    s = {**DEFAULT_SETTINGS, **(settings or {})}
    period = f"{month_label(s['period_start'])} – {month_label(s['period_end'])}"
    issued = month_label(s["reporting_month"])
    return {
        "period": period,
        "issued": issued,
        "crops_as_of": date_label(s["crops_as_of"]),
        "subtitle": f"Outlook: {period} (as of {issued})",
    }


def find_qgis_python() -> str | None:
    """Locate a PyQGIS-enabled python launcher (python-qgis*.bat) on Windows."""
    env = os.environ.get("QGIS_PYTHON")
    if env and Path(env).exists():
        return env
    patterns = [
        r"C:\Program Files\QGIS*\bin\python-qgis*.bat",
        r"C:\OSGeo4W*\bin\python-qgis*.bat",
    ]
    hits: list[str] = []
    for p in patterns:
        hits.extend(glob.glob(p))
    if not hits:
        return None
    # prefer the newest install (sort by version-ish path), plain python-qgis over -ltr when both exist
    hits.sort(key=lambda s: (Path(s).parent.parent.name, "ltr" not in Path(s).name))
    return hits[-1]
