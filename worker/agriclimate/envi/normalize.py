"""Indicator normalization (min–max scaling to 0–1)."""
from __future__ import annotations

import pandas as pd


def minmax(values: pd.Series, invert: bool = False) -> pd.Series:
    """x_norm = (x − min) / (max − min); 0 when max = min. NaN stays NaN.

    ``invert=True`` gives (max − x) / (max − min), used when a lower raw value means higher
    vulnerability (e.g. rainfall as % of normal).
    """
    s = pd.to_numeric(values, errors="coerce").astype(float)
    lo, hi = s.min(skipna=True), s.max(skipna=True)
    if pd.isna(lo) or hi == lo:
        return s.where(s.isna(), 0.0)
    out = (s - lo) / (hi - lo)
    return 1.0 - out if invert else out


def fixed_scale(values: pd.Series, max_value: float) -> pd.Series:
    """Scale against a fixed theoretical maximum (e.g. ordinal drought score / max possible score)."""
    s = pd.to_numeric(values, errors="coerce").astype(float)
    if not max_value:
        return s.where(s.isna(), 0.0)
    return (s / float(max_value)).clip(0, 1)


def normalize_hazard(raw: pd.Series, report: dict, scaling: str = "minmax") -> tuple[pd.Series, str]:
    """Normalize the drought hazard indicator according to its type/direction.

    Returns (normalized series, human-readable description of the method).
    """
    invert = report.get("hazard_direction") == "lower_worse"
    if scaling == "fixed" and report.get("hazard_type") == "categorical":
        mx = report.get("hazard_max")
        return fixed_scale(raw, mx), f"score ÷ maximum possible score ({mx})"
    desc = "min–max, inverted (lower rainfall = higher value)" if invert else "min–max"
    return minmax(raw, invert=invert), desc


def ordinal_from_categories(values, mapping: dict) -> pd.Series:
    """Map categorical labels (case-insensitive) to ordinal scores; unknown labels -> NaN."""
    s = pd.Series(values)
    return s.astype(str).str.strip().str.lower().map({k.lower(): v for k, v in mapping.items()}).astype(float)

