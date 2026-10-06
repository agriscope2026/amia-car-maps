"""Combine indicators into the El Niño Vulnerability Index (ENVI), classify and summarise."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from . import config
from .io_loader import DatasetResult, Gazetteer
from .normalize import minmax, normalize_hazard

IND_KEYS = ["hazard", "damage", "crops"]
DATASET_OF = {"hazard": "drought", "damage": "damage", "crops": "crops"}


# ---------------------------------------------------------------- weights ---

def validate_weights(weights: dict, tol: float = 1e-3) -> dict:
    """Weights must be non-negative, cover the three indicators and sum to 1 (±tol)."""
    w = {k: float(weights.get(k, 0) or 0) for k in IND_KEYS}
    if any(v < 0 for v in w.values()):
        raise ValueError("Weights must be non-negative.")
    total = sum(w.values())
    if abs(total - 1.0) > tol:
        raise ValueError(f"Weights must sum to 1 (currently {total:.3f}).")
    return {k: v / total for k, v in w.items()}  # remove rounding residue (e.g. 3 × 0.3333)


def weighted_sum(norms: pd.DataFrame, weights: dict) -> pd.Series:
    """ENVI = Σ wᵢ · xᵢ_norm. NaN if any indicator is NaN."""
    w = validate_weights(weights)
    cols = [f"{k}_norm" for k in IND_KEYS]
    vals = norms[cols].to_numpy(dtype=float)
    out = vals @ np.array([w[k] for k in IND_KEYS])
    out[np.isnan(vals).any(axis=1)] = np.nan
    return pd.Series(out, index=norms.index)


# --------------------------------------------------------- classification ---

def jenks_breaks(values, n_classes: int = 5) -> list[float]:
    """Fisher–Jenks natural breaks. Returns n_classes+1 break values (min … max)."""
    data = sorted(float(v) for v in values if v is not None and not math.isnan(v))
    n = len(data)
    if n == 0:
        return [0.0] * (n_classes + 1)
    uniq = sorted(set(data))
    if len(uniq) <= n_classes:
        brk = uniq + [uniq[-1]] * (n_classes - len(uniq))
        return [data[0]] + brk
    lower = [[0] * (n_classes + 1) for _ in range(n + 1)]
    var = [[math.inf] * (n_classes + 1) for _ in range(n + 1)]
    for j in range(1, n_classes + 1):
        lower[1][j] = 1
        var[1][j] = 0.0
    for l in range(2, n + 1):
        s1 = s2 = w = 0.0
        for m in range(1, l + 1):
            i3 = l - m + 1
            val = data[i3 - 1]
            s2 += val * val
            s1 += val
            w += 1
            v = s2 - (s1 * s1) / w
            i4 = i3 - 1
            if i4 != 0:
                for j in range(2, n_classes + 1):
                    if var[l][j] >= v + var[i4][j - 1]:
                        lower[l][j] = i3
                        var[l][j] = v + var[i4][j - 1]
        lower[l][1] = 1
        var[l][1] = v
    breaks = [0.0] * (n_classes + 1)
    breaks[n_classes] = data[-1]
    breaks[0] = data[0]
    k = n
    for j in range(n_classes, 1, -1):
        idx = lower[k][j] - 2
        breaks[j - 1] = data[idx]
        k = lower[k][j] - 1
    return breaks


def class_breaks(values: pd.Series, method: str = "equal") -> list[float]:
    v = pd.to_numeric(values, errors="coerce").dropna()
    if method == "equal" or v.empty:
        return [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    if method == "quantile":
        return [float(x) for x in np.quantile(v, [0, 0.2, 0.4, 0.6, 0.8, 1.0])]
    if method == "jenks":
        return jenks_breaks(v.tolist(), 5)
    raise ValueError(f"Unknown classification method '{method}'")


def classify(values: pd.Series, breaks: list[float], method: str = "equal") -> pd.Series:
    """Assign the 5 class names.

    Equal intervals are lower-inclusive ([0, 0.2) → Very Low … [0.8, 1.0] → Very High).
    Quantile and natural-breaks classes are upper-inclusive (break = last value of a class).
    """
    v = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    inner = np.array(breaks[1:-1], dtype=float)
    side = "right" if method == "equal" else "left"
    idx = np.searchsorted(inner, v, side=side)
    idx = np.clip(idx, 0, 4)
    names = np.array(config.CLASS_NAMES, dtype=object)[idx]
    names[np.isnan(v)] = config.NO_DATA_LABEL
    return pd.Series(names, index=values.index)


def legend_items(breaks: list[float], counts: dict | None = None, include_nodata: bool = False) -> list[dict]:
    items = []
    for i, name in enumerate(config.CLASS_NAMES):
        lo, hi = breaks[i], breaks[i + 1]
        items.append({"class": name, "color": config.CLASS_COLORS[name], "lo": lo, "hi": hi,
                      "range": f"{lo:.2f} – {hi:.2f}", "label": f"{name} ({lo:.2f} – {hi:.2f})",
                      "count": (counts or {}).get(name, 0)})
    if include_nodata:
        items.append({"class": config.NO_DATA_LABEL, "color": config.NO_DATA_COLOR, "lo": None, "hi": None,
                      "range": "", "label": config.NO_DATA_LABEL, "count": (counts or {}).get(config.NO_DATA_LABEL, 0)})
    return items


# ---------------------------------------------------------------- combine ---

def analysis_level(results: dict[str, DatasetResult]) -> str:
    return "municipal" if any(r.level == "municipal" for r in results.values()) else "provincial"


def _broadcast(res: DatasetResult, base: pd.DataFrame, level: str) -> pd.DataFrame:
    """Attach a dataset's values to every area of the analysis level."""
    if res.level == level or level == "provincial":
        return base[["area_key"]].join(res.data, on="area_key").drop(columns="area_key")
    # provincial data → municipal areas
    return base[["province"]].join(res.data, on="province").drop(columns="province")


