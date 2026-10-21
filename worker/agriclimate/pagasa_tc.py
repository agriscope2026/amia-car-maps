"""PAGASA Tropical Cyclone Bulletin → Special Farm Weather Outlook and Advisory for CAR (draft payload).

Source: https://bagong.pagasa.dost.gov.ph/tropical-cyclone/severe-weather-bulletin – one tab per active tropical
cyclone ("tcwb-1", "tcwb-2" …). From each tab this module reads:

  * the bulletin number, category and local name (Super Typhoon "Rosal"), issue time and next bulletin;
  * the centre (km from land, latitude/longitude), movement, maximum winds and gusts, forecast positions;
  * the Tropical Cyclone Wind Signal (TCWS) tables – Luzon areas per signal – and from them the CAR
    municipalities under each signal: a whole province ("Ifugao"), named towns ("the northern portion of Apayao
    (Calanasan, Luna)"), "the rest of / remaining …" (the towns of that province not under a higher signal) and
    Baguio City;
  * the strong-gust outlook per day and the heavy-rainfall outlook (whether CAR is named);
  * PAGASA's track and intensity forecast image (shown as it is on the exports) and the bulletin PDF link.

The payload is a draft: the admin checks it against PAGASA's bulletin before publishing.
"""
from __future__ import annotations

import html as htmllib
import logging
import os
import re
from datetime import date, datetime, timedelta

import pandas as pd

from . import classes, reference
from .envi.io_loader import clean_name, match_name
from .exports import now_manila
from .products import common

log = logging.getLogger("agriclimate.pagasa_tc")
PAGE_URL = os.environ.get("PAGASA_TC_URL", "https://bagong.pagasa.dost.gov.ph/tropical-cyclone/severe-weather-bulletin")
TYPE = "tc_advisory"
TITLE = "Special Farm Weather Outlook and Advisory"
SOURCE = "DOST-PAGASA Tropical Cyclone Bulletin; farm advisory by DA-RFO-CAR AMIA"

CAR_PROVINCES = {"ABRA": "Abra", "APAYAO": "Apayao", "BENGUET": "Benguet", "IFUGAO": "Ifugao", "KALINGA": "Kalinga",
                 "MOUNTAIN PROVINCE": "Mountain Province"}
NO_SIGNAL = "No wind signal"
SIGNAL_LABELS = {n: f"Wind Signal No. {n}" for n in range(1, 6)}
# PAGASA TCWS colours (the signal icons on the bulletin page)
SIGNAL_COLORS = {0: "#f4f6f4", 1: "#29b6f6", 2: "#ffd600", 3: "#ff9100", 4: "#e53935", 5: "#8e24aa"}
WINDS = {1: "39–61 km/h (strong winds)", 2: "62–88 km/h (gale-force winds)", 3: "89–117 km/h (storm-force winds)",
         4: "118–184 km/h (typhoon-force winds)", 5: "185 km/h or higher (typhoon-force winds)"}
LEAD = {1: "36 hours", 2: "24 hours", 3: "18 hours", 4: "12 hours", 5: "12 hours"}
DAYS = r"(?:Today|Tonight|Tomorrow|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"

LEGEND = classes.categorical("tcws", "Tropical Cyclone Wind Signal", "signal",
                             [(NO_SIGNAL, SIGNAL_COLORS[0])] + [(SIGNAL_LABELS[n], SIGNAL_COLORS[n]) for n in range(1, 6)])


# ---------------------------------------------------------------- fetching ---

def fetch_html() -> str:
    from .pagasa_seasonal import _get
    return _get(PAGE_URL).decode("utf-8", errors="replace")


def _lines(fragment: str) -> list[str]:
    t = re.sub(r"<(script|style)\b.*?</\1>", "", fragment, flags=re.S | re.I)
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = htmllib.unescape(re.sub(r"<[^>]+>", "\n", t)).replace("\xa0", " ")
    out = []
    for l in t.splitlines():
        l = re.sub(r"\s+", " ", l).strip()
        if l and l != "-->" and (not out or out[-1] != l):
            out.append(l)
    return out


def _abs(url: str) -> str:
    return url if url.startswith("http") else "https://bagong.pagasa.dost.gov.ph" + url


# ----------------------------------------------------------------- parsing ---

def _tabs(html: str) -> list[str]:
    """One HTML block per tropical cyclone (tab-pane "tcwb-N"); the whole page when there are no tabs."""
    starts = [m.start() for m in re.finditer(r"""<div[^>]+class=["'][^"']*tab-pane[^"']*["'][^>]*id=["']tcwb-\d+""", html)]
    if not starts:
        return [html]
    return [html[a:b] for a, b in zip(starts, starts[1:] + [len(html)])]


def _after(lines: list[str], head: str, n: int = 1) -> list[str]:
    i = next((k for k, l in enumerate(lines) if l.lower().startswith(head.lower())), None)
    return [] if i is None else lines[i + 1:i + 1 + n]


def _section(lines: list[str], start: str, stops: tuple[str, ...]) -> list[str]:
    i = next((k for k, l in enumerate(lines) if l.lower().startswith(start.lower())), None)
    if i is None:
        return []
    out = []
    for l in lines[i + 1:]:
        if any(l.lower().startswith(s.lower()) for s in stops):
            break
        out.append(l)
    return out


def _num(s: str | None) -> float | None:
    try:
        return float(s.replace(",", "")) if s else None
    except ValueError:
        return None


def _signal_tables(block: str) -> dict[int, dict]:
    """{signal: {"luzon": text, "impact": [...], "what_to_do": [...]}} from the TCWS tables of one tab."""
    out: dict[int, dict] = {}
    marks = list(re.finditer(r"""class=["']signalno(\d)["']""", block))
    for j, m in enumerate(marks):
        n = int(m.group(1))
        part = block[m.end(): marks[j + 1].start() if j + 1 < len(marks) else len(block)]
        luzon = re.search(r"<strong>\s*Luzon\s*</strong>\s*<ul>(.*?)</ul>", part, flags=re.S | re.I)
        text = " ".join(_lines(luzon.group(1))) if luzon else ""
        lines = _lines(part)
        out[n] = {
            "luzon": "" if text.strip() in ("", "-") else text.strip(),
            "impact": _section(lines, "Impact of the Wind", ("Precautionary Measures", "What To Do")),
            "what_to_do": _section(lines, "What To Do", ("Considering these", "Tropical Cyclone Wind Signal",
                                                         "Tropical Cyclone Bulletin Archive")),
        }
    return out


