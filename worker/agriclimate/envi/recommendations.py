"""Rule-based draft of agricultural recommendations (editable by the user).

Mirrors web/js/recommend.js, but also uses the ENVI results: priority areas are the High / Very High
municipalities instead of raw input rankings.
"""
from __future__ import annotations

import pandas as pd

from . import config

CATS = ("not affected", "dry condition", "dry spell", "drought")


def _list(items: list[str]) -> str:
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""


def _calendar(months: list[str], period_start: str) -> list[str]:
    """Give each forecast month column a year, starting at period_start (YYYY-MM)."""
    try:
        y, m = (int(x) for x in period_start.split("-"))
    except ValueError:
        return months
    m -= 1
    out = []
    for name in months:
        target = config.MONTHS.index(name)
        for _ in range(12):
            if m % 12 == target:
                break
            m += 1
        out.append(f"{name} {y + m // 12}")
    return out


def drought_timing(drought_data: pd.DataFrame, months: list[str], period_start: str, labels: dict) -> list[dict]:
    """Group provinces by first dry-spell month, first drought month and number of drought months."""
    cat_cols = [f"cat_{m}" for m in months if f"cat_{m}" in drought_data.columns]
    if not cat_cols:
        return []
    cal = _calendar([c[4:] for c in cat_cols], period_start)
    groups: dict[tuple, list[str]] = {}
    for key, row in drought_data.iterrows():
        seq = [str(row[c]).strip().lower() if pd.notna(row[c]) else "" for c in cat_cols]
        first = lambda cat: next((cal[i] for i, v in enumerate(seq) if v == cat), None)  # noqa: E731
        t = (first("dry spell"), first("drought"), sum(v == "drought" for v in seq))
        groups.setdefault(t, []).append(labels.get(key, str(key).title()))
    out = [{"dry_spell": k[0], "drought": k[1], "drought_months": k[2], "provinces": sorted(v)} for k, v in groups.items()]
    return sorted(out, key=lambda g: -g["drought_months"])


def generate(df: pd.DataFrame, meta: dict, results: dict, settings: dict) -> str:
    """Draft recommendations from the ENVI table, the drought forecast and the summary."""
    from .io_loader import PROVINCE_DISPLAY

    lines: list[str] = []
    drought = results.get("drought")
    timing = []
    if drought is not None and drought.ok:
        timing = drought_timing(drought.data, drought.report.get("months", []), settings.get("period_start", ""),
                                PROVINCE_DISPLAY)
    if timing:
        lines.append("Expected dry conditions:")
        for g in timing:
            parts = []
            if g["dry_spell"]:
                parts.append(f"dry spell from {g['dry_spell']}")
            if g["drought"]:
                n = g["drought_months"]
                parts.append(f"drought from {g['drought']} ({n} month{'s' if n != 1 else ''})")
            lines.append(f"• {_list(g['provinces'])}: {', '.join(parts) or 'no dry spell or drought forecast'}.")
        lines.append("")

    lines.append("Recommended actions:")
    n = 1
    with_drought = [g for g in timing if g["drought"]]
    if with_drought:
        earliest = min(with_drought, key=lambda g: pd.Timestamp(f"1 {g['drought']}"))["drought"]
        severe = [p for g in timing if g["drought_months"] >= 3 for p in g["provinces"]]
        lines.append(
            f"{n}. Planting calendar: harvest standing rice and corn before the drought onset ({earliest}). "
            + (f"In rainfed areas of {_list(severe)}, avoid new rice plantings late in the season and "
               if severe else "Where planting continues, ")
            + "shift to short-maturing, drought-tolerant varieties or less water-demanding crops "
              "(legumes, root crops, vegetables).")
    else:
        lines.append(f"{n}. Planting calendar: follow the PAGASA outlook; use short-maturing, drought-tolerant "
                     "varieties for late plantings.")
    n += 1

    risk = df[df.envi_class.isin(["Very High", "High"])].sort_values("envi", ascending=False)
    if len(risk):
        names = [f"{r.area} ({r.envi_class}, {r.crops_raw:,.0f} ha)" for r in risk.head(8).itertuples()]
        more = f" and {len(risk) - 8} more" if len(risk) > 8 else ""
        lines.append(f"{n}. Priority areas: focus monitoring, inputs and field support on the High / Very High "
                     f"municipalities – {', '.join(names)}{more}. Together they hold "
                     f"{meta['summary']['crop_at_risk_ha']:,.0f} ha of standing crops at risk.")
        n += 1
    dmg = df[df.damage_raw > 0].sort_values("damage_raw", ascending=False).head(5)
    if len(dmg):
        lines.append(f"{n}. Pre-positioning: stock drought-tolerant seeds, fertilizer and water pumps in areas with "
                     f"repeated El Niño damage – {_list(list(dmg.area))}.")
        n += 1
    lines += [
        f"{n}. Water management: activate small-scale irrigation projects (SSIP/SWIP), solar-powered pumps and "
        "rainwater harvesting; desilt canals and schedule irrigation (e.g., alternate wetting and drying in "
        "irrigated rice).",
        f"{n + 1}. Risk transfer: enroll standing crops with PCIC crop insurance before the onset of drought and "
        "prepare damage reporting through the DRRM operations center.",
        f"{n + 2}. Livestock: secure water and forage reserves for livestock and poultry in the most affected provinces.",
        f"{n + 3}. Advisories: disseminate monthly DA/PAGASA farm advisories and update this index when a new "
        "forecast is issued.",
    ]
    return "\n".join(lines)
