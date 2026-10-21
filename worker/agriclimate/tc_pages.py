"""Special Farm Weather Outlook and Advisory (tropical cyclone) – the exported images.

  * **A4, one page, for printing** (PDF + PNG, 1240 × 1754 design units → 3720 × 5262 px = A4 at 450 dpi): everything
    on one sheet – the storm, the track map (PAGASA's style, with CAR by wind signal), the
    storm's position / movement / strength, the CAR areas under each signal, what CAR can expect, the farm actions
    and the crop advice. Text shrinks as far as needed so that it always fits the one page.
  * **Facebook posts** (4:5, 1080 × 1350 → 2160 × 2700 px, the portrait size Facebook shows uncropped): the advisory
    (track map with CAR's wind signals, its key, summary), what to do (before / during / after the storm) and the
    crop and livestock advice. Light, minimalist cards, large type for phones.

Everything keeps a 40-unit margin from the edges, so nothing is cut when Facebook or a printer trims the image.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from PIL import Image

from . import pages, reference
from .envi.presentation import GREEN, GREEN_DARK, INK, LIGHT, MUTED, PANEL_TEXT, _hex
from .pages import _canvas, _fit, _footer, _header, _save

log = logging.getLogger("agriclimate.tc_pages")
A4 = pages.PORTRAIT                   # 1240 × 1754 design units (A4 portrait)
A4_DPI = 450                          # 3720 px over 210 mm
FACEBOOK = (1080, 1350)               # 4:5
FACEBOOK_PX = (2160, 2700)
ORANGE = (150, 60, 0)
CARD = (247, 249, 248)                # light card background
LINE = (222, 229, 225)                # hairlines and card outlines
RAIN = (30, 100, 200)
# section of the steps → colour of its label (most urgent first)
SECTION_COLORS = [("now", (198, 40, 40)), ("before", (216, 84, 0)), ("prepare", (176, 112, 0)),
                  ("during", (21, 101, 192)), ("after", GREEN)]


def _cat_color(category: str | None) -> tuple:
    c = (category or "").lower()
    if "typhoon" in c:
        return (198, 40, 40)
    if "severe" in c:
        return (216, 84, 0)
    if "storm" in c:
        return (230, 124, 0)
    return (2, 119, 189)


def _on(color: tuple) -> tuple:
    """Text colour that reads on a background colour."""
    r, g, b = color[:3]
    return INK if 0.299 * r + 0.587 * g + 0.114 * b > 160 else (255, 255, 255)


def _pill(cv, x, y, text: str, color: tuple, fs: float, max_w: float | None = None) -> tuple[float, float]:
    """A rounded label; returns its (width, height)."""
    if max_w:
        fs = _fit(cv, text, "bold", fs, max_w - fs * 1.4, 10)
    w, h = cv.width(text, "bold", fs) + fs * 1.4, fs * 1.7
    cv.rrect(x, y, w, h, color, r=h / 2)
    cv.text(x + w / 2, y + h / 2, text, "bold", fs, _on(color), anchor="mm")
    return w, h


def _section_color(head: str) -> tuple:
    h = head.lower()
    return next((c for k, c in SECTION_COLORS if h.startswith(k) or f" {k} " in f" {h} "), GREEN)


# ------------------------------------------------------------------- pieces ---

def track_map(payload: dict, out_dir: Path, w: float, h: float, tag: str, units_per_inch: float = 110,
              legend: bool = True, inset: bool = False) -> Path:
    """The track map for a panel of w × h design units, drawn at the size it is shown: on the A4 1 inch = 150 units
    (1240 units = 210 mm), so the map's font sizes are the printed sizes; Facebook (seen on phones) uses fewer
    units per inch, i.e. relatively larger text."""
    from . import tc_map
    path = out_dir / f"tc_track_map_{tag}.png"
    if not path.exists():
        tc_map.render(payload, path, (w / units_per_inch, h / units_per_inch), dpi=450, legend=legend, inset=inset)
    return path


def _crop_transparent(path: Path) -> Image.Image:
    im = Image.open(path).convert("RGBA")
    box = im.getbbox()
    return im.crop(box) if box else im


def _signal_rows(payload: dict) -> list[tuple[int, str, list[str]]]:
    """[(signal, province, [municipalities])] – highest signal first."""
    out = []
    for n, keys in sorted(((int(n), ks) for n, ks in (payload["summary"].get("car_by_signal") or {}).items()), reverse=True):
        by: dict[str, list[str]] = {}
        for k in keys:
            by.setdefault(reference.province_display(reference.province_of(k)), []).append(reference.area_label(k))
        for prov, towns in sorted(by.items()):
            out.append((n, prov, sorted(towns)))
    return out


def _signal_color(payload: dict, n: int) -> tuple:
    lg = payload["layers"][0]["legend"]["classes"]
    return _hex(next((c["color"] for c in lg if c["label"] == f"Wind Signal No. {n}"), "#cccccc"))


def _actions(payload: dict) -> list[str]:
    rec = payload.get("texts", {}).get("recommendations") or ""
    return [re.sub(r"^\d+\.\s*", "", l.strip()) for l in rec.split("\n") if re.match(r"^\d+\.", l.strip())]


def _storm(payload: dict) -> str:
    tc = payload.get("tc") or {}
    return f"{tc.get('category') or 'Tropical cyclone'} “{(tc.get('name') or '').title()}”"


def _storm_band(cv, payload: dict, y: float, x: float = 40, w: float | None = None, big: float = 40) -> float:
    """The storm on a white card: category label, name, bulletin, and PAGASA's headline in the category colour."""
    tc = payload.get("tc") or {}
    w = w or cv.W - 80
    col = _cat_color(tc.get("category"))
    meta = f"PAGASA Tropical Cyclone Bulletin #{tc.get('bulletin_no') or '?'}  ·  {tc.get('issued_text') or ''}"
    head = tc.get("headline") or ""
    hl = cv.wrap(head, "semibold", big * 0.55, w - 56)[:2] if head else []
    h = 22 + big * 1.25 + big * 0.55 * 1.45 + len(hl) * big * 0.55 * 1.32 + 16
    cv.rrect(x, y, w, h, (255, 255, 255), r=18, outline=LINE, width=2)
    cv.rrect(x, y + 16, 7, h - 32, col, r=3)
    pw, ph = _pill(cv, x + 28, y + 18 + (big * 1.1 - big * 0.5 * 1.7) / 2, (tc.get("category") or "Tropical cyclone").upper(),
                   col, big * 0.5)
    name = (tc.get("name") or "").upper()
    cv.d.text(((x + 28 + pw + 16) * cv.s, (y + 18) * cv.s), name,
              font=pages._extrabold(cv, _fit(cv, name, "bold", big, w - pw - 80, 18)), fill=INK)
    yy = y + 22 + big * 1.25
    cv.text(x + 28, yy, meta, "semibold", _fit(cv, meta, "semibold", big * 0.55, w - 56, 12), MUTED)
    yy += big * 0.55 * 1.45
    for l in hl:
        cv.text(x + 28, yy, l, "semibold", big * 0.55, col)
        yy += big * 0.55 * 1.32
    return y + h + 14


