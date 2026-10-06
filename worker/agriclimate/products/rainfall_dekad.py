"""10-day rainfall forecast in mm, one row per municipality: **one map per day** plus the 10-day total.

Template: PSGC, PROVINCE, MUNICIPALITY, DAY_1 … DAY_10 (daily rainfall, mm). DAY_1 is the first day of the
period. A single RAINFALL_MM column (10-day total) is still accepted, but then only the total map is made.
"""
from __future__ import annotations

import re
from datetime import timedelta

import pandas as pd

from .. import classes
from ..envi import config
from . import common

TYPE = "rainfall_dekad"
TITLE = "10-Day Rainfall Forecast – CAR"
DEFAULT_SOURCE = "DOST-PAGASA 10-day rainfall forecast; processed by DA-RFO-CAR AMIA"
DEFAULT_MAX_WARN_MM = 500.0
DAY_RE = re.compile(r"^DAY[ _]?(\d{1,2})$")
NOTE = common.MM_NOTE
DISCLAIMER = common.WEATHER_DISCLAIMER


def load(src, filename: str, settings: dict | None = None):
    """Return (DatasetResult, DataFrame indexed by area_key with ``total`` and ``day_1`` … columns)."""
    settings = settings or {}
    df, res = common.read_table(src, filename, TYPE)
    rep = res.report
    if df is None:
        return res, None
    total_col = common.find_col(df, "RAINFALL_MM", "RAINFALL", "RAINFALL_(MM)", "TOTAL_MM", "TOTAL")
    day_cols = sorted([c for c in df.columns if DAY_RE.match(str(c).upper().strip())],
                      key=lambda c: int(DAY_RE.match(str(c).upper().strip()).group(1)))
    if total_col is None and not day_cols:
        rep["errors"].append("Missing the rainfall columns: add DAY_1 … DAY_10 (daily rainfall in mm), or "
                             "RAINFALL_MM (10-day total in mm).")
        return res, None
    max_warn = float(settings.get("max_warn_mm") or DEFAULT_MAX_WARN_MM)
    roles = common.row_roles(df)
    values = pd.DataFrame(index=df.index)
    if day_cols:
        nums = common.parse_numeric_columns(df, day_cols, rep, unit="mm", max_warn=max_warn / 2, roles=roles)
        for i, c in enumerate(day_cols, 1):
            values[f"day_{i}"] = nums[c]
        rep["days"] = len(day_cols)
        if len(day_cols) not in (10, 11):
            rep["warnings"].append(f"{len(day_cols)} daily columns found; a 10-day forecast normally has 10.")
    if total_col is not None:
        t = common.parse_numeric_columns(df, [total_col], rep, unit="mm", max_warn=max_warn, roles=roles)[total_col]
        if day_cols:
            summed = values.sum(axis=1, min_count=1)
            bad = [i for i in df.index if roles.get(i) == "data" and pd.notna(t[i]) and pd.notna(summed[i])
                   and abs(t[i] - summed[i]) > 1]
            if bad:
                rep["warnings"].append(f"{total_col} differs from the sum of the daily columns in {len(bad)} row(s) "
                                       f"(e.g. row {bad[0] + 2}); {total_col} is used for the 10-day total.")
        values["total"] = t
        rep["rainfall_note"] = f"10-day total from column {total_col} (mm)."
    else:
        values["total"] = values.sum(axis=1, min_count=1)
        rep["rainfall_note"] = f"10-day total = sum of the {len(day_cols)} daily values (mm)."
    if not day_cols:
        rep["warnings"].append("Only a 10-day total was given, so no daily maps can be made. Use the DAY_1 … DAY_10 "
                               "columns of the template for one map per day.")
    if rep["errors"]:
        return res, None
    blanks = [i for i in df.index if roles.get(i) == "data" and pd.isna(values["total"][i])]
    if blanks:
        rep["warnings"].append(f"{len(blanks)} row(s) have no rainfall value and will be shown as “No data” "
                               f"(rows {', '.join(str(i + 2) for i in blanks[:10])}{'…' if len(blanks) > 10 else ''}).")
    if not common.match_municipal_rows(df, res, values, settings, TYPE):
        return res, None
    return res, res.data


