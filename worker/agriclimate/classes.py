"""Legends and class assignment for graduated (mm, %) and categorical (drought, ENVI) maps.

Graduated classes are **lower-inclusive**: a value equal to a break belongs to the class that starts at
that break (10 mm → "10–25"). The last class is open-ended ("> 200"). The % of normal legend follows
PAGASA's wording, which is **upper-inclusive** (40 % → "way below normal", 41 % → "below normal").
"""
from __future__ import annotations

import math
from copy import deepcopy

import numpy as np
import pandas as pd

from .envi import config

NO_DATA = config.NO_DATA_LABEL
NO_DATA_COLOR = config.NO_DATA_COLOR

# Dry → wet (brown/yellow → green → blue); colour-blind safe (BrBG/GnBu family).
RAIN_PALETTE_7 = ["#8c510a", "#d8b365", "#f6e8c3", "#c7eae5", "#5ab4ac", "#2b8cbe", "#08306b"]


def _fmt(v: float) -> str:
    return f"{v:g}" if float(v).is_integer() else f"{v:.1f}"


def graduated(legend_id: str, title: str, unit: str, breaks: list[float], colors: list[str],
              labels: list[str] | None = None, closed: str = "left", descs: list[str] | None = None) -> dict:
    """Build a graduated legend from ``n`` breaks (lower bounds) → ``n`` classes; the last is open."""
    if len(colors) != len(breaks):
        raise ValueError("Need one colour per class (one per lower break).")
    if any(b2 <= b1 for b1, b2 in zip(breaks, breaks[1:])):
        raise ValueError("Class breaks must be strictly increasing.")
    classes = []
    for i, lo in enumerate(breaks):
        hi = breaks[i + 1] if i + 1 < len(breaks) else None
        default = f"> {_fmt(lo)}" if hi is None else f"{_fmt(lo)}–{_fmt(hi)}"
        c = {"label": (labels[i] if labels else default), "lo": lo, "hi": hi, "color": colors[i]}
        if descs:
            c["desc"] = descs[i]
        classes.append(c)
    return {"id": legend_id, "kind": "graduated", "title": title, "unit": unit, "closed": closed,
            "classes": classes, "no_data": {"label": NO_DATA, "color": NO_DATA_COLOR}}


def categorical(legend_id: str, title: str, unit: str, items: list[tuple[str, str]]) -> dict:
    return {"id": legend_id, "kind": "categorical", "title": title, "unit": unit,
            "classes": [{"label": k, "color": c} for k, c in items],
            "no_data": {"label": NO_DATA, "color": NO_DATA_COLOR}}


# DA-RFO-CAR map legends (from the official sample layouts in "sample data/").
DAILY_RAIN_BREAKS = [0, 5, 15, 37.5, 75, 150, 250, 400]
DAILY_RAIN_COLORS = ["#9aa6b2", "#22c3e6", "#8dc95b", "#ffff4f", "#ffa51d", "#e8322f", "#e8448e", "#a64ac9"]
DAILY_RAIN_DESCS = ["No Rain", "Very Light Rain", "Light Rain", "Moderate Rain", "Heavy Rain", "Intense Rain",
                    "Torrential Rain", "Extreme Rain"]
MONTH_RAIN_BREAKS = [0, 50, 100, 200, 300, 400, 500]
MONTH_RAIN_COLORS = ["#d9d9d9", "#cfe6ff", "#1fbdf8", "#0a6fd6", "#00319c", "#001a4d", "#262626"]
MONTH_RAIN_DESCS = ["Minimal Rainfall", "Light Rainfall", "Moderate Rainfall", "Moderate to Heavy Rainfall",
                    "Heavy Rainfall", "Very Heavy Rainfall", "Extreme Rainfall"]