def compute_envi(results: dict[str, DatasetResult], gaz: Gazetteer, settings: dict) -> tuple[pd.DataFrame, dict]:
    """Merge the three datasets on the GIS area key, normalize, weight, classify and rank.

    Returns (table with one row per GIS area, metadata dict).
    """
    level = analysis_level(results)
    weights = validate_weights(settings.get("weights", config.DEFAULT_SETTINGS["weights"]))
    method = settings.get("classification", "equal")

    if level == "municipal":
        base = gaz.muni[["area_key", "province", "province_label", "label", "gis_name"]].copy()
        base = base.rename(columns={"label": "area"})
    else:
        base = gaz.prov[["area_key", "province", "label", "gis_name"]].copy()
        base["province_label"] = base["label"]
        base = base.rename(columns={"label": "area"})
    base = base.reset_index(drop=True)

    parts = {k: _broadcast(results[DATASET_OF[k]], base, level) for k in IND_KEYS}
    df = base.copy()
    for k, p in parts.items():
        df = pd.concat([df, p.reset_index(drop=True)], axis=1)

    hazard_norm, hazard_desc = normalize_hazard(df["hazard_raw"], results["drought"].report,
                                                settings.get("hazard_scaling", "minmax"))
    df["hazard_norm"] = hazard_norm
    df["damage_norm"] = minmax(df["damage_raw"])
    df["crops_norm"] = minmax(df["crops_raw"])

    missing = df[[f"{k}_raw" for k in IND_KEYS]].isna()
    df["missing_indicators"] = missing.apply(
        lambda r: ", ".join(config.INDICATORS[c.replace("_raw", "")][0] for c, m in r.items() if m), axis=1)
    if settings.get("missing_policy", "nodata") == "zero":
        for k in IND_KEYS:
            df[f"{k}_norm"] = df[f"{k}_norm"].fillna(0.0)

    df["envi"] = weighted_sum(df, weights)
    breaks = class_breaks(df["envi"], method)
    df["envi_class"] = classify(df["envi"], breaks, method)
    df["rank"] = df["envi"].rank(ascending=False, method="min").astype("Int64")
    df["class_color"] = df["envi_class"].map({**config.CLASS_COLORS, config.NO_DATA_LABEL: config.NO_DATA_COLOR})
    df = df.sort_values(["rank", "province", "area"], na_position="last").reset_index(drop=True)

    meta = {
        "level": level,
        "weights": weights,
        "classification": method,
        "breaks": breaks,
        "hazard_method": hazard_desc,
        "hazard_note": results["drought"].report.get("hazard_note", ""),
        "damage_note": results["damage"].report.get("damage_note", ""),
        "crops_note": results["crops"].report.get("crops_note", ""),
        "n_areas": int(len(df)),
        "n_nodata": int((df.envi_class == config.NO_DATA_LABEL).sum()),
        "labels": config.period_labels(settings),
        "hazard_months": results["drought"].report.get("months", []),
        "hazard_type": results["drought"].report.get("hazard_type", ""),
        "damage_years": results["damage"].report.get("damage_years", []),
    }
    meta["summary"] = summarize(df, breaks)
    return df, meta