def parse_bulletin(block: str) -> dict:
    lines = _lines(block)
    b: dict = {"bulletin_no": None, "category": None, "name": None}
    for l in lines:
        m = re.match(r"Tropical Cyclone Bulletin\s*#\s*(\d+)", l, flags=re.I)
        if m and not b["bulletin_no"]:
            b["bulletin_no"] = int(m.group(1))
        m = re.match(r"""^(Super Typhoon|Typhoon|Severe Tropical Storm|Tropical Storm|Tropical Depression)\s*["“”']([^"“”']+)["“”']""", l, flags=re.I)
        if m and not b["name"]:
            b["category"], b["name"] = m.group(1).title(), m.group(2).strip().upper()
    issued = next((l for l in lines if l.lower().startswith("issued at")), "")
    b["issued_text"] = issued.removeprefix("Issued at").strip()
    m = re.search(r"(\d{1,2}:\d{2}\s*[ap]m),?\s*(\d{1,2}\s+\w+\s+\d{4})", issued, flags=re.I)
    b["issued_at"] = None
    if m:
        try:
            b["issued_at"] = datetime.strptime(f"{m.group(2)} {m.group(1).upper().replace(' ', '')}", "%d %B %Y %I:%M%p").isoformat()
        except ValueError:
            pass
    b["next_bulletin"] = next((l.strip("()") for l in lines if l.lower().startswith("(valid for broadcast")), "")
    # headline: the first all-capitals sentence after the validity line
    b["headline"] = next((l for l in lines if len(l) > 25 and l.upper() == l and re.search(r"[A-Z]{4}", l)
                          and not l.startswith("HAZARDS") and not l.startswith("TRACK")), "")
    loc = " ".join(_after(lines, "Location of Eye/center", 1))
    b["location_text"] = re.sub(r"^The center of the eye of .*? was estimated based on all available data at\s*", "", loc).strip()
    m = re.search(r"\(\s*([\d.]+)\s*°?\s*N\s*,\s*([\d.]+)\s*°?\s*E", loc)
    b["lat"], b["lon"] = (_num(m.group(1)), _num(m.group(2))) if m else (None, None)
    b["movement"] = " ".join(_after(lines, "Movement", 1))
    strength = " ".join(_after(lines, "Strength", 1))
    b["strength"] = strength
    m = re.search(r"(\d[\d,]*)\s*km/h near the center.*?(\d[\d,]*)\s*km/h", strength)
    b["max_wind_kmh"], b["gust_kmh"] = (_num(m.group(1)), _num(m.group(2))) if m else (None, None)
    b["forecast"] = [{"time": m.group(1).strip(), "where": m.group(2).strip()}
                     for l in _section(lines, "Forecast Position", ("Wind Signal", "Tropical Cyclone Wind Signal"))
                     if (m := re.match(r"^(\w{3} \d{1,2}, \d{4} \d{1,2}:\d{2} [AP]M)\s*-\s*(.+)$", l))]
    winds = _section(lines, "Severe Winds", ("HAZARDS AFFECTING COASTAL", "Coastal Inundation", "TRACK AND INTENSITY"))
    b["wind_notes"] = [l for l in winds if not re.match(DAYS + r"\s*\(", l)]
    b["gusts"] = [{"day": m.group(1), "date": m.group(2), "areas": m.group(3).strip()}
                  for l in winds if (m := re.match(r"^(" + DAYS + r")\s*\(([^)]+)\):\s*(.+)$", l))]
    b["rainfall"] = _section(lines, "Heavy Rainfall Outlook", ("Severe Winds", "HAZARDS AFFECTING COASTAL"))
    b["highest_possible"] = next((l for l in winds if "highest Wind Signal" in l), "")
    b["outlook"] = _section(lines, "TRACK AND INTENSITY OUTLOOK", ("Location of Eye", "Location of Center"))
    b["signals"] = _signal_tables(block)
    track = re.search(r"""(https?://[^"']+/track_[\w-]+\.png)""", block)
    pdf = re.search(r"""(https?://[^"']+/bulletin_[\w-]+\.pdf)""", block)
    b["track_image"] = track.group(1) if track else None
    b["bulletin_pdf"] = pdf.group(1) if pdf else None
    return b


def parse_page(html: str) -> list[dict]:
    """Every active tropical cyclone on the bulletin page (empty when none)."""
    out = []
    # the bulletin number is in the page header ("Tropical Cyclone Bulletin #4"), outside the tabs
    head = re.search(r"Tropical Cyclone Bulletin\s*#\s*(\d+)", re.sub(r"<[^>]+>", " ", html))
    for block in _tabs(html):
        if "Tropical Cyclone Bulletin" not in block and "signalno" not in block:
            continue
        b = parse_bulletin(block)
        if b["name"] or b["signals"]:
            if not b["bulletin_no"]:
                # the latest bulletin in this cyclone's archive (TCB#1_rosal.pdf … TCB#4_rosal.pdf), else the header
                nums = [int(n) for n in re.findall(r"TCB(?:%23|#)(\d+)_" + re.escape((b["name"] or "").lower()) + r"\.pdf",
                                                   html, flags=re.I)]
                b["bulletin_no"] = max(nums) if nums else (int(head.group(1)) if head and not out else None)
            out.append(b)
    return out


# ------------------------------------------- bulletin PDF: track and winds ---

CATEGORIES = {"STY": "Super Typhoon", "TY": "Typhoon", "STS": "Severe Tropical Storm", "TS": "Tropical Storm",
              "TD": "Tropical Depression", "LPA": "Low Pressure Area"}
_ROW = re.compile(r"^(\d{1,2}\.\d)\s+(\d{2,3}\.\d)\s+(.+?)\s+(\d{2,3})\s+(STY|TY|STS|TS|TD|LPA)\b\s*(\S+)?\s*(\d+)?\s*$")