def _storm_strip(cv, payload: dict, y: float, h: float = 64) -> float:
    """The storm in one line (Facebook): category label, name, bulletin number."""
    tc = payload.get("tc") or {}
    col = _cat_color(tc.get("category"))
    W = cv.W
    cv.rrect(40, y, W - 80, h, (255, 255, 255), r=16, outline=LINE, width=2)
    cv.rrect(40, y + 12, 7, h - 24, col, r=3)
    meta = f"PAGASA Bulletin #{tc.get('bulletin_no') or '?'}"
    mw = cv.width(meta, "semibold", 20)
    pw, _ = _pill(cv, 64, y + (h - 20 * 1.7) / 2, (tc.get("category") or "Tropical cyclone").upper(), col, 20)
    name = (tc.get("name") or "").upper()
    cv.d.text(((64 + pw + 14) * cv.s, (y + h / 2) * cv.s), name,
              font=pages._extrabold(cv, _fit(cv, name, "bold", 36, W - 200 - pw - mw, 18)), fill=INK, anchor="lm")
    cv.text(W - 62, y + h / 2, meta, "semibold", 20, MUTED, anchor="rm")
    return y + h + 12


def _fact(cv, x, y, w, h, title: str, body: str, color=GREEN_DARK, size: float = 21):
    cv.rrect(x, y, w, h, LIGHT, r=14)
    cv.rect(x, y + 14, 6, h - 28, color)
    cv.text(x + 20, y + 12, title.upper(), "bold", size * 0.8, color)
    while size > 12 and len(cv.wrap(body, "semibold", size, w - 36)) * size * 1.28 > h - size * 0.8 - 30:
        size -= 1
    cv.para(x + 20, y + 20 + size * 0.8, body, w - 36, style="semibold", size=size, fill=INK, lh=1.28)


def _panel(cv, img: Path | Image.Image | None, x, y, w, h, caption: str, missing: str = ""):
    cv.rrect(x, y, w, h, (255, 255, 255), r=14, outline=(214, 222, 216), width=2)
    cv.text(x + 16, y + 10, caption, "bold", _fit(cv, caption, "bold", 20, w - 32, 12), GREEN_DARK)
    if img is None:
        cv.para(x + 16, y + 56, missing, w - 32, size=17, fill=MUTED)
        return
    cv.paste(img, x + 8, y + 40, w - 16, h - 48)


def _facts(payload: dict) -> list[tuple[str, str]]:
    tc = payload.get("tc") or {}
    d = (payload.get("summary") or {}).get("car_distance") or {}
    nxt = (tc.get("next_bulletin") or "").replace("Valid for broadcast until the next advisory to be issued at ", "")
    strength = (f"{tc['max_wind_kmh']:.0f} km/h winds, gusts up to {tc['gust_kmh']:.0f} km/h" if tc.get("max_wind_kmh")
                else tc.get("strength") or "–")
    out = [("Location", tc.get("location_text") or "–"), ("Movement", (tc.get("movement") or "–").replace("Moving ", "")),
           ("Strength", strength)]
    if d.get("closest_km") is not None:
        from .tc_map import _short_time
        out.append(("Closest to CAR", f"About {d['closest_km']:,} km ({_short_time(d.get('closest_time') or '')})"))
    else:
        out.append(("Next bulletin", nxt or "Every 6 hours"))
    return out


