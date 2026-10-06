"""Rule-based recommendation drafts for the rainfall and drought products (always editable).

ENVI uses the prototype's ``envi.recommendations.generate``.
"""
from __future__ import annotations

from .. import reference


def _list(items: list[str]) -> str:
    items = list(items)
    if not items:
        return ""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _areas(layer: dict, pred) -> list[str]:
    hits = [(k, v["value"]) for k, v in layer["values"].items() if v["value"] is not None and pred(v["value"])]
    return [reference.area_label(k) for k, _ in sorted(hits, key=lambda kv: kv[1])]


def _short(names: list[str], n: int = 12) -> str:
    return _list(names[:n]) + (f" and {len(names) - n} other areas" if len(names) > n else "")


def rainfall_dekad(payload: dict) -> str:
    lyr = next((x for x in payload["layers"] if x["id"] == "total"), payload["layers"][-1])
    period = payload["period"]["label"]
    heavy_days = []
    for d in payload["layers"]:
        if "date" in d:
            n = sum(1 for v in d["values"].values() if v["value"] is not None and v["value"] >= 75)
            if n:
                heavy_days.append(f"{d['label']} ({n} municipalities)")
    dry = _areas(lyr, lambda v: v < 10)
    low = _areas(lyr, lambda v: 10 <= v < 25)
    wet = _areas(lyr, lambda v: v >= 150)
    lines = [f"Agricultural advisory for {period}:"]
    if dry:
        lines.append(f"- Very little rain (< 10 mm) is expected in {_short(dry)}. Prioritise irrigation for "
                     "crops at critical stages (flowering, grain filling), use alternate wetting and drying in "
                     "rice, mulch upland crops and delay planting until soil moisture is adequate.")
    if low:
        lines.append(f"- Light rainfall (10–25 mm) in {_short(low)}: conserve soil moisture, schedule irrigation "
                     "and monitor crops for water stress and pests that thrive in dry conditions.")
    if wet:
        lines.append(f"- Heavy rainfall (≥ 150 mm) is expected in {_short(wet)}. Clear canals and drainage, "
                     "harvest mature crops early, secure seeds and inputs, and watch for landslides on sloping "
                     "farms and flooding in low-lying fields.")
    if heavy_days:
        lines.append(f"- Heavy rain days (≥ 75 mm in a day): {_list(heavy_days)}. Avoid spraying and fertilizer "
                     "application on these days, secure harvested produce and check drainage beforehand.")
    if len(lines) == 1:
        lines.append("- Rainfall is expected to be moderate across CAR. Continue regular farm operations and "
                     "monitor the next forecast.")
    lines.append("- Coordinate with MAOs and irrigators' associations; follow PAGASA and LGU advisories.")
    return "\n".join(lines)


def rainfall_seasonal(payload: dict) -> str:
    season = next(lyr for lyr in payload["layers"] if lyr["id"] == "season_total")
    pct = next((lyr for lyr in payload["layers"] if lyr["id"] == "pct_normal"), None)
    months = payload["layers"][:len(payload["period"].get("months", []))]
    lines = [f"Agricultural advisory for the season {payload['period']['label']}:"]
    dry_months = []
    for lyr in months:
        n = sum(1 for v in lyr["values"].values() if v["value"] is not None and v["value"] < 50)
        if n >= 20:
            dry_months.append(lyr["label"])
    if dry_months:
        lines.append(f"- Months with < 50 mm in many municipalities: {_list(dry_months)}. Plan planting so "
                     "critical crop stages avoid these months; use early-maturing and drought-tolerant varieties.")
    if pct:
        below = _areas(pct, lambda v: v <= 80)
        above = _areas(pct, lambda v: v > 120)
        if below:
            lines.append(f"- Below-normal seasonal rainfall in {_short(below)}: store water (small farm "
                         "reservoirs, SWIP/SSIP), repair irrigation canals and promote water-saving technologies.")
        if above:
            lines.append(f"- Above-normal rainfall in {_short(above)}: improve drainage, guard against "
                         "soil erosion and plan harvests around the wettest months.")
    low = _areas(season, lambda v: v < 600)
    if low:
        lines.append(f"- Lowest season totals: {_short(low, 8)}. Prioritise these areas for water management "
                     "interventions and crop insurance (PCIC) enrolment.")
    lines.append("- 1 mm of rain = 1 litre per m² (10 m³ per hectare): compare with crop water requirements "
                 "when planning irrigation.")
    return "\n".join(lines)


def drought(payload: dict) -> str:
    by = payload["summary"]["by_month_province"]
    months = payload["period"]["months"]
    lines = [f"Agricultural advisory for {payload['period']['label']}:"]
    provinces = sorted({p for m in by.values() for p in m})
    from ..envi.config import month_label
    for prov in provinces:
        seq = [(ym, by[ym].get(prov)) for ym in months]
        first_spell = next((month_label(ym) for ym, c in seq if c in ("Dry spell", "Drought")), None)
        first_drought = next((month_label(ym) for ym, c in seq if c == "Drought"), None)
        if first_drought:
            lines.append(f"- {prov}: drought from {first_drought}"
                         + (f" (dry spell from {first_spell})" if first_spell and first_spell != first_drought else "")
                         + ". Advance planting or shift to drought-tolerant crops, harvest early where possible, "
                           "and prepare water impounding and irrigation support.")
        elif first_spell:
            lines.append(f"- {prov}: dry spell from {first_spell}. Schedule irrigation, conserve soil moisture "
                         "and avoid planting water-demanding crops late in the season.")
    lines.append("- Pre-position seeds, enrol farmers in PCIC crop insurance and monitor PAGASA updates monthly.")
    return "\n".join(lines)


DRAFTERS = {"rainfall_dekad": rainfall_dekad, "rainfall_seasonal": rainfall_seasonal, "drought": drought}