def parse_pdf(data: bytes) -> dict:
    """The bulletin PDF's "Track and intensity forecast" table (centre latitude/longitude per forecast hour) and the
    extent of the tropical cyclone winds ("Strong to typhoon-force winds extend outwards up to 780 km")."""
    import io
    from pypdf import PdfReader
    text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)
    out: dict = {"track": [], "wind_extent_km": None, "pressure_hpa": None}
    m = re.search(r"extend\s+outwards?\s+up\s+to\s+([\d,]+)\s*km", text, flags=re.I)
    out["wind_extent_km"] = _num(m.group(1)) if m else None
    m = re.search(r"central pressure of\s*([\d,]+)\s*hPa", text, flags=re.I)
    out["pressure_hpa"] = _num(m.group(1)) if m else None
    hours = clock = day = None
    for raw in text.splitlines():
        l = raw.strip()
        if m := re.match(r"^(\d+)-Hour Forecast", l, flags=re.I):
            hours, clock, day = int(m.group(1)), None, None
        elif m := re.match(r"^(\d{1,2}:\d{2}\s*[AP]M)$", l, flags=re.I):
            clock = m.group(1).upper()
        elif m := re.match(r"^(\d{1,2}\s+[A-Za-z]+\s+\d{4})$", l):
            day = m.group(1)
        elif (m := _ROW.match(l)) and hours is not None:
            out["track"].append({
                "hours": hours, "time": " ".join(x for x in (clock, day) if x), "lat": float(m.group(1)),
                "lon": float(m.group(2)), "where": m.group(3).strip(), "wind_kmh": int(m.group(4)),
                "category": CATEGORIES.get(m.group(5), m.group(5)), "cat": m.group(5),
                "outside_par": "OUTSIDE PAR" in m.group(3).upper(),
            })
            hours = None
    return out


def short_time(t: str) -> str:
    """'2:00 PM 22 October 2026' → '22 Oct 2 PM'."""
    m = re.match(r"(\d{1,2}):(\d{2})\s*([AP]M)\s+(\d{1,2})\s+([A-Za-z]{3})", t or "")
    if not m:
        return t
    mins = "" if m.group(2) == "00" else f":{m.group(2)}"
    return f"{int(m.group(4))} {m.group(5)} {int(m.group(1))}{mins} {m.group(3)}"


def _aeqd(lat: float, lon: float):
    """Metre-based projection centred on the storm, for buffers and distances (to / from EPSG:4326)."""
    from pyproj import Transformer
    crs = f"+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84 +units=m"
    return Transformer.from_crs("EPSG:4326", crs, always_xy=True), Transformer.from_crs(crs, "EPSG:4326", always_xy=True)


# Philippine Area of Responsibility (as drawn on PAGASA's track maps)
PAR = [(120, 25), (135, 25), (135, 5), (115, 5), (115, 15), (120, 21), (120, 25)]
# Half-width of the forecast cone (km) by forecast hour. The bulletin does not give PAGASA's own cone, so the cone is
# drawn from typical track-forecast errors of the western North Pacific (about 100 km at 24 h, 170 km at 48 h,
# 240 km at 72 h, …) – an approximation of the cone on PAGASA's track image, labelled as such.
CONE_KM = [(0, 20), (12, 60), (24, 100), (36, 135), (48, 170), (60, 205), (72, 240), (96, 320), (120, 400)]


def _cone_km(hours: float) -> float:
    for (h0, r0), (h1, r1) in zip(CONE_KM, CONE_KM[1:]):
        if hours <= h1:
            return r0 + (r1 - r0) * (hours - h0) / (h1 - h0)
    return CONE_KM[-1][1]


def storm_force_km(png: bytes, wind_extent_km: float | None) -> int | None:
    """Radius of the storm-force winds (≥ 89 km/h, PAGASA's red circle), measured on PAGASA's track image: the bulletin
    gives only the yellow circle's radius (strong winds, ``wind_extent_km``), and both circles share the storm centre,
    so red radius = yellow radius × (red px / yellow px). None when the image has no red circle (weaker storms)."""
    if not png or not wind_extent_km:
        return None
    import io

    import numpy as np
    from PIL import Image
    # PAGASA's image is ~2700 × 2200 px: shrink it first (nearest neighbour keeps the flat colours exact, and the
    # ratio of the radii does not depend on the size) and use int16, so this takes a few MB instead of ~400 MB
    im = Image.open(io.BytesIO(png)).convert("RGB")
    im.thumbnail((900, 900), Image.NEAREST)
    a = np.asarray(im).astype(np.int16)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    red = (r >= 150) & (r <= 215) & (r - g >= 45) & (r - b >= 55)            # translucent red over sea or land
    yellow = np.zeros(red.shape, bool)
    for c in ((207, 213, 182), (216, 211, 174)):                             # translucent yellow over sea / land
        yellow |= np.abs(a - c).sum(2) <= 10
    if red.sum() < 100 or yellow.sum() < 400:
        return None
    # the disc of both colours (the red one sits inside the yellow one); other reddish marks (logos, labels) are
    # outside the yellow disc and left out
    yy, yx = np.nonzero(yellow)
    y0, y1, x0, x1 = np.percentile(yy, 0.2), np.percentile(yy, 99.8), np.percentile(yx, 0.2), np.percentile(yx, 99.8)
    red[:int(y0)], red[int(y1) + 1:], red[:, :int(x0)], red[:, int(x1) + 1:] = False, False, False, False
    if red.sum() < 100:
        return None
    ys, xs = np.nonzero(red)
    cy, cx = ys.mean(), xs.mean()
    rr = np.percentile(np.hypot(ys - cy, xs - cx), 99.5)
    ry = np.percentile(np.hypot(yy - cy, yx - cx), 99.5)
    ratio = rr / ry if ry else 0
    if not 0.05 < ratio < 0.95:
        log.warning("storm-force circle not measurable on the PAGASA image (ratio %.2f)", ratio)
        return None
    return int(round(wind_extent_km * ratio / 10) * 10)