# -------------------------------------------- text columns (fit to a box) ---

def _column(cv, x, y, w, blocks: list[tuple], fs: float, draw: bool = True) -> float:
    """Draw (or only measure) text blocks top to bottom; returns the bottom y.

    blocks: ("head", text) | ("sub", text) | ("para", text[, style, color]) | ("num", n, text) | ("bullet", text) |
            ("swatch", color, head, body) | ("crop", label, color, text) | ("gap", h)"""
    for b in blocks:
        kind = b[0]
        if kind == "gap":
            y += b[1]
        elif kind == "head":
            lines = cv.wrap(b[1], "bold", fs + 2, w)
            for i, l in enumerate(lines):
                if draw:
                    cv.text(x, y, l, "bold", fs + 2, GREEN_DARK)
                y += (fs + 2) * (1.22 if i < len(lines) - 1 else 1.5)
        elif kind == "sub":
            # the section of the steps ("Before the storm – …"), as a coloured label
            y += fs * 0.35
            sfs = fs * 0.82
            text = b[1].upper()
            col = _section_color(b[1])
            lines = cv.wrap(text, "bold", sfs, w - sfs * 1.4)
            if draw:
                if len(lines) == 1:
                    _pill(cv, x, y, text, col, sfs)
                else:
                    cv.rrect(x, y, w, len(lines) * sfs * 1.3 + sfs * 0.6, col, r=sfs * 0.6)
                    for i, l in enumerate(lines):
                        cv.text(x + sfs * 0.7, y + sfs * 0.3 + i * sfs * 1.3, l, "bold", sfs, _on(col))
            y += (sfs * 1.7 if len(lines) == 1 else len(lines) * sfs * 1.3 + sfs * 0.6) + fs * 0.55
        elif kind == "para":
            style = b[2] if len(b) > 2 else "regular"
            color = b[3] if len(b) > 3 else INK
            for l in cv.wrap(b[1], style, fs - 1, w):
                if draw:
                    cv.text(x, y, l, style, fs - 1, color)
                y += (fs - 1) * 1.3
            y += 6
        elif kind in ("num", "bullet"):
            ind = fs * 1.75
            lines = cv.wrap(b[2] if kind == "num" else b[1], "regular", fs - 1, w - ind)
            if draw:
                if kind == "num":
                    r = fs * 0.62
                    cy = y + (fs - 1) * 0.62
                    cv.d.ellipse([(x + r * 0.1) * cv.s, (cy - r) * cv.s, (x + r * 2.1) * cv.s, (cy + r) * cv.s], fill=GREEN)
                    n = str(b[1])
                    cv.text(x + r * 1.1, cy, n, "bold", fs * (0.62 if len(n) > 1 else 0.7), (255, 255, 255), anchor="mm")
                else:
                    r = fs * 0.17
                    cv.d.ellipse([(x + 5 - r) * cv.s, (y + fs * 0.55 - r) * cv.s, (x + 5 + r) * cv.s,
                                  (y + fs * 0.55 + r) * cv.s], fill=GREEN)
                for i, l in enumerate(lines):
                    cv.text(x + ind, y + i * (fs - 1) * 1.3, l, "regular", fs - 1, INK)
            y += len(lines) * (fs - 1) * 1.3 + max(5, fs * 0.38)
        elif kind == "swatch":
            _, color, head, body = b
            if draw:
                cv.rect(x, y + 3, fs * 1.1, fs * 0.85, color, outline=(90, 90, 90))
                cv.text(x + fs * 1.6, y, head, "bold", fs, INK)
            y += fs * 1.32
            for l in cv.wrap(body, "regular", fs - 2, w - fs * 1.6):
                if draw:
                    cv.text(x + fs * 1.6, y, l, "regular", fs - 2, INK)
                y += (fs - 2) * 1.3
            y += 6
        elif kind == "crop":
            _, label, color, text = b
            lab = f"{label}: "
            lw = cv.width(lab, "bold", fs - 1)
            lines = cv.wrap(text, "regular", fs - 1, w - lw)
            if draw:
                cv.text(x, y, lab, "bold", fs - 1, color)
                for i, l in enumerate(lines):
                    cv.text(x + lw, y + i * (fs - 1) * 1.3, l, "regular", fs - 1, INK)
            y += len(lines) * (fs - 1) * 1.3 + 5
    return y


def _fit_columns(cv, cols: list[tuple[float, float, list[tuple]]], y: float, bottom: float, hi: float = 22, lo: float = 12) -> float:
    """Largest font size (hi → lo) with which every column fits between y and bottom; draws them."""
    fs = hi
    while fs > lo and any(_column(cv, x, y, w, blocks, fs, draw=False) > bottom for x, w, blocks in cols):
        fs -= 0.5
    for x, w, blocks in cols:
        _column(cv, x, y, w, blocks, fs)
    return fs