def day_label(d) -> str:
    """'September 24' (the year is in the validity line)."""
    return f"{config.MONTHS[d.month - 1]} {d.day}"


def build(src, filename: str, settings: dict | None = None) -> dict:
    """Validate the upload and build the preview payload (daily layers first, then the 10-day total)."""
    settings = settings or {}
    res, data = load(src, filename, settings)
    start = common.to_date(settings.get("period_start"))
    end = common.to_date(settings.get("period_end"))
    if start is None or end is None:
        res.report["errors"].append("Set the forecast dates (period start and end).")
    elif end < start:
        res.report["errors"].append("The end date is before the start date.")
    elif (end - start).days > 11:
        res.report["warnings"].append(f"The period covers {(end - start).days + 1} days; a 10-day forecast has 10.")
    issued = common.to_date(settings.get("issue_date"))
    if issued is None:
        res.report["errors"].append("Set the issue date (“as of”).")
    n_days = res.report.get("days", 0)
    if start and end and n_days and (end - start).days + 1 != n_days:
        res.report["warnings"].append(f"The file has {n_days} daily columns but the period has "
                                      f"{(end - start).days + 1} days; DAY_1 is taken as {common.fmt_day(start)}.")
    payload = {"type": TYPE, "ok": res.ok, "report": res.report}
    if not res.ok or data is None:
        return payload
    period_label = common.dekad_label(start, end)
    first = day_label(start) if start.year == end.year else common.fmt_day(start)
    valid = f"Valid from {first} – {common.fmt_day(end)}"          # "Valid from September 24 – October 3, 2026"
    legend = classes.preset("rainfall_dekad", settings.get("legend"))
    layers = []
    for i in range(1, n_days + 1):
        d = start + timedelta(days=i - 1)
        lyr = common.layer(f"d_{d.isoformat()}", day_label(d), "rainfall_mm", "mm", legend, data[f"day_{i}"],
                           {"total": data["total"]})
        lyr["date"] = d.isoformat()
        layers.append(lyr)
    total = common.layer("total", f"10-day total ({period_label})", "rainfall_mm", "mm", legend, data["total"])
    layers.append(total)
    payload.update({
        "title": TITLE,
        "subtitle": f"Forecast rainfall for {period_label} (as of {common.fmt_day(issued)})",
        "issued": issued.isoformat(),
        "period": {"kind": "dekad", "start": start.isoformat(), "end": end.isoformat(), "label": period_label,
                   "days": [lyr["date"] for lyr in layers if "date" in lyr]},
        "valid_text": valid,
        "level": "municipal",
        "source": settings.get("source") or DEFAULT_SOURCE,
        "layers": layers,
        "summary": {"total": common.numeric_summary(total), "driest": common.numeric_summary(total, ascending=True),
                    "days": {lyr["date"]: {k: v for k, v in common.numeric_summary(lyr).items() if k != "top"}
                             for lyr in layers if "date" in lyr}},
        "method": {"note": res.report.get("rainfall_note", ""),
                   "classes": "lower-inclusive (5 mm → 5–15 mm); DA-RFO-CAR daily rainfall categories",
                   "max_warn_mm": float(settings.get("max_warn_mm") or DEFAULT_MAX_WARN_MM)},
    })
    payload["texts"] = common.base_texts(payload, {"disclaimer": DISCLAIMER, **settings})
    payload["texts"]["legend_title"] = "LEGEND in millimeters (mm):"
    payload["texts"]["notes"] = payload["texts"]["notes"] or NOTE
    return payload


def main_layer_id(payload: dict) -> str:
    return "total"
