"""Drought monitoring forecast (PAGASA DroughtCaster or the manual template): one map per outlook month.

Manual template (same as the prototype's ``drought forecast.csv``): ``ID, PROVINCE, October … March`` with the
PAGASA categories. A municipal table (``PROVINCE, MUNICIPALITY, <months>``) is accepted too. Provincial
values are applied to every municipality of the province so the dashboard can use one geometry set.
"""
from __future__ import annotations

import pandas as pd

from .. import classes, reference
from ..envi import config
from ..envi.io_loader import load_drought
from . import common

TYPE = "drought"
TITLE = "Drought Forecast – CAR"
DEFAULT_SOURCE = "DOST-PAGASA DroughtCaster / drought outlook; processed by DA-RFO-CAR AMIA"
CATEGORY_LABEL = {"not affected": "Not affected", "no": "Not affected", "none": "Not affected",
                  "normal": "Not affected", "near normal": "Not affected", "dry condition": "Dry condition",
                  "dry spell": "Dry spell", "drought": "Drought"}
DEFINITIONS = [
    ("Dry condition", "2 consecutive months of below-normal rainfall (21–60% reduction from average)"),
    ("Dry spell", "3 consecutive months of below-normal rainfall, or 2 consecutive months of way-below-normal "
                  "rainfall (more than 60% reduction)"),
    ("Drought", "3 consecutive months of way-below-normal rainfall, or 5 consecutive months of below-normal "
                "rainfall"),
]


def _months_to_ym(months: list[str], start_ym: str) -> list[str]:
    sy, sm = (int(x) for x in start_ym.split("-")[:2])
    out, y, prev = [], sy, None
    for m in months:
        mi = config.MONTHS.index(m) + 1
        if prev is not None and mi < prev:
            y += 1
        elif prev is None and mi < sm:
            y += 1
        out.append(f"{y:04d}-{mi:02d}")
        prev = mi
    return out


def build(src, filename: str, settings: dict | None = None) -> dict:
    settings = settings or {}
    gaz = reference.gazetteer()
    res = load_drought(src, filename, gaz, {**config.DEFAULT_SETTINGS, **settings})
    rep = res.report
    if res.ok and rep.get("hazard_type") != "categorical":
        rep["errors"].append("Drought values must be PAGASA categories (not affected / dry condition / dry spell / "
                             "drought), not numbers.")
    issued = common.to_date(settings.get("issue_date"))
    if issued is None:
        rep["errors"].append("Set the issue date (“as of”).")
    start_ym = (settings.get("period_start") or "")[:7]
    if not start_ym:
        rep["errors"].append("Set the first month of the outlook (period start).")
    payload = {"type": TYPE, "ok": res.ok, "report": rep}
    if not res.ok:
        return payload
    if res.level == "provincial":
        missing = sorted(set(gaz.prov.area_key) - set(res.data.index))
        if missing:
            rep["warnings"].append("Provinces missing (shown as “No data”): "
                                   + ", ".join(reference.province_display(p) for p in missing) + ".")
    months = rep["months"]
    yms = _months_to_ym(months, start_ym)
    keys = reference.gazetteer_table().area_key
    legend = classes.preset("drought")
    layers = []
    for m, ym in zip(months, yms):
        col = res.data[f"cat_{m}"].str.strip().str.lower().map(CATEGORY_LABEL)
        if res.level == "provincial":
            series = pd.Series({k: col.get(reference.province_of(k)) for k in keys})
        else:
            series = col.reindex(keys)
        layers.append(common.layer(f"m_{ym}", config.month_label(ym), "drought_category", "category", legend,
                                   series))
    label = f"{config.month_label(yms[0])} – {config.month_label(yms[-1])}"
    by_month = {}
    for ym, lyr in zip(yms, layers):
        provs = {}
        for k, v in lyr["values"].items():
            provs.setdefault(reference.province_display(reference.province_of(k)), v["class"])
        by_month[ym] = provs
    payload.update({
        "title": TITLE,
        "subtitle": f"Outlook: {label} (as of {common.fmt_day(issued)})",
        "issued": issued.isoformat(),
        "period": {"kind": "season", "start": f"{yms[0]}-01",
                   "end": pd.Period(yms[-1], "M").end_time.date().isoformat(), "label": label, "months": yms},
        "level": res.level,
        "source": settings.get("source") or DEFAULT_SOURCE,
        "layers": layers,
        "summary": {"by_month_province": by_month,
                    "class_counts": {ym: {c["label"]: c.get("count", 0) for c in l["legend"]["classes"]}
                                     for ym, l in zip(yms, layers)}},
        "method": {"definitions": [{"category": c, "definition": d} for c, d in DEFINITIONS],
                   "fetched_from": settings.get("fetched_from", "manual upload"),
                   "fetched_at": settings.get("fetched_at")},
    })
    payload["valid_text"] = f"Valid for the {label} outlook"
    payload["texts"] = common.base_texts(payload, settings)
    payload["texts"]["legend_title"] = "Legend (PAGASA drought categories)"
    if not payload["texts"]["notes"]:
        payload["texts"]["notes"] = " ".join(f"{c}: {d}." for c, d in DEFINITIONS)
    return payload