def _signal_blocks(payload: dict) -> list[tuple]:
    from .pagasa_tc import LEAD, WINDS
    rows = _signal_rows(payload)
    out: list[tuple] = [("head", "WIND SIGNALS IN CAR")]
    if not rows:
        out.append(("para", "No Tropical Cyclone Wind Signal is raised over the Cordillera Administrative Region in this "
                            "bulletin.", "semibold"))
    for n, prov, towns in rows:
        out.append(("swatch", _signal_color(payload, n), f"Signal No. {n} – {prov}", ", ".join(towns)))
    for n in sorted({n for n, _, _ in rows}, reverse=True):
        out.append(("para", f"Signal No. {n}: winds of {WINDS[n]} within {LEAD[n]}.", "italic", MUTED))
    s = payload.get("summary") or {}
    if s.get("car_gusts"):
        days = ", ".join(f"{g['day']} ({g['date']})" for g in s["car_gusts"])
        out.append(("para", f"Strong to gale-force gusts in CAR: {days}, especially in upland and exposed areas.",
                    "semibold", ORANGE))
    if s.get("car_rain") and not s.get("car_rainfall"):
        out.append(("para", "Heavy rain is expected over parts of CAR – see the PAGASA rainfall advisory.", "semibold", ORANGE))
    return out


def _crop_blocks(payload: dict) -> list[tuple]:
    t = payload.get("texts", {})
    return [("crop", lab, _hex(col), t[k]) for k, lab, col in pages._ADVICE if t.get(k)]


def summary_rows(payload: dict) -> list[tuple[str, tuple, str]]:
    """The outlook in a few short rows [(tag, colour, text)] for the first Facebook post: the storm, the CAR towns under
    each signal, rain, gusts and how soon to act. No repetition of the map or of the steps (they are on the next post)."""
    from .tc_map import _short_time
    tc = payload.get("tc") or {}
    s = payload.get("summary") or {}
    rows: list[tuple[str, tuple, str]] = []
    if tc.get("location_text"):
        wind = f"; winds {tc['max_wind_kmh']:.0f} km/h" if tc.get("max_wind_kmh") else ""
        move = (tc.get("movement") or "").replace("Moving ", "moving ").lower()
        rows.append(("STORM", _cat_color(tc.get("category")), f"{tc['location_text'].split(' (')[0]}, {move}{wind}."))
    sig = _signal_rows(payload)
    for n, prov, towns in sig:
        rows.append((f"SIGNAL {n}", _signal_color(payload, n), f"{prov}: {', '.join(towns)}"))
    if not sig:
        rows.append(("SIGNALS", (176, 190, 197), "No wind signal over CAR yet."))
    for prov, days in sorted((s.get("car_rainfall") or {}).items()):
        worst = max(days, key=lambda d: {"50–100 mm": 1, "100–200 mm": 2, ">200 mm": 3}.get(d[1], 0))[1]
        when = pages._list([d.lower() if d.lower().startswith("to") else d for d, _ in days])
        rows.append(("HEAVY RAIN", RAIN, f"{prov}, {when} ({worst}). Floods and landslides possible."))
    if s.get("car_gusts"):
        days = pages._list([g["day"].lower() if g["day"].lower().startswith("to") else g["day"] for g in s["car_gusts"]])
        rows.append(("GUSTS", (176, 112, 0), f"Strong gusts over CAR {days}, mostly in uplands."))
    d = s.get("car_distance") or {}
    act = {"imminent": "Act now", "approaching": "Prepare within 24 hours"}.get((s.get("situation") or {}).get("stage"),
                                                                                "Get ready")
    if d.get("closest_km") is not None:
        rows.append(("ACT", GREEN, f"{act}. Closest to CAR {_short_time(d.get('closest_time') or '')}, "
                                   f"about {d['closest_km']:,} km away."))
    else:
        rows.append(("ACT", GREEN, f"{act}."))
    return rows


def _summary_card(cv, payload: dict, x: float, y: float, w: float, bottom: float, hi: float = 28, lo: float = 15):
    """Summary as rows: a coloured tag, then the text; hairlines between rows."""
    rows = summary_rows(payload)
    cv.rrect(x, y, w, bottom - y, CARD, r=18)
    cv.text(x + 26, y + 18, "Summary", "bold", 30, GREEN_DARK)
    cv.text(x + w - 26, y + 24, "What to do: next posts  →", "semibold", 19, MUTED, anchor="ra")
    top = y + 72

    def layout(fs):
        tag_w = max(cv.width(t, "bold", fs * 0.62) for t, _, _ in rows) + fs * 0.62 * 1.4
        tx, tw = x + 26 + tag_w + 18, w - 52 - tag_w - 18
        hs = [max(fs * 0.62 * 1.7, len(cv.wrap(t, "regular", fs, tw)) * fs * 1.28) for _, _, t in rows]
        return tag_w, tx, tw, hs

    fs = hi
    while fs > lo:
        tag_w, tx, tw, hs = layout(fs)
        if sum(hs) + (len(rows) - 1) * fs * 0.9 <= bottom - top - 22:
            break
        fs -= 0.5
    tag_w, tx, tw, hs = layout(fs)
    gap = min(fs * 1.6, (bottom - top - 22 - sum(hs)) / max(1, len(rows) - 1))
    yy = top
    for i, ((tag, col, text), h) in enumerate(zip(rows, hs)):
        if i:
            cv.rect(x + 26, yy - gap / 2, w - 52, 1.5, LINE)
        _pill(cv, x + 26, yy + (fs * 1.28 - fs * 0.62 * 1.7) / 2, tag, col, fs * 0.62)
        for j, l in enumerate(cv.wrap(text, "regular", fs, tw)):
            cv.text(tx, yy + j * fs * 1.28, l, "regular", fs, INK)
        yy += h + gap


