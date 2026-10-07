"""Downloadable input templates, pre-filled with every CAR municipality, each with a README sheet."""
from __future__ import annotations

import io

import pandas as pd

from . import reference
from .envi import config
from .envi.io_loader import write_templates as write_envi_templates

TEMPLATE_INFO = {
    "rainfall_dekad": ("rainfall_10day_template.xlsx", [
        "10-day rainfall forecast – one row per municipality (all 77 are listed).",
        "DAY_1 … DAY_10: forecast rainfall for each day in millimetres (mm), ≥ 0. DAY_1 is the first day of the "
        "period you enter in the wizard. One map is made per day, plus the 10-day total.",
        "Alternative: a single RAINFALL_MM column (10-day total) – then only the total map is made.",
        "PSGC and PROVINCE help name matching – keep them. Leave a cell blank for “No data”.",
        "Enter the dekad dates, issue date and source in the upload wizard.",
    ]),
    "rainfall_seasonal": ("rainfall_seasonal_template.xlsx", [
        "Seasonal rainfall forecast – one row per municipality, one column per month (e.g. OCT_2026), in mm.",
        "Optional: SEASON_TOTAL (mm; otherwise the months are summed), NORMAL_MM (mm) and PCT_NORMAL (% of normal).",
        "If only NORMAL_MM is given, % of normal = SEASON_TOTAL ÷ NORMAL_MM × 100.",
        "1 mm of rainfall = 1 litre per square metre.",
    ]),
    "drought": ("drought_forecast_template.csv", []),
    "irrigation": ("irrigation_sources_template.xlsx", [
        "One row per irrigation source / dam. LAT and LON in decimal degrees (WGS 84), e.g. 17.4123, 120.9876.",
        "TYPE: NIS (national irrigation system), CIS (communal), SWIP, SSIP, DAM, RIVER or OTHER – a new type is "
        "also accepted (it gets its own colour in the dashboard); optional TYPE_LABEL column gives it a full name.",
        "SERVICE_AREA_HA: service area in hectares (ha). STATUS: Operational, Non-operational, "
        "Under construction, For rehabilitation, Proposed, Unknown.",
        "Service-area polygons can be uploaded separately as GeoJSON.",
    ]),
}


def _months(period_start: str, period_end: str) -> list[str]:
    return pd.period_range(period_start[:7], period_end[:7], freq="M").strftime("%Y-%m").tolist()


def _base_rows() -> pd.DataFrame:
    g = reference.gazetteer_table()
    return pd.DataFrame({"PSGC": g.psgc.values, "PROVINCE": g.province_label.values, "MUNICIPALITY": g.label.values})


def _xlsx(df: pd.DataFrame, notes: list[str], sheet: str = "DATA") -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as xw:
        df.to_excel(xw, sheet_name=sheet, index=False)
        pd.DataFrame({"README": notes}).to_excel(xw, sheet_name="README", index=False)
        from openpyxl.styles import Font
        for ws in xw.book.worksheets:
            for row in ws.iter_rows():
                for c in row:
                    c.font = Font(name=config.FONT_FAMILY, bold=c.row == 1)
            ws.column_dimensions["A"].width = 16 if ws.title == sheet else 120
            for col in ("B", "C"):
                ws.column_dimensions[col].width = 22
    return buf.getvalue()


def template(kind: str, period_start: str = "2026-10", period_end: str = "2027-03") -> tuple[str, bytes]:
    """Return (filename, bytes) for a template."""
    if kind == "rainfall_dekad":
        df = _base_rows()
        for i in range(1, 11):
            df[f"DAY_{i}"] = None
        return TEMPLATE_INFO[kind][0], _xlsx(df, TEMPLATE_INFO[kind][1])
    if kind == "rainfall_seasonal":
        df = _base_rows()
        for ym in _months(period_start, period_end):
            df[pd.Period(ym, "M").strftime("%b_%Y").upper()] = None
        for c in ("SEASON_TOTAL", "NORMAL_MM", "PCT_NORMAL"):
            df[c] = None
        return TEMPLATE_INFO[kind][0], _xlsx(df, TEMPLATE_INFO[kind][1])
    if kind == "drought":
        prov = reference.province_table()
        df = pd.DataFrame({"ID": prov.objectid.values, "PROVINCE": prov.label.values})
        for ym in _months(period_start, period_end):
            df[config.month_label(ym).split()[0]] = ""
        return TEMPLATE_INFO[kind][0], df.to_csv(index=False).encode("utf-8-sig")
    if kind == "irrigation":
        df = pd.DataFrame(columns=["NAME", "TYPE", "LAT", "LON", "MUNICIPALITY", "PROVINCE", "RIVER",
                                   "SERVICE_AREA_HA", "STATUS", "SOURCE"])
        return TEMPLATE_INFO[kind][0], _xlsx(df, TEMPLATE_INFO[kind][1])
    if kind in ("envi_damage", "envi_crops", "envi_drought", "crops"):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            paths = write_envi_templates(Path(d), reference.gazetteer())
            p = {"envi_drought": paths[0], "envi_damage": paths[1], "envi_crops": paths[2], "crops": paths[2]}[kind]
            return p.name, p.read_bytes()
    raise KeyError(f"Unknown template '{kind}'")


TEMPLATE_KINDS = ["rainfall_dekad", "rainfall_seasonal", "drought", "irrigation", "envi_drought", "envi_damage",
                  "envi_crops"]
