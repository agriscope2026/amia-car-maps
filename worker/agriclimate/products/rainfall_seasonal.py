"""Seasonal rainfall forecast in mm: one row per municipality, one column per month.

Template: PSGC, PROVINCE, MUNICIPALITY, OCT_2026 … MAR_2027, optional SEASON_TOTAL, NORMAL_MM, PCT_NORMAL.
Maps: one per month + the season total (+ % of normal when supplied or derivable).
"""
from __future__ import annotations

import pandas as pd

from .. import classes
from ..envi import config
from . import common

TYPE = "rainfall_seasonal"
TITLE = "Seasonal Rainfall Outlook – CAR"
DEFAULT_SOURCE = "DOST-PAGASA seasonal climate outlook; processed by DA-RFO-CAR AMIA"
MM_TO_LITRES_NOTE = common.MM_NOTE


def load(src, filename: str, settings: dict | None = None):
    settings = settings or {}
    df, res = common.read_table(src, filename, TYPE)
    rep = res.report
    if df is None:
        return res, None, []
    start_ym = (settings.get("period_start") or "")[:7] or None
    month_cols = {}
    for c in df.columns:
        if common.find_col(df[[c]], "SEASON_TOTAL", "NORMAL_MM", "PCT_NORMAL", "PSGC", "PROVINCE", "MUNICIPALITY"):
            continue
        ym = common.parse_month_col(c, start_ym)
        if ym:
            month_cols[c] = ym
    if not month_cols:
        rep["errors"].append("No month columns found. Name them like OCT_2026, NOV_2026 … MAR_2027 (values in mm).")
        return res, None, []
    dup = pd.Series(list(month_cols.values()))
    if dup.duplicated().any():
        rep["errors"].append(f"Month columns repeat: {sorted(set(dup[dup.duplicated()]))}.")
        return res, None, []
    months = sorted(set(month_cols.values()))
    expected = pd.period_range(months[0], months[-1], freq="M").strftime("%Y-%m").tolist()
    if expected != months:
        rep["warnings"].append("The months are not consecutive: " + ", ".join(sorted(set(expected) - set(months)))
                               + " missing.")
    total_col = common.find_col(df, "SEASON_TOTAL", "TOTAL", "SEASON_TOTAL_MM")
    normal_col = common.find_col(df, "NORMAL_MM", "NORMAL")
    pct_col = common.find_col(df, "PCT_NORMAL", "%_NORMAL", "PERCENT_NORMAL", "PCT_OF_NORMAL")
    roles = common.row_roles(df)
    max_month = float(settings.get("max_warn_mm") or 1500)
    nums = common.parse_numeric_columns(df, list(month_cols), rep, unit="mm", max_warn=max_month, roles=roles)
    values = pd.DataFrame({f"m_{ym}": nums[c] for c, ym in month_cols.items()})
    computed_total = values.sum(axis=1, min_count=1)
    if total_col is not None:
        t = common.parse_numeric_columns(df, [total_col], rep, unit="mm", roles=roles)[total_col]
        diff = (t - computed_total).abs()
        bad = [i for i in df.index if roles.get(i) == "data" and pd.notna(diff[i]) and diff[i] > 1.0]
        if bad:
            rep["warnings"].append(f"{total_col} differs from the sum of the months in {len(bad)} row(s) (e.g. "
                                   f"row {bad[0] + 2}); the value in {total_col} is used.")
        values["season_total"] = t.fillna(computed_total)
    else:
        values["season_total"] = computed_total
    if normal_col is not None:
        values["normal_mm"] = common.parse_numeric_columns(df, [normal_col], rep, unit="mm", roles=roles)[normal_col]
    if pct_col is not None:
        values["pct_normal"] = common.parse_numeric_columns(df, [pct_col], rep, unit="%", max_warn=400,
                                                            roles=roles)[pct_col]
    elif normal_col is not None:
        n = values["normal_mm"]
        values["pct_normal"] = (values["season_total"] / n.where(n > 0) * 100).round(0)
        rep["warnings"].append("PCT_NORMAL computed as SEASON_TOTAL ÷ NORMAL_MM × 100.")
    rep["months"] = months
    if rep["errors"]:
        return res, None, months
    if not common.match_municipal_rows(df, res, values, settings, TYPE):
        return res, None, months
    return res, res.data, months


def build(src, filename: str, settings: dict | None = None) -> dict:
    settings = settings or {}
    res, data, months = load(src, filename, settings)
    issued = common.to_date(settings.get("issue_date"))
    if issued is None:
        res.report["errors"].append("Set the issue date (“as of”).")
    payload = {"type": TYPE, "ok": res.ok, "report": res.report}
    if not res.ok or data is None:
        return payload
    season_label = f"{config.month_label(months[0])} – {config.month_label(months[-1])}"
    legends = settings.get("legends") or {}
    month_legend = classes.preset("rainfall_month", legends.get("rainfall_month"))
    season_legend = classes.preset("rainfall_season", legends.get("rainfall_season"))
    extra = {"season_total": data["season_total"]}
    if "pct_normal" in data:
        extra["pct_normal"] = data["pct_normal"]
    layers = [common.layer(f"m_{ym}", config.month_label(ym), "rainfall_mm", "mm", month_legend, data[f"m_{ym}"],
                           extra) for ym in months]
    layers.append(common.layer("season_total", f"Season total ({season_label})", "rainfall_mm", "mm",
                               season_legend, data["season_total"], extra))
    if "pct_normal" in data and data["pct_normal"].notna().any():
        layers.append(common.layer("pct_normal", f"% of normal ({season_label})", "pct_normal", "%",
                                   classes.preset("pct_normal"), data["pct_normal"], extra))
    payload.update({
        "title": TITLE,
        "subtitle": f"Outlook: {season_label} (as of {common.fmt_day(issued)})",
        "issued": issued.isoformat(),
        "period": {"kind": "season", "start": f"{months[0]}-01",
                   "end": (pd.Period(months[-1], "M").end_time.date()).isoformat(), "label": season_label,
                   "months": months},
        "level": "municipal",
        "source": settings.get("source") or DEFAULT_SOURCE,
        "layers": layers,
        "summary": {"season_total": common.numeric_summary(layers[len(months)]),
                    "months": {ym: {k: v for k, v in common.numeric_summary(l).items() if k != "top"}
                               for ym, l in zip(months, layers)}},
        "method": {"classes": "lower-inclusive (100 mm → 100–200 mm)", "pct_normal_thresholds":
                   "≤ 40 way below, 41–80 below, 81–120 near, > 120 above normal (to be confirmed with PAGASA)"},
    })
    payload["valid_text"] = f"Valid for {season_label} season"
    payload["texts"] = common.base_texts(payload, {"disclaimer": common.WEATHER_DISCLAIMER, **settings})
    payload["texts"].update({"legend_title": "Legend in millimeters (mm):",
                             "notes": payload["texts"]["notes"] or MM_TO_LITRES_NOTE})
    return payload