# -------------------------------------------------------- A4, one page (PDF) ---

def _a4_header(cv, payload: dict) -> float:
    """DA-RFO-CAR / AMIA letterhead with the three logos, then the green title bar; returns the y below it."""
    from .envi import config as envi_config
    W = cv.W
    x = 40
    for name, w in (("Bagong_Pilipinas_logo.png", 96), ("DA CAR LOGO no background.png", 104), ("AMIA_Logo.png", 92)):
        p = envi_config.LOGO_DIR / name
        if p.exists():
            _, _, lw, _ = cv.paste(p, x, 22, w, 96, align="left")
            x += lw + 16
    cv.d.line([((x + 2) * cv.s, 26 * cv.s), ((x + 2) * cv.s, 114 * cv.s)], fill=(160, 160, 160), width=int(2 * cv.s))
    tx, tw = x + 22, W - x - 62
    l1 = "DEPARTMENT OF AGRICULTURE"
    l2 = "Regional Field Office – Cordillera Administrative Region"
    l3 = "Adaptation and Mitigation Initiative in Agriculture (AMIA) Program"
    cv.text(tx, 24, l1, "bold", _fit(cv, l1, "bold", 30, tw, 18), GREEN_DARK)
    cv.text(tx, 62, l2, "semibold", _fit(cv, l2, "semibold", 24, tw, 16), GREEN)
    cv.text(tx, 94, l3, "bold", _fit(cv, l3, "bold", 22, tw, 14), pages.AMBER)
    y = 136
    tc = payload.get("tc") or {}
    title = "SPECIAL FARM WEATHER OUTLOOK AND ADVISORY"
    sub = f"for Cordillera Administrative Region  ·  as of {tc.get('issued_text') or payload.get('issued', '')}"
    cv.rrect(40, y, W - 80, 104, _hex("#0b6237"), r=16)
    cv.d.text((W / 2 * cv.s, (y + 14) * cv.s), title, font=pages._extrabold(cv, _fit(cv, title, "bold", 40, W - 140, 24)),
              fill=(255, 255, 255), anchor="ma")
    cv.text(W / 2, y + 66, sub, "semibold", _fit(cv, sub, "semibold", 22, W - 140, 14), (214, 240, 222), anchor="ma")
    return y + 104 + 14


def _rain_blocks(payload: dict) -> list[tuple]:
    rain = (payload.get("summary") or {}).get("car_rainfall") or {}
    if not rain:
        return []
    out: list[tuple] = [("head", "HEAVY RAINFALL (PAGASA)")]
    adv = (payload.get("tc") or {}).get("rain_advisory") or {}
    impacts = {r["class"]: r["impact"] for r in adv.get("rows", [])}
    for prov, days in sorted(rain.items()):
        by: dict[str, list[str]] = {}
        for d, c in days:
            by.setdefault(c, []).append(d)
        for c, ds in by.items():
            out.append(("swatch", _hex("#1e88e5" if c == "50–100 mm" else "#3949ab" if c == "100–200 mm" else "#6a1b9a"),
                        f"{prov}: {c}", f"{pages._list([d.lower() if d.lower().startswith('to') else d for d in ds])} – "
                                        "floods and landslides possible."))
    for w in (payload.get("tc") or {}).get("regional_warnings") or []:
        out.append(("para", f"{w['kind']} (PAGASA Northern Luzon): {w['text'][:300]}", "semibold", ORANGE))
    return out


def _rec_blocks(payload: dict, numbered_only: bool = False) -> list[tuple]:
    """The recommendations as blocks: section heads ("NOW – …:", "During the storm:") and numbered steps; the
    situation sentences above the first section are left out (the signal and rain blocks say it)."""
    out: list[tuple] = []
    started = False
    for kind, line in pages._rec_lines(payload.get("texts", {}).get("recommendations") or ""):
        if kind == "head":
            if line.rstrip().endswith(":"):
                started = True
                if not numbered_only:
                    out.append(("sub", line.rstrip(":")))
            continue
        if kind == "num":
            m = re.match(r"^(\d+)[.)]\s*(.*)$", line)
            out.append(("num", int(m.group(1)), m.group(2)) if m else ("bullet", line))
            started = True
        elif started:
            out.append(("bullet", line))
    return out


def _flow(cv, cols: list[tuple[float, float]], y: float, bottom: float, blocks: list[tuple], hi: float, lo: float,
          keep_heads: bool = True) -> float:
    """Newspaper columns: the blocks fill the first column, then the next. Largest font size (hi → lo) at which
    everything fits; a heading never ends a column. Returns the font size used."""
    def place(fs: float, draw: bool) -> bool:
        ci, yy = 0, y
        i = 0
        while i < len(blocks):
            b = blocks[i]
            h = _column(cv, 0, 0, cols[ci][1], [b], fs, draw=False)
            nxt = _column(cv, 0, 0, cols[ci][1], [blocks[i + 1]], fs, draw=False) if keep_heads and b[0] in ("head", "sub") and i + 1 < len(blocks) else 0
            if yy + h + nxt > bottom and yy > y:
                ci += 1
                yy = y
                if ci >= len(cols):
                    return False
                continue
            if draw:
                _column(cv, cols[ci][0], yy, cols[ci][1], [b], fs)
            yy += h
            i += 1
        return True

    fs = hi
    while fs > lo and not place(fs, False):
        fs -= 0.5
    if not place(fs, False):
        log.warning("A4 text does not fit at %.1f units – the end is cut", fs)
    place(fs, True)
    return fs


