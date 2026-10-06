"""Shared pieces of the product pipeline: reading municipal value tables, validation and payloads.

A *payload* is the JSON document the dashboard and the exports use for one product version::

    {"type", "title", "subtitle", "issued", "period": {...}, "level", "source",
     "layers": [{"id", "label", "variable", "unit", "legend", "values": {area_key: {...}}}],
     "summary": {...}, "texts": {...}, "report": {...}}
"""
from __future__ import annotations

import re
from datetime import date, datetime

import pandas as pd

from .. import classes, reference
from ..envi import config
from ..envi.io_loader import (DatasetResult, _assign_rows, _finish, _identify_columns, _new_result, _norm_col,
                              read_any)

DEFAULT_DISCLAIMER = ("DA RFO CAR is not liable for any loss or damage arising from the use of this map. "
                      "Forecast values are indicative and valid only for the period and areas stated.")
# wording of the DA-RFO-CAR sample layouts (sample data/*.jpg)
WEATHER_DISCLAIMER = ("DA RFO CAR is not liable to any loss or damages arising from utilizing the Farm Weather Outlook "
                      "and Advisory. The forecast is valid only to the dates and municipality stated.")
MM_NOTE = ("1 mm of rainfall is equivalent to 1 liter of rain falling on 1 m² of land. Over one hectare, this "
           "corresponds to 10,000 liters of rainfall.")
ISSUING_OFFICE = "Department of Agriculture – Regional Field Office, Cordillera Administrative Region (AMIA Program)"


def cell_ref(row_idx: int, col) -> str:
    return f"row {row_idx + 2}, column {col}"


def parse_numeric_columns(df: pd.DataFrame, cols: list, report: dict, *, unit: str, max_warn: float | None = None,
                          roles: dict[int, str] | None = None) -> pd.DataFrame:
    """Convert value columns to numbers. Errors and warnings name the spreadsheet row and column.

    Rows whose role is not ``data`` (subtotals) are not checked.
    """
    out = pd.DataFrame(index=df.index)
    for c in cols:
        raw = df[c]
        txt = raw.astype(str).str.replace(",", "").str.strip()
        blank = raw.isna() | txt.isin(["", "nan", "None", "-", "NaN"])
        num = pd.to_numeric(txt.where(~blank), errors="coerce")
        for i in df.index:
            if roles is not None and roles.get(i, "data") != "data":
                continue
            if blank[i]:
                continue
            if pd.isna(num[i]):
                report["errors"].append(f"{cell_ref(i, c)}: '{raw[i]}' is not a number ({unit}).")
            elif num[i] < 0:
                report["errors"].append(f"{cell_ref(i, c)}: {num[i]:g} {unit} is negative; values must be ≥ 0.")
            elif max_warn is not None and num[i] > max_warn:
                report["warnings"].append(f"{cell_ref(i, c)}: {num[i]:g} {unit} is above {max_warn:g} {unit} – "
                                          "please check.")
        out[c] = num
    return out


def read_table(src, filename: str, dataset: str) -> tuple[pd.DataFrame | None, DatasetResult]:
    res = _new_result(dataset, filename)
    try:
        df, res.report["sheet"] = read_any(src, filename)
    except Exception as e:  # noqa: BLE001
        res.report["errors"].append(f"Could not read the file: {e}")
        return None, res
    df.columns = [str(c).strip() for c in df.columns]
    res.report["columns"] = list(df.columns)
    return df, res


def match_municipal_rows(df: pd.DataFrame, res: DatasetResult, values: pd.DataFrame, settings: dict,
                         dataset: str, text_cols: list[str] | None = None) -> bool:
    """Match rows to the gazetteer (municipal level), aggregate and fill the report. False if no name column."""
    gaz = reference.gazetteer()
    name_col, prov_col, psgc_col = _identify_columns(df)
    if name_col is None:
        res.report["errors"].append("Missing the MUNICIPALITY column.")
        return False
    level, rows, _ = _assign_rows(df, name_col, prov_col, psgc_col, gaz, settings.get("manual_matches"), dataset,
                                  force_level="municipal")
    res.level = level
    cols = list(values.columns)
    data = values.copy()
    for t in text_cols or []:
        data[t] = df[t]
    _finish(res, data, rows, cols, gaz, agg="sum", text_cols=text_cols)
    missing = res.report.get("missing_areas", [])
    if missing:
        res.report["warnings"].append(f"{len(missing)} of {reference.N_MUNICIPALITIES} municipalities are missing "
                                      "from the file and will be shown as “No data”: "
                                      + ", ".join(m["label"] for m in missing) + ".")
    return True


def row_roles(df: pd.DataFrame) -> dict[int, str]:
    """Pre-classify rows as data/subtotal so subtotal rows are not validated as values."""
    gaz = reference.gazetteer()
    name_col, _, _ = _identify_columns(df)
    if name_col is None:
        return {}
    from ..envi.io_loader import REGION_NAMES, clean_name
    provs = gaz.province_cleans
    out = {}
    for i, v in df[name_col].items():
        c = clean_name(v)
        out[i] = "subtotal" if (c in provs or c in REGION_NAMES) else ("blank" if c == "" else "data")
    return out


