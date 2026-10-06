"""Reference layers maintained by the admin: standing crops (per date) and irrigation sources / dams."""
from __future__ import annotations

import io
import json
import re

import pandas as pd

from .. import reference
from ..envi.io_loader import load_crops
from . import common

IRRIGATION_TYPES = {
    "NIS": "National Irrigation System (NIA)",
    "CIS": "Communal Irrigation System (NIA)",
    "SWIP": "Small Water Impounding Project",
    "SSIP": "Small-Scale Irrigation Project",
    "DAM": "Dam",
    "OTHER": "Other irrigation source",
}
STATUSES = {"OPERATIONAL", "NON-OPERATIONAL", "UNDER CONSTRUCTION", "FOR REHABILITATION", "PROPOSED", "UNKNOWN"}
# CAR bounding box with a margin (EPSG:4326)
CAR_BBOX = (120.3, 15.9, 121.75, 18.6)


# ------------------------------------------------------------------ crops ---

# default colours per crop (the admin can change them); other crops take the next palette colour
CROP_DEFAULT_COLORS = {"Rice": "#2e7d32", "Corn": "#e0a100"}
CROP_PALETTE = ["#1565c0", "#7b3fa0", "#c62828", "#00838f", "#6d4c41", "#ef6c00", "#ad1457", "#558b2f", "#283593",
                "#9e9d24"]
_NAME_NOISE = re.compile(r"\b(total|totals|standing|area|areas|hectares?|ha|crops?|planted|\(ha\)|in ha)\b", re.I)
_NAME_COLS = ("MUNICIPALITY_CLEAN", "MUNICIPALITY", "MUNICIPALITY/CITY", "CITY/MUNICIPALITY", "LGU", "AREA", "NAME",
              "MUN_NAME", "PROVINCE")


def crop_name(column: str) -> str:
    """'Corn Total' → 'Corn', 'Coffee (ha)' → 'Coffee', 'HIGH VALUE CROPS AREA' → 'High Value', 'Total' → ''."""
    n = re.sub(r"[_]+", " ", str(column))
    n = re.sub(r"\(.*?\)", " ", n)
    n = _NAME_NOISE.sub(" ", n)
    n = re.sub(r"\s+", " ", n).strip(" -:/")
    return n.title() if n else ""


def default_colors(crops: list[str], existing: dict | None = None) -> dict[str, str]:
    out, used = {}, set((existing or {}).values())
    pal = [c for c in CROP_PALETTE if c not in used]
    for c in crops:
        if existing and existing.get(c):
            out[c] = existing[c]
        elif c in CROP_DEFAULT_COLORS:
            out[c] = CROP_DEFAULT_COLORS[c]
        else:
            out[c] = pal.pop(0) if pal else CROP_PALETTE[len(out) % len(CROP_PALETTE)]
    return out


def _with_header_row(src, filename: str):
    """Spreadsheets often start with title rows: use the first row that holds a municipality/area column."""
    if not filename.lower().endswith((".xlsx", ".xlsm", ".xls")):
        return src, filename
    raw = src if isinstance(src, (bytes, bytearray)) else open(src, "rb").read()
    first = pd.read_excel(io.BytesIO(raw), header=None, nrows=15)
    for i, row in first.iterrows():
        cells = {str(v).strip().upper() for v in row.values if pd.notna(v)}
        if cells & set(_NAME_COLS):
            if i == 0:
                return raw, filename
            df = pd.read_excel(io.BytesIO(raw), header=i)
            buf = io.BytesIO()
            df.to_excel(buf, index=False)
            return buf.getvalue(), filename
    return raw, filename


def build_crops(src, filename: str, settings: dict | None = None) -> dict:
    """Standing crops (ha) per municipality → {as_of, crops, colors, values: {area_key: {crop: ha}}, report}.

    Every numeric column is a crop (Rice, Corn, Coffee, Vegetables …); a plain "Total" column is ignored.
    """
    settings = settings or {}
    src, filename = _with_header_row(src, filename)
    res = load_crops(src, filename, reference.gazetteer(), settings)
    rep = res.report
    as_of = common.to_date(settings.get("as_of") or settings.get("crops_as_of"))
    if as_of is None:
        rep["errors"].append("Set the “as of” date of the standing crops inventory.")
    out = {"type": "crops", "ok": res.ok, "report": rep}
    if not res.ok:
        return out
    cols = dict(zip(rep.get("crop_columns", []), [c for c in res.data.columns if c.startswith("crop_")]))
    names: dict[str, str] = {}
    for original, col in cols.items():
        name = crop_name(original)
        if not name:
            rep["warnings"].append(f"Column '{original}' looks like a total of all crops and is not shown as a crop.")
            continue
        if name in names.values():
            name = f"{name} ({original})"
        names[col] = name
    if not names:
        rep["errors"].append("No crop columns found (e.g. Rice, Corn, Coffee – area in hectares).")
        out["ok"] = False
        return out
    values = {}
    for k in reference.gazetteer_table().area_key:
        if k in res.data.index:
            values[k] = {names[c]: round(float(res.data.at[k, c]), 2) for c in names
                         if pd.notna(res.data.at[k, c])}
    crops = list(names.values())
    out.update({"as_of": as_of.isoformat(), "crops": crops, "unit": "ha", "values": values,
                "colors": default_colors(crops, settings.get("colors")),
                "totals": {names[c]: round(float(res.data[c].sum()), 2) for c in names}})
    return out


# ------------------------------------------------------------- irrigation ---