def track_geometry(tc: dict) -> dict | None:
    """Like PAGASA's track map: the track line (now → last forecast), the forecast cone (approximate, see CONE_KM) and,
    around the present centre, the area with at least strong winds (≥ 39 km/h; the bulletin's "extent of tropical
    cyclone winds") and with storm-force winds (≥ 89 km/h; measured on PAGASA's image, see storm_force_km). Also the
    distance from CAR. None without the forecast track."""
    from shapely.geometry import LineString, Point, mapping
    from shapely.ops import transform, unary_union
    pts = ([(tc["lon"], tc["lat"])] if tc.get("lat") and tc.get("lon") else []) + [(p["lon"], p["lat"]) for p in tc.get("track") or []]
    if len(pts) < 2:
        return None
    km = tc.get("wind_extent_km") or 0
    lat0 = sum(p[1] for p in pts) / len(pts)
    lon0 = sum(p[0] for p in pts) / len(pts)
    fwd, back = _aeqd(lat0, lon0)
    line = transform(fwd.transform, LineString(pts))
    _, prov = reference.boundaries()
    car_ll = unary_union(list(prov.to_crs("EPSG:4326").geometry))
    car = transform(fwd.transform, car_ll)
    now = transform(fwd.transform, Point(pts[0]))
    # the strong-wind circle, drawn in a projection centred on the storm so that it is a true circle on the ground
    circle = storm = None
    f2, b2 = _aeqd(pts[0][1], pts[0][0])
    if km:
        circle = transform(b2.transform, Point(0, 0).buffer(km * 1000, resolution=64))
        strong_now = transform(f2.transform, car_ll).distance(Point(0, 0)) / 1000 <= km
    if tc.get("storm_force_km"):
        storm = transform(b2.transform, Point(0, 0).buffer(tc["storm_force_km"] * 1000, resolution=64))
    # cone: circles growing with the forecast hour, joined pairwise
    hours = ([0] if tc.get("lat") and tc.get("lon") else []) + [p["hours"] for p in tc.get("track") or []]
    discs = [transform(fwd.transform, Point(x, y)).buffer(_cone_km(h) * 1000, resolution=32) for (x, y), h in zip(pts, hours)]
    cone = unary_union([unary_union([d0, d1]).convex_hull for d0, d1 in zip(discs, discs[1:])])
    dists = [(car.distance(transform(fwd.transform, Point(p["lon"], p["lat"]))) / 1000, p) for p in tc.get("track") or []]
    near_km, near = min(dists, key=lambda d: d[0]) if dists else (None, None)
    return {
        "line": mapping(transform(back.transform, line)),
        "strong_winds": mapping(circle) if circle is not None else None,
        "storm_force": mapping(storm) if storm is not None else None,
        "cone": mapping(transform(back.transform, cone)),
        "now_km": round(car.distance(now) / 1000),
        "closest_km": round(near_km) if near_km is not None else None,
        "closest_time": near["time"] if near else None,
        "closest_where": near["where"] if near else None,
        # CAR within reach of the strong winds somewhere along the track (for the advice) / right now
        "car_in_buffer": bool(km and car.distance(line) / 1000 <= km),
        "car_in_strong_winds_now": bool(km and strong_now),
    }


def track_feature_collection(tc: dict, geom: dict | None) -> dict:
    """GeoJSON for the dashboard map, in PAGASA's style: PAR, the forecast cone, the strong-wind (yellow) and storm-force
    (red) circles around the present centre, the track line and the positions (now and forecast, with their
    category)."""
    feats = [{"type": "Feature", "geometry": {"type": "LineString", "coordinates": [list(p) for p in PAR]},
              "properties": {"kind": "par"}}]
    if geom and geom.get("cone"):
        feats.append({"type": "Feature", "geometry": geom["cone"], "properties": {"kind": "cone", "approximate": True}})
    if geom and geom.get("strong_winds"):
        feats.append({"type": "Feature", "geometry": geom["strong_winds"],
                      "properties": {"kind": "strong_winds", "km": tc.get("wind_extent_km")}})
    if geom and geom.get("storm_force"):
        feats.append({"type": "Feature", "geometry": geom["storm_force"],
                      "properties": {"kind": "storm_force", "km": tc.get("storm_force_km")}})
    if geom:
        feats.append({"type": "Feature", "geometry": geom["line"], "properties": {"kind": "track"}})
    if tc.get("lat") and tc.get("lon"):
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [tc["lon"], tc["lat"]]},
                      "properties": {"kind": "now", "label": "Now", "category": tc.get("category"),
                                     "cat": {v: k for k, v in CATEGORIES.items()}.get(tc.get("category") or "", "")}})
    for p in tc.get("track") or []:
        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]},
                      "properties": {"kind": "forecast", "label": f"{short_time(p['time'])} · {p['cat']}",
                                     "time_label": short_time(p["time"]), "time": p["time"],
                                     "cat": p["cat"], "wind_kmh": p["wind_kmh"]}})
    return {"type": "FeatureCollection", "features": feats}


# ------------------------------------------ Weather Advisory (heavy rainfall) ---

ADVISORY_URL = os.environ.get("PAGASA_ADVISORY_URL", "https://bagong.pagasa.dost.gov.ph/weather/weather-advisory")
REGIONAL_URL = os.environ.get("PAGASA_REGIONAL_URL", "https://bagong.pagasa.dost.gov.ph/regional-forecast/nlprsd")
# names PAGASA uses in the rainfall table (provinces, island groups, regions) – to tell one day's list from the next
PH_AREAS = sorted({
    "Abra", "Agusan del Norte", "Agusan del Sur", "Aklan", "Albay", "Antique", "Apayao", "Aurora", "Basilan", "Bataan",
    "Batanes", "Batangas", "Benguet", "Biliran", "Bohol", "Bukidnon", "Bulacan", "Cagayan", "Camarines Norte",
    "Camarines Sur", "Camiguin", "Capiz", "Catanduanes", "Cavite", "Cebu", "Cotabato", "Davao de Oro", "Davao del Norte",
    "Davao del Sur", "Davao Occidental", "Davao Oriental", "Dinagat Islands", "Eastern Samar", "Guimaras", "Ifugao",
    "Ilocos Norte", "Ilocos Sur", "Iloilo", "Isabela", "Kalinga", "La Union", "Laguna", "Lanao del Norte",
    "Lanao del Sur", "Leyte", "Maguindanao", "Maguindanao del Norte", "Maguindanao del Sur", "Marinduque", "Masbate",
    "Misamis Occidental", "Misamis Oriental", "Mountain Province", "Negros Occidental", "Negros Oriental",
    "Northern Samar", "Nueva Ecija", "Nueva Vizcaya", "Occidental Mindoro", "Oriental Mindoro", "Palawan", "Pampanga",
    "Pangasinan", "Quezon", "Quirino", "Rizal", "Romblon", "Samar", "Sarangani", "Siquijor", "Sorsogon",
    "South Cotabato", "Southern Leyte", "Sultan Kudarat", "Sulu", "Surigao del Norte", "Surigao del Sur", "Tarlac",
    "Tawi-Tawi", "Zambales", "Zamboanga del Norte", "Zamboanga del Sur", "Zamboanga Sibugay", "Metro Manila",
    "Babuyan Islands", "Polillo Islands", "Calamian Islands", "Kalayaan Islands", "Cuyo Islands", "Burias Island",
    "Ticao Island", "Siargao", "Bucas Grande", "Ilocos Region", "Cordillera Administrative Region", "Cagayan Valley",
    "Central Luzon", "CALABARZON", "MIMAROPA", "Bicol Region", "Western Visayas", "Central Visayas", "Eastern Visayas",
    "Zamboanga Peninsula", "Northern Mindanao", "Davao Region", "SOCCSKSARGEN", "Caraga", "BARMM", "Baguio City",
}, key=len, reverse=True)
RAIN_CLASSES = [(">200 mm", re.compile(r"\(\s*>\s*200\s*mm\s*\)")),
                ("100–200 mm", re.compile(r"\(\s*100\s*[–-]\s*200\s*mm\s*\)")),
                ("50–100 mm", re.compile(r"\(\s*50\s*[–-]\s*100\s*mm\s*\)"))]
