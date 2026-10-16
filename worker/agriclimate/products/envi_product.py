"""ENVI – El Niño Vulnerability Index: the prototype's method wrapped as a portal product.

Inputs (dataset → file): ``drought`` (provincial monthly categories), ``damage`` (historical damage, ha),
``crops`` (standing rice / corn, ha) and, optional, ``hvc`` (HVCDP Regional Summary → HVC standing area as of the
crops date) and ``livestock`` (heads → TLU). With livestock the crops indicator becomes crops & livestock exposure
(see ``envi.exposure``). Exports reuse the prototype pipeline (``envi.pipeline.run``).
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
EXPOSURE_COLS = ["crops_area_norm", "hvc_short_ha", "hvc_perennial_ha", "livestock_raw", "livestock_norm",
                 "livestock_heads"]


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
                               "crops_norm"] + crop_cols + [c for c in EXPOSURE_COLS if c in t]}
    legend = classes.preset("envi")
    br = meta["breaks"]
    for i, c in enumerate(legend["classes"]):          # class ranges for the legend (retained on every map)
        c["lo"], c["hi"] = round(float(br[i]), 4), round(float(br[i + 1]), 4)
    series = t["envi_class"].where(t["envi"].notna())
    lyr = common.layer("envi", "ENVI class", "envi_class", "class", legend, series.reindex(keys), extra)
    for k, rec in lyr["values"].items():   # the class is the label; keep the index value too
        v = t["envi"].get(k)
        rec["envi"] = None if v is None or pd.isna(v) else round(float(v), 3)
    layers = [lyr] + monthly_layers(df, t, meta, s, results, keys)
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
        "layers": layers,
        "summary": {k: meta["summary"][k] for k in ("class_counts", "crop_at_risk_ha", "crop_at_risk_by_crop",
                                                   "crop_total_ha", "n_at_risk", "top10", "hotspots",
                                                   "livestock_at_risk_tlu", "livestock_total_tlu",
                                                   "livestock_at_risk_heads")
                    if k in meta["summary"]},
        "method": {"weights": meta["weights"], "classification": meta["classification"], "breaks": meta["breaks"],
                   "hazard": meta["hazard_note"] + f" Normalized: {meta['hazard_method']}.",
                   "damage": meta["damage_note"], "crops": meta["crops_note"], "crops_label": meta["crops_label"],
                   "formula": "ENVI = Σ weight × min–max normalized indicator",
                   "monthly": "Monthly ENVI: drought part = that month's forecast score ÷ 3 (not affected 0, dry "
                              "condition 1, dry spell 2, drought 3); damage and standing crops as in the season ENVI."},
    })
    ex = meta["exposure"]
    payload["exposure"] = {"hvc": ex["hvc"], "livestock": ex["livestock"], "livestock_share": ex["livestock_share"],
                           "crops_as_of": s.get("crops_as_of"), "livestock_as_of": ex.get("livestock_as_of"),
                           "hvc_summary": ex.get("hvc_summary"), "livestock_summary": ex.get("livestock_summary")}
    payload["texts"] = common.base_texts(payload, {**settings, "recommendations": recs})
    payload["texts"]["legend_title"] = "Vulnerability class (ENVI)"
    payload["recommendations_source"] = "edited" if settings.get("recommendations") else "auto"
    # observed drought situation (PAGASA DroughtCaster assessment), when the forecast was fetched from there
    cur = settings.get("current_condition")
    if isinstance(cur, dict) and cur.get("by_province"):
        payload["current"] = {"month": cur.get("month"), "label": cur.get("label"), "by_province": cur["by_province"],
                              "source": cur.get("source") or "PAGASA DroughtCaster (observed)"}
    return payload


def month_keys(names: list[str], start: str, end: str) -> dict[str, str]:
    """Outlook month names ('October', …) → 'YYYY-MM' within the period (the first match from the start)."""
    out = {}
    for p in pd.period_range(start, end, freq="M"):
        name = p.strftime("%B")
        if name in names and name not in out:
            out[name] = p.strftime("%Y-%m")
    return out


def monthly_layers(df: pd.DataFrame, t: pd.DataFrame, meta: dict, s: dict, results: dict, keys) -> list[dict]:
    """One ENVI layer per outlook month (m_YYYY-MM), after the season layer; same legend, own class ranges, and
    the month's own draft recommendations (its forecast and its High / Very High areas)."""
    months = index.monthly_envi(t.reset_index(), meta, s, results["drought"].report)
    yms = month_keys(list(months), s["period_start"], s["period_end"])
    out = []
    for name, f in months.items():
        if name not in yms:
            continue
        f = f.set_axis(t.index)
        legend = classes.preset("envi")
        br = f.attrs["breaks"]
        for i, c in enumerate(legend["classes"]):
            c["lo"], c["hi"] = round(float(br[i]), 4), round(float(br[i + 1]), 4)
        extra = {c: f[c] for c in ["rank", "hazard_raw", "hazard_norm", "damage_norm", "crops_norm"]}
        extra.update({c: t[c] for c in ["damage_raw", "crops_raw", "livestock_raw"] if c in t})
        if f"cat_{name}" in t:
            extra["drought_category"] = t[f"cat_{name}"]
        label = pd.Period(yms[name], "M").strftime("%B %Y")
        lyr = common.layer(f"m_{yms[name]}", label, "envi_class", "class", legend,
                           f["envi_class"].where(f["envi"].notna()).reindex(keys), extra)
        for k, rec in lyr["values"].items():
            v = f["envi"].get(k)
            rec["envi"] = None if v is None or pd.isna(v) else round(float(v), 3)
        d, m = index.month_view(df, meta, name, f.reset_index(drop=True), label)
        lyr["recommendations"] = recommendations.generate(d, m, results, s)
        out.append(lyr)
    return out


def crop_table(payload: dict) -> dict[str, dict[str, float]]:
    """{area_key: {crop: ha}} from an ENVI payload – feeds the dashboard's crops overlay."""
    out = {}
    for k, v in payload["layers"][0]["values"].items():
        out[k] = {index.crop_label(c): v[c] for c in v if c.startswith("crop_") and v[c] is not None}
    return out