def _key_items(payload: dict) -> tuple[list, list]:
    """The map key: PAGASA's symbols (first row) and the wind signals of CAR (second row)."""
    from .tc_map import CONE_EDGE, CONE_FILL, STORM_EDGE, STORM_FILL, WINDS_EDGE, WINDS_FILL
    tc = payload.get("tc") or {}
    feats = (tc.get("track_geojson") or {}).get("features", [])
    kinds = {f["properties"]["kind"] for f in feats}
    sym = [("dot", None, None, "Position (category)")]
    if "cone" in kinds:
        sym.append(("box", CONE_FILL, CONE_EDGE, "Forecast cone (approx.)"))
    if tc.get("wind_extent_km"):
        sym.append(("box", WINDS_FILL, WINDS_EDGE, f"Strong winds ({tc['wind_extent_km']:,.0f} km)"))
    if tc.get("storm_force_km"):
        sym.append(("box", STORM_FILL, STORM_EDGE, f"Storm-force winds ({tc['storm_force_km']:,.0f} km)"))
    sym.append(("dash", None, None, "PAR"))
    sig = [("box", c["color"], "#5a5a5a", c["label"].replace("Wind Signal No.", "Signal"))
           for c in payload["layers"][0]["legend"]["classes"]]
    return sym, sig


def _key_row(cv, items: list, x: float, y: float, w: float, fs: float = 18) -> float:
    """One centred row of key items; returns its height."""
    from .tc_map import TRACK
    step = lambda f: sum(cv.width(t, "semibold", f) + f * 2.9 for *_, t in items)  # noqa: E731
    while step(fs) > w and fs > 10:
        fs -= 0.5
    xx = x + (w - step(fs)) / 2
    cy = y + fs * 0.8
    for kind, fill, edge, text in items:
        sw = fs * 1.5
        if kind == "dot":
            cv.d.line([(xx * cv.s, cy * cv.s), ((xx + sw) * cv.s, cy * cv.s)], fill=_hex(TRACK), width=int(2 * cv.s))
            r = fs * 0.45
            cv.d.ellipse([(xx + sw / 2 - r) * cv.s, (cy - r) * cv.s, (xx + sw / 2 + r) * cv.s, (cy + r) * cv.s], fill=_hex(TRACK))
        elif kind == "box":
            base = _hex(fill)
            soft = tuple(int(c + (255 - c) * 0.45) for c in base) if edge != "#5a5a5a" else base
            cv.rrect(xx, cy - fs * 0.45, sw, fs * 0.9, soft, r=3, outline=_hex(edge), width=1.2)
        elif kind == "dash":
            for k in range(3):
                cv.d.line([((xx + k * sw / 3) * cv.s, cy * cv.s), ((xx + k * sw / 3 + sw / 5) * cv.s, cy * cv.s)],
                          fill=(55, 71, 79), width=int(2 * cv.s))
        cv.text(xx + sw + fs * 0.45, cy, text, "semibold", fs, INK, anchor="lm")
        xx += cv.width(text, "semibold", fs) + fs * 2.9
    return fs * 1.6


def _map_block(cv, payload: dict, out_dir: Path, x: float, y: float, w: float, h: float, tag: str,
               units_per_inch: float, fs: float) -> float:
    """The one map – PAGASA's style (track, cone, wind circles, PAR) with CAR by wind signal and its zoomed inset –
    and the two-row key under it. Returns the bottom."""
    sym, sig = _key_items(payload)
    key_h = fs * 1.6 * 2 + 10
    cap = "Track forecast and wind signals in CAR (DOST-PAGASA data)"
    mh = h - key_h
    _panel(cv, track_map(payload, out_dir, w - 16, mh - 48, tag, units_per_inch=units_per_inch, legend=False, inset=True),
           x, y, w, mh, cap)
    yy = y + mh + 6
    yy += _key_row(cv, sym, x, yy, w, fs)
    yy += _key_row(cv, sig, x, yy, w, fs)
    return y + h