_IMPACT = re.compile(r"\s(Widespread|Numerous|Localized|Isolated|Flooding|Landslide)\b")


def _cells(text: str, n: int) -> list[list[str]]:
    """'Ilocos Norte, Apayao, and Cagayan Ilocos Norte, Apayao, and Cagayan Batanes' → one list per day (n days).
    Names joined by ',' / 'and' are one day; a name right after another (only a space between) or '-' starts the next."""
    cells: list[list[str]] = []
    cur: list[str] | None = None
    after_sep = False
    i, t = 0, text.strip()
    while i < len(t):
        if t[i].isspace():
            i += 1
        elif t[i] == "-" and (i + 1 == len(t) or t[i + 1].isspace()):     # an empty day
            if cur is not None:
                cells.append(cur)
            cells.append([])
            cur, after_sep = None, False
            i += 1
        elif t[i] in ",;":
            after_sep = True
            i += 1
        elif m := re.match(r"(and|&)\s", t[i:]):
            after_sep = True
            i += m.end()
        else:
            name = next((a for a in PH_AREAS if t[i:i + len(a)].lower() == a.lower()
                         and (i + len(a) == len(t) or not t[i + len(a)].isalpha())), None)
            if name is None:                          # other words ("mainland", "the northern portion of …"): skip
                j = t.find(" ", i)
                i = len(t) if j < 0 else j + 1
                continue
            if cur is not None and after_sep:
                cur.append(name)
            else:                                     # a name straight after another one starts the next day
                if cur is not None:
                    cells.append(cur)
                cur = [name]
            after_sep = False
            i += len(name)
    if cur is not None:
        cells.append(cur)
    return (cells + [[] for _ in range(n)])[:n]


def parse_weather_advisory(html: str) -> dict | None:
    """Heavy rainfall outlook of the PAGASA Weather Advisory → {"number", "issued", "days", "rows": [{class, by_day,
    impact}], "car": {province: [(day, class)]}}; None when there is no advisory."""
    m = re.search(r"WEATHER ADVISORY NO\.?\s*(\d+)", html, flags=re.I)
    if not m:
        return None
    seg = html[m.start(): m.start() + 20000]
    p = re.search(r"<p>(.*?)</p>", seg, flags=re.S)
    text = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", " ", p.group(1) if p else ""))).strip()
    issued = re.search(r"ISSUED AT:\s*([^<]+)", seg)
    head = re.search(r"Forecast Rainfall\s+(.*?)\s+Potential Impacts", text)
    days = re.findall(r"(Today|Tonight|Tomorrow|(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)(?:\s*\([^)]*\))?)",
                      head.group(1)) if head else ["Today", "Tomorrow", "Day 3"]
    marks = [(lab, rx.search(text)) for lab, rx in RAIN_CLASSES]
    marks = sorted([(lab, mm) for lab, mm in marks if mm], key=lambda x: x[1].start())
    rows = []
    for k, (lab, mm) in enumerate(marks):
        end = marks[k + 1][1].start() if k + 1 < len(marks) else len(text)
        body = text[mm.end():end]
        imp = _IMPACT.search(" " + body)
        cells_text, impact = (body[:imp.start()], body[imp.start():].strip()) if imp else (body, "")
        impact = impact.split(" Forecast rainfall may be higher")[0].strip()
        rows.append({"class": lab, "by_day": dict(zip(days, _cells(cells_text, len(days)))), "impact": impact})
    car: dict[str, list[tuple[str, str]]] = {}
    for r in rows:
        for day, names in r["by_day"].items():
            for n in names:
                prov = clean_name(n)
                if prov in CAR_PROVINCES or prov == "CORDILLERA ADMINISTRATIVE REGION" or prov == "BAGUIO":
                    car.setdefault(CAR_PROVINCES.get(prov, n), []).append((day, r["class"]))
    nxt = re.search(r"next Weather Advisory will be issued at ([^.]+)\.", text)
    return {"number": int(m.group(1)), "issued": issued.group(1).strip() if issued else "", "days": days,
            "rows": rows, "car": car, "next": nxt.group(1).strip() if nxt else "", "url": ADVISORY_URL}


def parse_regional_warnings(html: str) -> list[dict]:
    """Heavy Rainfall Warning / Thunderstorm Advisory of PAGASA's Northern Luzon office, when one is in effect."""
    out = []
    for tab, kind in (("rainfalls", "Heavy Rainfall Warning"), ("thunderstorms", "Thunderstorm Advisory")):
        m = re.search(rf"""id=["']{tab}["'][^>]*>(.*?)</div>\s*</div>""", html, flags=re.S)
        if not m:
            continue
        text = " ".join(_lines(m.group(1)))
        if not text or re.search(r"there is no", text, flags=re.I):
            continue
        out.append({"kind": kind, "text": text[:1500], "car": _mentions_car(text)})
    return out


