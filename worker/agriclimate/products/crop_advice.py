"""Farm recommendations for rice, corn and high-value crops (HVC), shown under the legend of the 10-day,
seasonal and drought maps. Drafted from the forecast (rule-based) and always editable in the admin.

Each text is kept short (about 230 characters) so it fits the map panel.
"""
from __future__ import annotations

from ..envi.config import month_label

CROPS = ("rice", "corn", "hvc")
LABELS = {"rice": "Rice", "corn": "Corn", "hvc": "HVC"}
TEXT_KEYS = {c: f"advice_{c}" for c in CROPS}     # keys in payload["texts"]


def _numeric(layer: dict) -> list[float]:
    return [v["value"] for v in layer["values"].values() if isinstance(v["value"], (int, float))]


def _share(layer: dict, pred) -> float:
    vals = _numeric(layer)
    return sum(1 for v in vals if pred(v)) / len(vals) if vals else 0.0


def rainfall_dekad(payload: dict) -> dict[str, str]:
    days = [lyr for lyr in payload["layers"] if lyr["id"].startswith("d_")]
    total = next((lyr for lyr in payload["layers"] if lyr["id"] == "total"), payload["layers"][-1])
    heavy = [d["label"] for d in days if _share(d, lambda v: v >= 75) > 0]
    wet = bool(heavy) or _share(total, lambda v: v >= 150) > 0.2
    dry = _share(total, lambda v: v < 25) > 0.3
    when = f" ({', '.join(heavy[:3])})" if heavy else ""
    if wet:
        return {
            "rice": f"Drain excess water from paddies before heavy rain{when}. Delay fertilizer and spraying on rainy "
                    "days; harvest mature palay early and dry it under shelter.",
            "corn": "Clear drainage canals to avoid waterlogging. Postpone side-dressing on heavy-rain days; check for "
                    "stalk rot and fall armyworm after the rains.",
            "hvc": "Use raised beds, plastic mulch or rain shelters. Spray protectant fungicide before rains (late "
                   "blight, clubroot) and harvest mature vegetables early.",
        }
    if dry:
        return {
            "rice": "Keep 2–5 cm of water at flowering; use alternate wetting and drying where water is short. "
                    "Prioritise irrigation for fields at the reproductive stage.",
            "corn": "Irrigate at tasseling and silking. Mulch to keep soil moisture and delay planting until the soil "
                    "is moist enough.",
            "hvc": "Water early in the morning, use drip irrigation and mulch. Give priority to seedlings and newly "
                   "transplanted crops.",
        }
    return {
        "rice": "Good conditions for transplanting and fertilizer application between rain days. Keep 3–5 cm of "
                "water in the paddies and monitor for pests.",
        "corn": "Suitable for planting and side-dressing. Hill-up to improve drainage and monitor fall armyworm.",
        "hvc": "Good for transplanting vegetables. Keep drainage open and watch for fungal diseases after rain.",
    }


def rainfall_seasonal(payload: dict) -> dict[str, str]:
    months = [lyr for lyr in payload["layers"] if lyr["id"].startswith("m_")]
    dry = [m["label"].split()[0] for m in months if _share(m, lambda v: v < 50) > 0.3]
    wet = [m["label"].split()[0] for m in months if _share(m, lambda v: v >= 300) > 0.3]
    dry_txt = f"; dry months: {', '.join(dry[:3])}" if dry else ""
    wet_txt = f" Expect heavy rain in {', '.join(wet[:2])}." if wet else ""
    return {
        "rice": f"Time planting so flowering avoids the driest months{dry_txt}. Use early-maturing varieties and "
                f"store water for the dry part of the season.{wet_txt}"[:240],
        "corn": "Plant at the start of the wetter months and use drought-tolerant or early-maturing hybrids. "
                "Mulch and keep drainage open in the wettest months.",
        "hvc": "Plan staggered planting with irrigation (SWIP/SSIP, drip). Use rain shelters in wet months and mulch "
               "in dry months; prioritise high-value crops under irrigation.",
    }


def drought(payload: dict) -> dict[str, str]:
    months = [lyr for lyr in payload["layers"] if lyr["id"].startswith("m_")]
    first = next((m for m in months if any(v["class"] == "Drought" for v in m["values"].values())), None)
    spell = next((m for m in months if any(v["class"] in ("Dry spell", "Drought") for v in m["values"].values())),
                 None)
    onset = month_label(first["id"][2:]) if first else (month_label(spell["id"][2:]) if spell else "")
    by = f" before {onset}" if onset else ""
    return {
        "rice": f"Harvest standing rice{by}. Skip or reduce dry-season rice in rainfed areas; use early-maturing "
                "varieties and alternate wetting and drying in irrigated fields.",
        "corn": f"Plant early-maturing, drought-tolerant hybrids so the crop is harvested{by}. Mulch, and "
                "enrol standing crops in PCIC crop insurance.",
        "hvc": "Reduce planting to the area you can irrigate. Use drip irrigation, mulching and water "
               "impounding; prioritise crops with assured water.",
    }


DRAFTERS = {"rainfall_dekad": rainfall_dekad, "rainfall_seasonal": rainfall_seasonal, "drought": drought}


def draft(payload: dict) -> dict[str, str] | None:
    f = DRAFTERS.get(payload["type"])
    return f(payload) if f else None


def advice_of(payload: dict) -> dict[str, str]:
    """The (possibly edited) farm recommendations of a payload: {'rice': …, 'corn': …, 'hvc': …}."""
    t = payload.get("texts", {})
    return {c: (t.get(TEXT_KEYS[c]) or "").strip() for c in CROPS if (t.get(TEXT_KEYS[c]) or "").strip()}