PRESETS: dict[str, dict] = {
    # daily maps and the 10-day total of the 10-day forecast
    "rainfall_dekad": graduated("rainfall_dekad", "10-day rainfall forecast", "mm", DAILY_RAIN_BREAKS,
                                DAILY_RAIN_COLORS, descs=DAILY_RAIN_DESCS),
    "rainfall_month": graduated("rainfall_month", "Monthly rainfall forecast", "mm", MONTH_RAIN_BREAKS,
                                MONTH_RAIN_COLORS, descs=MONTH_RAIN_DESCS),
    "rainfall_season": graduated("rainfall_season", "Seasonal rainfall total", "mm",
                                 [0, 300, 600, 900, 1200, 1500, 2000], MONTH_RAIN_COLORS, descs=MONTH_RAIN_DESCS),
    # PAGASA terms; thresholds to be confirmed against PAGASA's current legend (see docs §12).
    "pct_normal": graduated("pct_normal", "Rainfall, % of normal", "%", [0, 40, 80, 120],
                            ["#a6611a", "#dfc27d", "#e0e0e0", "#4393c3"],
                            ["Way below normal (≤ 40%)", "Below normal (41–80%)", "Near normal (81–120%)",
                             "Above normal (> 120%)"], closed="right"),
    "drought": categorical("drought", "Drought forecast", "category", [
        ("Not affected", "#ffffff"), ("Dry condition", "#ffeb89"), ("Dry spell", "#ff9501"),
        ("Drought", "#e5383b")]),
    "envi": categorical("envi", "El Niño Vulnerability Index", "class",
                        [(n, config.CLASS_COLORS[n]) for n in config.CLASS_NAMES]),
}


def preset(legend_id: str, override: dict | None = None) -> dict:
    """A copy of a preset legend, optionally with admin-edited breaks/colours/labels."""
    lg = deepcopy(PRESETS[legend_id])
    if override and lg["kind"] == "graduated" and override.get("breaks"):
        lg = graduated(legend_id, override.get("title", lg["title"]), lg["unit"], list(override["breaks"]),
                       list(override.get("colors") or _resample(RAIN_PALETTE_7, len(override["breaks"]))),
                       override.get("labels"), lg["closed"])
    return lg


def _resample(colors: list[str], n: int) -> list[str]:
    if n <= len(colors):
        idx = np.round(np.linspace(0, len(colors) - 1, n)).astype(int)
        return [colors[i] for i in idx]
    return colors + [colors[-1]] * (n - len(colors))


def assign(values: pd.Series, legend: dict) -> tuple[pd.Series, pd.Series]:
    """Return (class label, colour) per value. NaN → No data."""
    if legend["kind"] == "categorical":
        lut = {c["label"].lower(): c for c in legend["classes"]}
        lab = values.map(lambda v: lut[str(v).strip().lower()]["label"]
                         if isinstance(v, str) and str(v).strip().lower() in lut else NO_DATA)
    else:
        v = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
        lows = np.array([c["lo"] for c in legend["classes"]], dtype=float)
        side = "right" if legend.get("closed", "left") == "left" else "left"
        idx = np.clip(np.searchsorted(lows, v, side=side) - 1, 0, len(lows) - 1)
        names = np.array([c["label"] for c in legend["classes"]], dtype=object)[idx]
        names[np.isnan(v)] = NO_DATA
        lab = pd.Series(names, index=values.index)
    colors = {c["label"]: c["color"] for c in legend["classes"]} | {NO_DATA: NO_DATA_COLOR}
    return lab, lab.map(colors)


def counts(labels: pd.Series, legend: dict) -> dict[str, int]:
    vc = labels.value_counts().to_dict()
    out = {c["label"]: int(vc.get(c["label"], 0)) for c in legend["classes"]}
    out[NO_DATA] = int(vc.get(NO_DATA, 0))
    return out


def legend_with_counts(legend: dict, labels: pd.Series) -> dict:
    lg = deepcopy(legend)
    cnt = counts(labels, legend)
    for c in lg["classes"]:
        c["count"] = cnt[c["label"]]
    lg["no_data"]["count"] = cnt[NO_DATA]
    return lg


def is_finite(v) -> bool:
    try:
        return v is not None and math.isfinite(float(v))
    except (TypeError, ValueError):
        return False