# --------------------------------------------------- CAR areas per signal ---

def _top_split(text: str) -> list[str]:
    """Split on commas, semicolons and " and " outside parentheses."""
    parts, depth, cur, i = [], 0, "", 0
    while i < len(text):
        ch = text[i]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if depth == 0 and (ch in ",;" or text.startswith(" and ", i)):
            parts.append(cur)
            cur = ""
            i += 5 if text.startswith(" and ", i) else 1
            continue
        cur += ch
        i += 1
    parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


def _province_in(seg: str) -> str | None:
    outside = re.sub(r"\(.*?\)", " ", seg)
    up = clean_name(outside)
    for p in sorted(CAR_PROVINCES, key=len, reverse=True):          # "MOUNTAIN PROVINCE" before shorter names
        if re.search(rf"\b{p}\b", up):
            return p
    return None


def car_signals(signals: dict[int, dict]) -> tuple[dict[str, int], list[str]]:
    """{area_key: highest signal} for the CAR municipalities named in the TCWS tables, and notes on what was read."""
    gaz = reference.gazetteer()
    towns = gaz.muni
    out: dict[str, int] = {}
    notes: list[str] = []
    for n in sorted(signals, reverse=True):                          # highest first: "the rest of" excludes them
        text = signals[n].get("luzon", "")
        for seg in _top_split(text):
            if re.search(r"\bBAGUIO\b", clean_name(seg)) and not _province_in(seg):
                out.setdefault("BENGUET|BAGUIO", n)
                continue
            prov = _province_in(seg)
            if not prov:
                continue
            in_prov = towns[towns.province == prov]
            named = re.search(r"\((.*?)\)", seg)
            if named:
                keys = []
                for name in re.split(r",|\band\b", named.group(1)):
                    name = name.strip()
                    if not name:
                        continue
                    m = match_name(name, prov, "municipal", gaz, None, "tcws")
                    if m["area_key"] and m["area_key"].startswith(prov + "|"):
                        keys.append(m["area_key"])
                    else:
                        notes.append(f"Signal {n}: '{name}' ({CAR_PROVINCES[prov]}) not found in the gazetteer.")
            elif re.search(r"\b(rest|remaining|remainder)\b", seg, flags=re.I):
                keys = [k for k in in_prov.area_key if k not in out]
            else:
                keys = list(in_prov.area_key)
            for k in keys:
                out.setdefault(k, n)
            notes.append(f"Signal {n}: {seg.strip()} → {len(keys)} municipalit{'y' if len(keys) == 1 else 'ies'}.")
    return out, notes


def _mentions_car(text: str) -> bool:
    up = clean_name(text)
    return "CORDILLERA" in up or any(re.search(rf"\b{p}\b", up) for p in CAR_PROVINCES) or "BAGUIO" in up


# ------------------------------------------------------------------ payload ---

def _when(b: dict) -> str:
    try:
        t = datetime.fromisoformat(b["issued_at"])
        return f"{t.strftime('%I:%M %p').lstrip('0')}, {t.day} {t.strftime('%B %Y')}"
    except (TypeError, ValueError):
        return b.get("issued_text", "")


def _list(items: list[str]) -> str:
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""


RAIN_RANK = {"50–100 mm": 1, "100–200 mm": 2, ">200 mm": 3}


def situation(top: int, signal_provs: list[str], rain: dict[str, list[tuple[str, str]]], gusts: list[dict],
              hours_to_closest: float | None, in_buffer: bool) -> dict:
    """How close the danger is for CAR: 'imminent' (act within hours), 'approaching' (within a day or two) or 'watch'."""
    rain_today = max((RAIN_RANK.get(c, 0) for v in rain.values() for d, c in v if d.lower().startswith(("today", "tonight"))),
                     default=0)
    rain_any = max((RAIN_RANK.get(c, 0) for v in rain.values() for _, c in v), default=0)
    gust_today = any(g["day"].lower() in ("today", "tonight") for g in gusts)
    if top >= 2 or rain_today >= 2 or (in_buffer and hours_to_closest is not None and hours_to_closest <= 24):
        stage = "imminent"
    elif top >= 1 or rain_any or gusts or in_buffer:
        stage = "approaching"
    else:
        stage = "watch"
    where = sorted(set(signal_provs) | set(rain))
    return {"stage": stage, "where": where, "rain_today": rain_today, "rain_any": rain_any, "gust_today": gust_today}


def recommendations(top: int, signal_provs: list[str], rain: dict[str, list[tuple[str, str]]], gusts: list[dict],
                    hours_to_closest: float | None = None, in_buffer: bool = False, rain_impacts: dict | None = None) -> str:
    """Farm advisory for CAR: what to do now, during and after the storm – concrete steps, more urgent as it nears."""
    s = situation(top, signal_provs, rain, gusts, hours_to_closest, in_buffer)
    where = _list(s["where"]) if s["where"] else "CAR"
    lines: list[str] = []
    n = 0

    def add(text: str):
        nonlocal n
        n += 1
        lines.append(f"{n}. {text}")

    # the situation, one short line each
    if top:
        lines.append(f"Signal No. {top} in {_list(signal_provs)}: {WINDS[top].split(' (')[0]} winds within {LEAD.get(top, '36 hours')}.")
    for prov, days in sorted(rain.items()):
        worst = max(days, key=lambda d: RAIN_RANK.get(d[1], 0))[1]
        when = _list([d.lower() if d.lower().startswith("to") else d for d, _ in days])
        lines.append(f"Heavy rain in {prov} {when} ({worst}): floods and landslides possible.")
    if gusts:
        lines.append("Strong gusts over CAR " + _list([g["day"].lower() if g["day"].lower().startswith("to") else g["day"]
                                                     for g in gusts]) + ", mostly in uplands.")

    if s["stage"] == "watch":
        lines.append("Prepare now, while the weather is fine:")
        add("Harvest mature rice, corn and vegetables.")
        add("Clean canals and paddy outlets.")
        add("Tie down greenhouse plastic, trellises and roofs.")
        add("Keep seeds, fertilizer and feed dry, up high.")
        add("Follow PAGASA every 6 hours.")
        return "\n".join(lines)

    urgent = s["stage"] == "imminent"
    lines.append(f"{'NOW – within 12 hours' if urgent else 'Before the storm – within 24 hours'} ({where}):")
    add("Harvest rice at 85% ripe and dry-husked corn – low-lying fields first.")
    add("Store the harvest in sacks, 30 cm off the floor, under tarpaulin.")
    add("Harvest ready vegetables; roll up greenhouse plastic.")
    add("Cut banana leaves to 3–4 and prop with bamboo; stake young trees.")
    add("Open paddy outlets and clear canals; net fishpond dikes.")
    add("Move animals to high, sheltered pens with 3 days of feed and water.")
    add("Keep seeds and fertilizer dry; move tools and machines up high.")
    add("Do not plant, spray or fertilize until the weather clears.")
    if s["rain_any"] or top:
        add("Near slopes or rivers? Leave at once if you see cracks, tilting trees or muddy water.")
    add("Charge your phone, keep a radio, know your evacuation centre.")
    lines.append("During the storm:")
    add("Stay indoors – do not check fields or animals in the storm.")
    add("Do not cross swollen rivers; keep away from slopes.")
    add("Listen to PAGASA updates every 6 hours.")
    lines.append("After the storm:")
    add("Go back to the fields only when winds and rivers have calmed.")
    add("Drain flooded fields; dry wet palay and corn within a day.")
    add("Photograph damage and report it to the MAO; insured farmers: file with PCIC.")
    add("Ask the MAO for replanting seeds; use early-maturing varieties.")
    return "\n".join(lines)