def _in_car(lon: float, lat: float) -> bool:
    x0, y0, x1, y1 = CAR_BBOX
    return x0 <= lon <= x1 and y0 <= lat <= y1


def build_irrigation(src, filename: str, settings: dict | None = None) -> dict:
    """CSV/XLSX (NAME, TYPE, LAT, LON, MUNICIPALITY, RIVER, SERVICE_AREA_HA, STATUS, SOURCE) or GeoJSON."""
    rep = {"dataset": "irrigation", "filename": filename, "errors": [], "warnings": []}
    if filename.lower().endswith((".geojson", ".json")):
        return _irrigation_geojson(src, rep)
    df, res = common.read_table(src, filename, "irrigation")
    rep = res.report
    if df is None:
        return {"type": "irrigation", "ok": False, "report": rep}
    cols = {k: common.find_col(df, *a) for k, a in {
        "name": ("NAME", "PROJECT_NAME", "SYSTEM_NAME"), "type": ("TYPE", "CATEGORY"),
        "lat": ("LAT", "LATITUDE", "Y"), "lon": ("LON", "LONG", "LONGITUDE", "X"),
        "municipality": ("MUNICIPALITY",), "province": ("PROVINCE",), "river": ("RIVER", "WATER_SOURCE"),
        "service_area_ha": ("SERVICE_AREA_HA", "SERVICE_AREA", "AREA_HA"), "status": ("STATUS",),
        "source": ("SOURCE", "DATA_SOURCE")}.items()}
    for req in ("name", "type", "lat", "lon"):
        if cols[req] is None:
            rep["errors"].append(f"Missing the {req.upper()} column.")
    if rep["errors"]:
        return {"type": "irrigation", "ok": False, "report": rep}
    feats = []
    for i, r in df.iterrows():
        name = str(r[cols["name"]]).strip()
        if not name or name.lower() == "nan":
            continue
        try:
            lat, lon = float(r[cols["lat"]]), float(r[cols["lon"]])
        except (TypeError, ValueError):
            rep["errors"].append(f"{common.cell_ref(i, cols['lat'])}: LAT/LON must be decimal degrees.")
            continue
        if not _in_car(lon, lat):
            if _in_car(lat, lon):
                rep["errors"].append(f"Row {i + 2} ({name}): LAT and LON look swapped.")
            else:
                rep["errors"].append(f"Row {i + 2} ({name}): {lat:.4f}, {lon:.4f} is outside CAR.")
            continue
        typ = str(r[cols["type"]]).strip().upper()
        typ = {"NATIONAL": "NIS", "COMMUNAL": "CIS"}.get(typ, typ)
        if typ not in IRRIGATION_TYPES:
            rep["warnings"].append(f"Row {i + 2} ({name}): type '{r[cols['type']]}' is not one of "
                                   f"{', '.join(IRRIGATION_TYPES)}; saved as OTHER.")
            typ = "OTHER"
        props = {"name": name, "type": typ, "type_label": IRRIGATION_TYPES[typ]}
        for k in ("municipality", "province", "river", "status", "source"):
            v = r[cols[k]] if cols[k] is not None else None
            props[k] = None if v is None or pd.isna(v) or str(v).strip() == "" else str(v).strip()
        if props["status"] and props["status"].upper() not in STATUSES:
            rep["warnings"].append(f"Row {i + 2} ({name}): unknown status '{props['status']}'.")
        sa = r[cols["service_area_ha"]] if cols["service_area_ha"] is not None else None
        sa_num = pd.to_numeric(pd.Series([sa]), errors="coerce").iloc[0]
        if sa is not None and pd.notna(sa) and str(sa).strip() != "" and pd.isna(sa_num):
            rep["errors"].append(f"{common.cell_ref(i, cols['service_area_ha'])}: '{sa}' is not a number (ha).")
        props["service_area_ha"] = None if pd.isna(sa_num) else float(sa_num)
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 6),
                                                                                         round(lat, 6)]},
                      "properties": props})
    return {"type": "irrigation", "ok": not rep["errors"], "report": rep,
            "geojson": {"type": "FeatureCollection", "features": feats},
            "counts": pd.Series([f["properties"]["type"] for f in feats]).value_counts().to_dict() if feats else {}}


def _irrigation_geojson(src, rep) -> dict:
    raw = src if isinstance(src, (bytes, bytearray)) else open(src, "rb").read()
    try:
        gj = json.load(io.BytesIO(raw))
    except ValueError as e:
        rep["errors"].append(f"Not valid GeoJSON: {e}")
        return {"type": "irrigation", "ok": False, "report": rep}
    feats = gj.get("features", []) if gj.get("type") == "FeatureCollection" else []
    if not feats:
        rep["errors"].append("The GeoJSON has no features (expected a FeatureCollection).")
    points, polys = [], []
    for i, f in enumerate(feats, 1):
        p = f.get("properties") or {}
        if not p.get("name") and not p.get("NAME"):
            rep["warnings"].append(f"Feature {i} has no name.")
        p = {k.lower(): v for k, v in p.items()}
        typ = str(p.get("type", "OTHER")).upper()
        p["type"] = typ if typ in IRRIGATION_TYPES else "OTHER"
        p["type_label"] = IRRIGATION_TYPES[p["type"]]
        f = {**f, "properties": p}
        gt = (f.get("geometry") or {}).get("type")
        (points if gt == "Point" else polys if gt in ("Polygon", "MultiPolygon") else []).append(f)
    return {"type": "irrigation", "ok": not rep["errors"], "report": rep,
            "geojson": {"type": "FeatureCollection", "features": points},
            "service_areas": {"type": "FeatureCollection", "features": polys}}