def find_col(df: pd.DataFrame, *aliases: str):
    cols = {_norm_col(c).replace(" ", "_"): c for c in df.columns}
    for a in aliases:
        if a in cols:
            return cols[a]
    return None


def layer(layer_id: str, label: str, variable: str, unit: str, legend: dict, series: pd.Series,
          extra: dict[str, pd.Series] | None = None) -> dict:
    """Build a dashboard layer for all 77 municipalities (missing → No data)."""
    keys = reference.gazetteer_table().area_key
    s = series.reindex(keys)
    labels, colors = classes.assign(s, legend)
    values = {}
    for k in keys:
        v = s[k]
        rec = {"value": None if pd.isna(v) else (round(float(v), 2) if not isinstance(v, str) else v),
               "class": labels[k], "color": colors[k]}
        for name, ser in (extra or {}).items():
            x = ser.get(k) if hasattr(ser, "get") else None
            rec[name] = None if x is None or (not isinstance(x, str) and pd.isna(x)) else (
                x if isinstance(x, str) else round(float(x), 2))
        values[k] = rec
    return {"id": layer_id, "label": label, "variable": variable, "unit": unit,
            "legend": classes.legend_with_counts(legend, labels), "values": values}


def numeric_summary(lyr: dict, n: int = 10, ascending: bool = False) -> dict:
    vals = [(k, v["value"]) for k, v in lyr["values"].items() if classes.is_finite(v["value"])]
    if not vals:
        return {"n": 0}
    s = pd.Series(dict(vals))
    top = s.sort_values(ascending=ascending).head(n)
    return {
        "n": int(len(s)), "min": float(s.min()), "max": float(s.max()), "mean": round(float(s.mean()), 1),
        "top": [{"area_key": k, "area": reference.area_label(k),
                 "province": reference.province_display(reference.province_of(k)), "value": float(v)}
                for k, v in top.items()],
        "class_counts": {c["label"]: c.get("count", 0) for c in lyr["legend"]["classes"]}
                        | {classes.NO_DATA: lyr["legend"]["no_data"].get("count", 0)},
    }


# ----------------------------------------------------------------- periods ---

MONTH_ABBR = {m[:3].upper(): i + 1 for i, m in enumerate(config.MONTHS)}


def to_date(v) -> date | None:
    if v in (None, ""):
        return None
    if isinstance(v, date):
        return v if not isinstance(v, datetime) else v.date()
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"'{v}' is not a date (use YYYY-MM-DD).")


def fmt_day(d: date) -> str:
    return f"{config.MONTHS[d.month - 1]} {d.day}, {d.year}"


def dekad_label(start: date, end: date) -> str:
    """'October 1–10, 2026' (or 'October 21 – November 1, 2026' across months)."""
    if start.year == end.year and start.month == end.month:
        return f"{config.MONTHS[start.month - 1]} {start.day}–{end.day}, {start.year}"
    if start.year == end.year:
        return f"{config.MONTHS[start.month - 1]} {start.day} – {config.MONTHS[end.month - 1]} {end.day}, {end.year}"
    return f"{fmt_day(start)} – {fmt_day(end)}"


def month_key_label(ym: str) -> str:
    return config.month_label(ym)


def parse_month_col(col, start_ym: str | None) -> str | None:
    """'OCT_2026' / 'October 2026' / '2026-10' / 'Oct' → 'YYYY-MM'. Year inferred from the season start."""
    k = _norm_col(col).replace("_", " ").replace("-", " ")
    m = re.fullmatch(r"(\d{4}) (\d{1,2})", k)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}"
    m = re.fullmatch(r"([A-Z]+)\.? ?(\d{4})?", k)
    if not m:
        return None
    word, year = m.group(1), m.group(2)
    month = None
    for full in config.MONTHS:
        if word == full.upper() or word == full[:3].upper() or (len(word) >= 3 and full.upper().startswith(word)):
            month = config.MONTHS.index(full) + 1
            break
    if month is None:
        return None
    if year is None:
        if not start_ym:
            return None
        sy, sm = (int(x) for x in start_ym.split("-")[:2])
        year = sy if month >= sm else sy + 1
    return f"{int(year):04d}-{month:02d}"


def base_texts(product: dict, settings: dict) -> dict:
    return {
        "title": settings.get("title") or product["title"],
        "subtitle": settings.get("subtitle") or product["subtitle"],
        "notes": settings.get("notes", ""),
        "disclaimer": settings.get("disclaimer") or DEFAULT_DISCLAIMER,
        "sources": settings.get("sources") or product.get("source", ""),
        "recommendations": settings.get("recommendations", ""),
        "issuing_office": ISSUING_OFFICE,
        "data_credit": settings.get("data_credit") or "DOST-PAGASA",   # "Weather data from: …" on the map
    }
