"""ENVI – El Niño Vulnerability Index: the prototype's method wrapped as a portal product.

Inputs (dataset → file): ``drought`` (provincial monthly categories), ``damage`` (historical damage, ha),
``crops`` (standing crops, ha). Exports reuse the prototype pipeline (``envi.pipeline.run``).
"""
from __future__ import annotations

import pandas as pd

from .. import classes, reference
from ..envi import config, index, io_loader, recommendations
from ..envi.pipeline import merged_settings
from . import common

TYPE = "envi"
TITLE = "El Niño Vulnerability Index – CAR"
DEFAULT_SOURCE = ("DOST-PAGASA drought forecast; DA-RFO-CAR historical El Niño damage and standing crops. "
                  "Index: DA-RFO-CAR AMIA")


def compute(files: dict, settings: dict | None = None):
    """files: {dataset: (bytes|path, filename)} → (results, df, meta, settings) – df/meta None if invalid."""
    s = merged_settings(_envi_settings(settings or {}))
    gaz = reference.gazetteer()
    results = io_loader.load_all(files, gaz, s)
    if not all(r.ok for r in results.values()):
        return results, None, None, s
    df, meta = index.compute_envi(results, gaz, s)
    return results, df, meta, s


def _envi_settings(settings: dict) -> dict:
    """Map portal period settings onto the prototype's names."""
    out = dict(settings)
    if settings.get("issue_date"):
        out.setdefault("reporting_month", settings["issue_date"][:7])
    if settings.get("period_start"):
        out["period_start"] = settings["period_start"][:7]
    if settings.get("period_end"):
        out["period_end"] = settings["period_end"][:7]
    return out


def build(files: dict, settings: dict | None = None) -> dict:
    settings = settings or {}
    results, df, meta, s = compute(files, settings)
    report = {k: r.report for k, r in results.items()}
    ok = df is not None
    payload = {"type": TYPE, "ok": ok, "report": report}
    if not ok:
        return payload
    keys = reference.gazetteer_table().area_key
    t = df.set_index("area_key")
    crop_cols = [c for c in t.columns if c.startswith("crop_")]
    extra = {c: t[c] for c in ["rank", "hazard_raw", "damage_raw", "crops_raw", "hazard_norm", "damage_norm",
                               "crops_norm"] + crop_cols}
    legend = classes.preset("envi")
    br = meta["breaks"]
    for i, c in enumerate(legend["classes"]):          # class ranges for the legend (retained on every map)
        c["lo"], c["hi"] = round(float(br[i]), 4), round(float(br[i + 1]), 4)
    series = t["envi_class"].where(t["envi"].notna())
    lyr = common.layer("envi", "ENVI class", "envi_class", "class", legend, series.reindex(keys), extra)
    for k, rec in lyr["values"].items():   # the class is the label; keep the index value too
        v = t["envi"].get(k)
        rec["envi"] = None if v is None or pd.isna(v) else round(float(v), 3)
    recs = s.get("recommendations") or recommendations.generate(df, meta, results, s)
    lab = meta["labels"]
    payload.update({
        "title": TITLE,
        "subtitle": lab["subtitle"],
        "issued": (settings.get("issue_date") or f"{s['reporting_month']}-01"),
        "period": {"kind": "season", "start": f"{s['period_start']}-01",
                   "end": pd.Period(s["period_end"], "M").end_time.date().isoformat(), "label": lab["period"]},
        "level": meta["level"],
        "source": settings.get("source") or DEFAULT_SOURCE,
        "layers": [lyr],
        "summary": {k: meta["summary"][k] for k in ("class_counts", "crop_at_risk_ha", "crop_at_risk_by_crop",
                                                   "crop_total_ha", "n_at_risk", "top10", "hotspots")},
        "method": {"weights": meta["weights"], "classification": meta["classification"], "breaks": meta["breaks"],
                   "hazard": meta["hazard_note"] + f" Normalized: {meta['hazard_method']}.",
                   "damage": meta["damage_note"], "crops": meta["crops_note"],
                   "formula": "ENVI = Σ weight × min–max normalized indicator"},
    })
    payload["texts"] = common.base_texts(payload, {**settings, "recommendations": recs})
    payload["texts"]["legend_title"] = "Vulnerability class (ENVI)"
    payload["recommendations_source"] = "edited" if settings.get("recommendations") else "auto"
    return payload


def crop_table(payload: dict) -> dict[str, dict[str, float]]:
    """{area_key: {crop: ha}} from an ENVI payload – feeds the dashboard's crops overlay."""
    out = {}
    for k, v in payload["layers"][0]["values"].items():
        out[k] = {c[5:].replace("_total", "").replace("_", " ").title(): v[c] for c in v if c.startswith("crop_")
                  and v[c] is not None}
    return out