def a4_page(payload: dict, out_dir: Path) -> dict:
    cv = _canvas(A4)
    W, H = cv.W, cv.H
    y = _a4_header(cv, payload)
    y = _storm_band(cv, payload, y, big=32)
    # the one map: PAGASA's track elements with CAR by wind signal
    y = _map_block(cv, payload, out_dir, 40, y, W - 80, 640, "a4", 150, 17) + 12
    facts = _facts(payload)
    fw = (W - 80 - 3 * 12) / 4
    for i, (t, b) in enumerate(facts):
        _fact(cv, 40 + i * (fw + 12), y, fw, 92, t, b, size=19)
    y += 92 + 16
    # text in two newspaper columns: signals, rain, outlook, then what to do (now / during / after) and crop advice
    bottom = H - 112
    hp = (payload.get("tc") or {}).get("highest_possible")
    crops = _crop_blocks(payload)
    blocks = (_signal_blocks(payload) + ([("para", hp, "italic", MUTED)] if hp else []) + _rain_blocks(payload)
              + [("head", "WHAT FARMERS SHOULD DO")] + _rec_blocks(payload)
              + ([("gap", 6), ("head", "CROP AND LIVESTOCK ADVICE")] + crops if crops else []))
    gap = 28
    cw = (W - 80 - gap) / 2
    cv.rect(40 + cw + gap / 2 - 1, y, 2, bottom - y, (214, 222, 216))
    fs = _flow(cv, [(40, cw), (40 + cw + gap, cw)], y, bottom, blocks, hi=22, lo=14)
    log.info("A4 text at %.1f units", fs)
    disc = payload.get("texts", {}).get("disclaimer") or ""
    if disc:
        cv.text(40, H - 104, disc, "italic", _fit(cv, disc, "italic", 15, W - 80, 10), MUTED)
    _footer(cv, payload)
    png, jpg = _save(cv, out_dir / "tc_advisory_a4.png", out_dir / "tc_advisory_a4_preview.jpg")
    pdf = out_dir / "tc_advisory_a4.pdf"
    Image.open(png).convert("RGB").save(pdf, "PDF", resolution=A4_DPI, title=payload.get("texts", {}).get("title"),
                                        author="DA-RFO-CAR AMIA", subject=payload["period"]["label"])
    return {"layer": "a4", "label": "Print format (A4)", "pdf": pdf.name, "poster": png.name, "poster_web": jpg.name,
            "alt": f"Special Farm Weather Outlook and Advisory for CAR, {payload['period']['label']}: one A4 page with "
                   "the track forecast, the CAR wind signals, the rainfall outlook and the farm advisory"}


# ------------------------------------------------------------ Facebook posts ---

def _fb_header(cv, payload: dict, kicker: str) -> float:
    """Compact letterhead for the posts: logos, DA-RFO-CAR · AMIA, the product name and the kicker."""
    from .envi import config as envi_config
    W = cv.W
    x = 40
    for name, w in (("Bagong_Pilipinas_logo.png", 70), ("DA CAR LOGO no background.png", 76), ("AMIA_Logo.png", 66)):
        p = envi_config.LOGO_DIR / name
        if p.exists():
            _, _, lw, _ = cv.paste(p, x, 22, w, 70, align="left")
            x += lw + 10
    tx, tw = x + 16, W - x - 56
    l1 = "DA-RFO Cordillera Administrative Region · AMIA Program"
    cv.text(tx, 24, l1, "semibold", _fit(cv, l1, "semibold", 20, tw, 13), GREEN)
    l2 = "SPECIAL FARM WEATHER OUTLOOK AND ADVISORY"
    cv.d.text((tx * cv.s, 52 * cv.s), l2, font=pages._extrabold(cv, _fit(cv, l2, "bold", 28, tw, 16)), fill=_hex("#0b6237"))
    cv.text(tx, 90, kicker, "semibold", _fit(cv, kicker, "semibold", 19, tw, 12), pages.AMBER)
    return 120


def advisory_post(payload: dict, out_dir: Path) -> dict:
    """The first post: the track map with CAR's wind signals (what people see first), its key, and the summary."""
    cv = _canvas(FACEBOOK)
    W, H = cv.W, cv.H
    tc = payload.get("tc") or {}
    y = _fb_header(cv, payload, f"for CAR  ·  as of {tc.get('issued_text') or payload.get('issued', '')}")
    y = _storm_strip(cv, payload, y)
    # the one map: PAGASA's track elements with CAR by wind signal
    y = _map_block(cv, payload, out_dir, 40, y, W - 80, 690, "facebook", 120, 19) + 12
    # summary
    _summary_card(cv, payload, 40, y, W - 80, H - 96)
    _footer(cv, payload)
    png, jpg = _save(cv, *pages._files(payload, out_dir, "advisory", "facebook"))
    return {"layer": "advisory", "label": "Advisory", "png": png, "jpg": jpg,
            "alt": f"Special Farm Weather Outlook and Advisory for CAR: {_storm(payload)} – track forecast (DOST-PAGASA) "
                   "with the CAR municipalities under wind signals, and the summary"}


def _sections(payload: dict) -> list[tuple[str, list[tuple]]]:
    """The recommendations split at their section heads: [(head, blocks)]."""
    out: list[tuple[str, list[tuple]]] = []
    for b in _rec_blocks(payload):
        if b[0] == "sub":
            out.append((b[1], []))
        elif out:
            out[-1][1].append(b)
    return out