def crop_advice(top: int, stage: str = "approaching") -> dict[str, str]:
    """Short, doable advice per crop for the recommendations page and the A4."""
    if stage == "watch":
        return {
            "advice_rice": "Plan an early harvest of mature fields; keep paddy outlets and canals clear.",
            "advice_corn": "Harvest ears with dry husks; hill up young corn so it stands firmer.",
            "advice_hvc": "Harvest vegetables ready for market; check that greenhouse plastic and trellises are tied down.",
            "advice_livestock": "Check pens and roofs; keep a few days of feed and water ready.",
        }
    now = "now" if stage == "imminent" else "today"
    return {
        "advice_rice": f"Harvest fields at least 85% ripe {now}; open paddy outlets so water does not stand over the "
                       "plants. Store palay in sacks off the floor, covered.",
        "advice_corn": f"Harvest ears whose husks are dry {now}; hill up and tie standing corn. Store it in a dry, raised place."
                       + (" Expect lodging in exposed fields." if top >= 2 else ""),
        "advice_hvc": "Harvest vegetables ready for market (cabbage, carrots, potatoes, lettuce); roll up or tie down "
                      "rain-shelter and greenhouse plastic; stake tomatoes, beans and peas; prop up bananas.",
        "advice_livestock": "Move animals to sheltered pens on high ground away from rivers and slopes; keep 3 days of "
                            "feed and water; close the sides of poultry houses.",
    }


def build_payload(b: dict, others: list[dict] | None = None, settings: dict | None = None) -> dict:
    settings = settings or {}
    by_key, notes = car_signals(b.get("signals") or {})
    keys = reference.gazetteer_table().area_key
    series = pd.Series({k: SIGNAL_LABELS[by_key[k]] if k in by_key else NO_SIGNAL for k in keys})
    lyr = common.layer("tcws", "Wind signals in CAR", "tcws", "signal", LEGEND, series)
    top = max(by_key.values(), default=0)
    by_signal = {n: sorted(k for k, s in by_key.items() if s == n) for n in sorted(set(by_key.values()), reverse=True)}
    provinces = sorted({reference.province_display(reference.province_of(k)) for k in by_key})
    gust_car = [g for g in b.get("gusts", []) if _mentions_car(g["areas"])]
    rain_car = any(_mentions_car(l) for l in b.get("rainfall", []))
    issued = (datetime.fromisoformat(b["issued_at"]).date() if b.get("issued_at") else date.today())
    end = issued + timedelta(days=2)
    for f in b.get("forecast", []):
        try:
            d = datetime.strptime(f["time"], "%b %d, %Y %I:%M %p").date()
            if "OUTSIDE PAR" not in f["where"].upper():
                end = max(end, d)
        except ValueError:
            pass
    storm = f"{b.get('category') or 'Tropical cyclone'} {b.get('name') or ''}".strip()
    when = _when(b)
    label = f"{storm} – TC Bulletin #{b.get('bulletin_no') or '?'}, {when}"
    payload = {
        "type": TYPE, "ok": True, "title": TITLE,
        "subtitle": f"{storm} · as of {when}",
        "issued": issued.isoformat(),
        "period": {"kind": "event", "start": issued.isoformat(), "end": end.isoformat(), "label": label},
        "level": "municipal", "source": SOURCE, "layers": [lyr],
        "summary": {
            "class_counts": {c["label"]: c.get("count", 0) for c in lyr["legend"]["classes"]},
            "car_top_signal": top,
            "car_by_signal": {str(n): ks for n, ks in by_signal.items()},
            "car_provinces": provinces,
            "car_gusts": gust_car,
            "car_rain": rain_car,
            "others": [{"name": o.get("name"), "category": o.get("category"), "bulletin_no": o.get("bulletin_no")}
                       for o in (others or [])],
        },
        "tc": {k: b.get(k) for k in ("bulletin_no", "category", "name", "issued_text", "issued_at", "next_bulletin",
                                     "headline", "location_text", "lat", "lon", "movement", "strength", "max_wind_kmh",
                                     "gust_kmh", "forecast", "gusts", "rainfall", "highest_possible", "outlook",
                                     "track_image", "bulletin_pdf", "wind_notes")}
              | {"page_url": PAGE_URL,
                 "signals": {str(n): {"impact": s.get("impact", []), "what_to_do": s.get("what_to_do", [])}
                             for n, s in (b.get("signals") or {}).items()}},
        "method": {"fetched_from": PAGE_URL, "fetched_at": now_manila(), "read": notes},
        "report": {"errors": [], "warnings": [], "notes": notes},
    }
    # forecast track (bulletin PDF), its buffer (extent of the strong winds) and the distance from CAR
    tc = payload["tc"]
    tc.update({k: b.get(k) for k in ("track", "wind_extent_km", "storm_force_km", "pressure_hpa")})
    geom = None
    if b.get("track"):
        try:
            geom = track_geometry(tc)
        except Exception as e:  # noqa: BLE001
            log.warning("track geometry failed: %s", e)
    tc["track_geojson"] = track_feature_collection(tc, geom)
    if geom:
        payload["summary"]["car_distance"] = {k: geom[k] for k in ("now_km", "closest_km", "closest_time",
                                                                    "closest_where", "car_in_buffer",
                                                                    "car_in_strong_winds_now")}
    else:
        payload["report"]["warnings"].append("The forecast track could not be read from the bulletin PDF – the map "
                                             "shows the present position only.")
    # heavy rainfall: PAGASA Weather Advisory (forecast rain per day by province) and Northern Luzon warnings
    adv = b.get("advisory")
    rain = {p: [list(x) for x in v] for p, v in ((adv or {}).get("car") or {}).items()}
    if adv:
        tc["rain_advisory"] = {k: adv[k] for k in ("number", "issued", "days", "rows", "next", "url")}
    regional = [w for w in b.get("regional") or [] if w.get("car")]
    if regional:
        tc["regional_warnings"] = regional
    payload["summary"]["car_rainfall"] = rain
    payload["summary"]["car_rain"] = rain_car = bool(rain_car or rain or regional)
    # how soon: hours from the bulletin to the storm's closest approach to CAR
    hours = None
    d = payload["summary"].get("car_distance") or {}
    try:
        t_close = datetime.strptime(d.get("closest_time") or "", "%I:%M %p %d %B %Y")
        hours = (t_close - datetime.fromisoformat(b["issued_at"])).total_seconds() / 3600
    except (ValueError, TypeError, KeyError):
        pass
    signal_provs = sorted({reference.province_display(reference.province_of(k)) for k in by_key})
    sit = situation(top, signal_provs, rain, gust_car, hours, bool(d.get("car_in_buffer")))
    payload["summary"]["situation"] = {**sit, "hours_to_closest": round(hours) if hours is not None else None}
    impacts = {r["class"]: r["impact"] for r in (adv or {}).get("rows", [])}
    payload["valid_text"] = b.get("next_bulletin") or "Valid until the next PAGASA bulletin"
    payload["texts"] = common.base_texts(payload, settings)
    payload["texts"]["legend_title"] = "Tropical Cyclone Wind Signals (TCWS)"
    payload["texts"]["data_credit"] = "DOST-PAGASA"
    payload["recommendations_draft"] = recommendations(top, signal_provs, rain, gust_car, hours,
                                                       bool(d.get("car_in_buffer")), impacts)
    payload["texts"]["recommendations"] = payload["recommendations_draft"]
    payload["crop_advice_draft"] = crop_advice(top, sit["stage"])
    payload["texts"].update(payload["crop_advice_draft"])
    payload["texts"]["notes"] = ("Wind signals and forecasts: DOST-PAGASA Tropical Cyclone Bulletin. Local winds may be "
                                 "stronger in upland and exposed areas. Check the latest PAGASA bulletin, issued every 6 hours.")
    if not by_key and not gust_car and not rain_car:
        payload["report"]["warnings"].append(f"{storm} has no wind signal over CAR and the bulletin does not mention CAR.")
    return payload