def summarize(df: pd.DataFrame, breaks: list[float]) -> dict:
    counts = df["envi_class"].value_counts().to_dict()
    counts = {c: int(counts.get(c, 0)) for c in config.CLASS_NAMES + [config.NO_DATA_LABEL]}
    risk = df[df.envi_class.isin(["High", "Very High"])]
    crop_cols = [c for c in df.columns if c.startswith("crop_")]
    at_risk = {c.replace("crop_", "").replace("_total", "").replace("_", " ").title(): float(risk[c].sum())
               for c in crop_cols}
    top = df.dropna(subset=["envi"]).head(10)
    hotspots = []
    for prov, g in risk.groupby("province_label", sort=False):
        g = g.sort_values("envi", ascending=False)
        hotspots.append({"province": prov, "max_envi": float(g.envi.max()), "n": int(len(g)),
                         "areas": [f"{a} ({c})" for a, c in zip(g.area, g.envi_class)]})
    hotspots.sort(key=lambda h: -h["max_envi"])
    return {
        "hotspots": hotspots,
        "class_counts": counts,
        "legend": legend_items(breaks, counts, include_nodata=counts[config.NO_DATA_LABEL] > 0),
        "crop_at_risk_ha": float(risk["crops_raw"].sum()) if "crops_raw" in risk else 0.0,
        "crop_at_risk_by_crop": at_risk,
        "crop_total_ha": float(df["crops_raw"].sum()),
        "n_at_risk": int(len(risk)),
        "top10": [{"rank": int(r["rank"]), "area": r.area, "province": r.province_label,
                   "envi": float(r.envi), "class": r.envi_class, "color": r.class_color,
                   "crops_ha": float(r.crops_raw) if pd.notna(r.crops_raw) else None}
                  for _, r in top.iterrows()],
    }


def display_table(df: pd.DataFrame) -> pd.DataFrame:
    """Tidy, human-readable column set for tables/exports."""
    cols = {
        "rank": "Rank", "area": "Area", "province_label": "Province",
        "hazard_raw": "Drought forecast score", "damage_raw": "Historical damage (ha, mean/yr)",
        "crops_raw": "Standing crops (ha)",
        "hazard_norm": "Drought (norm)", "damage_norm": "Damage (norm)", "crops_norm": "Crops (norm)",
        "envi": "ENVI", "envi_class": "Class", "missing_indicators": "Missing indicators",
    }
    extra = [c for c in df.columns if c.startswith(("crop_", "dmg_", "cat_"))]
    out = df[list(cols) + extra].rename(columns=cols)
    return out