def action_posts(payload: dict, out_dir: Path) -> list[dict]:
    """What farmers should do: the first section ("now" / "within 24 hours") on one post, the rest (during and after
    the storm) on the next – big type for phones."""
    secs = _sections(payload)
    if not secs:
        return []
    groups = [secs[:1], secs[1:]] if len(secs) > 1 else [secs]
    out = []
    for k, group in enumerate(groups, start=1):
        cv = _canvas(FACEBOOK)
        W, H = cv.W, cv.H
        y = _fb_header(cv, payload, f"What farmers should do  ·  {_storm(payload)}")
        blocks: list[tuple] = []
        for head, bl in group:
            blocks += [("sub", head)] + bl + [("gap", 14)]
        cv.text(48, y + 6, "What to do" if k == 1 else "During and after the storm", "bold", 40, INK)
        fs = _flow(cv, [(48, W - 96)], y + 70, H - 104, blocks[:-1], hi=36, lo=17)
        log.info("Facebook actions post %d at %.1f units", k, fs)
        _footer(cv, payload)
        pid = "recommendations" if k == 1 else f"recommendations_{k}"
        png, jpg = _save(cv, *pages._files(payload, out_dir, pid, "facebook"))
        out.append({"layer": pid, "label": "What to do" if k == 1 else "During and after the storm", "png": png, "jpg": jpg,
                    "alt": f"What farmers in CAR should do – {', '.join(h for h, _ in group)}"})
    return out


def _crop_points(text: str) -> list[str]:
    """Advice text → short points (one per sentence or clause)."""
    out = []
    for part in re.split(r"(?<=[.;])\s+", text.strip()):
        part = part.strip().rstrip(".;").strip()
        if part:
            out.append(part[0].upper() + part[1:])
    return out


def crops_post(payload: dict, out_dir: Path) -> dict | None:
    """Rice, corn, high-value crops and livestock: one card each (2 × 2), the points as short lines."""
    t = payload.get("texts", {})
    cards = [(lab, _hex(col), _crop_points(t[k])) for k, lab, col in pages._ADVICE if t.get(k)]
    if not cards:
        return None
    cv = _canvas(FACEBOOK)
    W, H = cv.W, cv.H
    y = _fb_header(cv, payload, f"Crop and livestock advisory  ·  {_storm(payload)}")
    cv.text(48, y + 6, "Crop and livestock advice", "bold", 40, INK)
    y += 70
    cols = 2 if len(cards) > 1 else 1
    rows = (len(cards) + cols - 1) // cols
    gap = 16
    cw = (W - 80 - gap * (cols - 1)) / cols
    ch = (H - 96 - y - gap * (rows - 1)) / rows
    pad = 24

    def height(fs, points):
        return sum(len(cv.wrap(p, "regular", fs, cw - 2 * pad - fs)) * fs * 1.3 + fs * 0.55 for p in points)

    fs = 30
    while fs > 14 and any(height(fs, pts) > ch - 2 * pad - 52 for _, _, pts in cards):
        fs -= 0.5
    for i, (lab, col, pts) in enumerate(cards):
        x0 = 40 + (i % cols) * (cw + gap)
        y0 = y + (i // cols) * (ch + gap)
        cv.rrect(x0, y0, cw, ch, CARD, r=18)
        cv.rrect(x0 + pad, y0, cw - 2 * pad, 6, col, r=3)
        r = 9
        cv.d.ellipse([(x0 + pad) * cv.s, (y0 + pad + 20 - r) * cv.s, (x0 + pad + 2 * r) * cv.s, (y0 + pad + 20 + r) * cv.s],
                     fill=col)
        cv.text(x0 + pad + 2 * r + 12, y0 + pad + 20, lab, "bold", _fit(cv, lab, "bold", 30, cw - 2 * pad - 30, 16), INK,
                anchor="lm")
        yy = y0 + pad + 56
        for ptxt in pts:
            cv.rect(x0 + pad, yy + fs * 0.28, 4, fs * 0.8, col)
            for line in cv.wrap(ptxt, "regular", fs, cw - 2 * pad - fs):
                cv.text(x0 + pad + fs, yy, line, "regular", fs, INK)
                yy += fs * 1.3
            yy += fs * 0.55
    log.info("Facebook crops post at %.1f units", fs)
    _footer(cv, payload)
    png, jpg = _save(cv, *pages._files(payload, out_dir, "crops", "facebook"))
    return {"layer": "crops", "label": "Crop and livestock advice", "png": png, "jpg": jpg,
            "alt": "What to do for rice, corn, high-value crops and livestock in CAR – " + _storm(payload)}


def _facebook_size(png: Path) -> None:
    """Facebook shows 1080 px wide (2160 px for sharp phones); a smaller file uploads faster."""
    with Image.open(png) as im:
        im = im.convert("RGB").resize(FACEBOOK_PX, Image.LANCZOS)
    im.save(png, optimize=True)


def export(payload: dict, out_dir: Path, progress) -> list[dict]:
    """The one-page A4 (PDF + PNG), then the Facebook posts: the advisory (track first), what to do, crop advice."""
    progress("pages", "running", "Making the A4 page (PDF)")
    out = [a4_page(payload, out_dir)]
    progress("pages", "running", "Making the Facebook posts")
    crops = crops_post(payload, out_dir)
    for p in [advisory_post(payload, out_dir), *action_posts(payload, out_dir), *([crops] if crops else [])]:
        _facebook_size(p["png"])
        out.append({"layer": p["layer"], "label": p["label"], "alt": p["alt"], "social": p["png"].name,
                    "social_web": p["jpg"].name})
    return out


__all__ = ["export", "a4_page", "advisory_post", "action_posts", "crops_post", "summary_rows", "FACEBOOK", "A4"]