def build_from_pagasa(settings: dict | None = None, html: str | None = None, pdf: bytes | None = None,
                      advisory_html: str | None = None, regional_html: str | None = None,
                      track_png: bytes | None = None) -> dict:
    """``html`` / ``pdf`` / ``advisory_html`` / ``regional_html`` / ``track_png``: the bulletin page and PDF, the
    Weather Advisory, the Northern Luzon page and PAGASA's track image (tests); fetched from PAGASA when not given."""
    fetching = html is None
    html = html if html is not None else fetch_html()
    tcs = parse_page(html)
    if not tcs:
        return {"ok": False, "error": "PAGASA has no active tropical cyclone bulletin right now.", "payload": None}
    # the cyclone that affects CAR the most (highest signal, then named in the outlook), else the first one
    def weight(b):
        s, _ = car_signals(b.get("signals") or {})
        return (max(s.values(), default=0), any(_mentions_car(g["areas"]) for g in b.get("gusts", [])))
    tcs.sort(key=weight, reverse=True)
    b = tcs[0]
    if pdf is None and fetching and b.get("bulletin_pdf"):
        try:
            from .pagasa_seasonal import _get
            pdf = _get(b["bulletin_pdf"], retries=2, timeout=60)
        except Exception as e:  # noqa: BLE001
            log.warning("bulletin PDF %s not available: %s", b["bulletin_pdf"], e)
    if pdf:
        try:
            b.update(parse_pdf(pdf))
        except Exception as e:  # noqa: BLE001
            log.warning("bulletin PDF could not be read: %s", e)
    from .pagasa_seasonal import _get
    try:
        if track_png is None and fetching and b.get("track_image"):
            track_png = _get(b["track_image"], retries=2, timeout=40)
        b["storm_force_km"] = storm_force_km(track_png, b.get("wind_extent_km"))
    except Exception as e:  # noqa: BLE001
        log.warning("PAGASA track image not available: %s", e)
    for key, page, url, parse in (("advisory", advisory_html, ADVISORY_URL, parse_weather_advisory),
                                  ("regional", regional_html, REGIONAL_URL, parse_regional_warnings)):
        try:
            if page is None and fetching:
                page = _get(url, retries=2, timeout=40).decode("utf-8", errors="replace")
            if page:
                b[key] = parse(page)
        except Exception as e:  # noqa: BLE001
            log.warning("%s (%s) not available: %s", key, url, e)
    payload = build_payload(b, tcs[1:], settings)
    return {"ok": True, "payload": payload, "count": len(tcs)}


def run_once(settings: dict | None = None) -> dict:
    try:
        res = build_from_pagasa(settings)
    except Exception as e:  # noqa: BLE001
        log.exception("PAGASA TC bulletin fetch failed")
        return {"ok": False, "error": f"Could not read the PAGASA bulletin: {e}", "payload": None}
    if not res["ok"]:
        return res
    p = res["payload"]
    return {"ok": True, "payload": p, "state": {"fetched_at": p["method"]["fetched_at"], "tc": p["tc"]["name"],
                                                 "bulletin": p["tc"]["bulletin_no"]}}
