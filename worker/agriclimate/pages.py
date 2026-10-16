"""Report pages around the maps: a title page (first), and a summary page and an agricultural recommendations page
(last), so photo mode reads as one report.

  * rainfall / drought: square pages like the print maps (1200 × 1200 design units, saved at 3600 px);
  * ENVI: each page twice, landscape like the presentation (1920 × 1080 → 5760 × 3240) and portrait like the A4
    poster (1240 × 1754 → 3720 × 5262), so the photo-mode switch between the two formats covers them too.

Title page (DA-RFO-CAR AMIA cover): logos and program header, the product title with the "for Cordillera
Administrative Region" banner, the period, the map legend, QR codes to the ACAP website and the interactive maps,
and the weather source (DOST-PAGASA). Summary: the current condition and the expected forecast in words, then the
key figures. Recommendations: crop advice (rice, corn, high-value crops) and the agricultural advisory.

Drawn with Pillow (the ENVI presentation's Canvas and fonts).
"""
from __future__ import annotations

import gc
import io
import os
import re
from pathlib import Path

import pandas as pd
from PIL import Image, ImageFont

from . import reference
from .envi import config as envi_config
from .envi.presentation import GREEN, GREEN_DARK, INK, LIGHT, MUTED, PANEL_TEXT, Canvas, _hex
from .products import common

SCALE = 3.0
SQUARE = (1200, 1200)
LANDSCAPE = (1920, 1080)
PORTRAIT = (1240, 1754)
PRODUCT_NAMES = {"rainfall_dekad": "10-day rainfall forecast", "rainfall_seasonal": "Seasonal rainfall forecast",
                 "drought": "Drought forecast", "envi": "El Niño Vulnerability Index (ENVI)"}
COVER_TITLES = {"rainfall_dekad": "10-DAY RAINFALL FORECAST", "rainfall_seasonal": "SEASONAL RAINFALL OUTLOOK",
                "drought": "DROUGHT FORECAST", "envi": "EL NIÑO VULNERABILITY INDEX"}
ACAP_URL = os.environ.get("ACAP_URL", "https://acap-car.github.io")
PORTAL_URL = os.environ.get("PORTAL_URL", "https://amia-car-maps.vercel.app")
AMBER = (232, 163, 23)
RISK = ("High", "Very High")


def _canvas(size: tuple[int, int], measure: bool = False) -> Canvas:
    """A page; ``measure=True`` gives a tiny canvas for laying out only (same text metrics, nothing kept)."""
    cv = Canvas(8, 8, SCALE) if measure else Canvas(int(size[0] * SCALE), int(size[1] * SCALE), SCALE)
    cv.W, cv.H = size
    return cv


def _extrabold(cv: Canvas, size: float) -> ImageFont.FreeTypeFont:
    p = envi_config.FONT_DIR / "Montserrat-ExtraBold.ttf"
    return ImageFont.truetype(str(p), int(round(size * cv.s))) if p.exists() else cv.f("bold", size)


def _date(iso: str) -> str:
    """'2026-10-05' → 'October 5, 2026'."""
    try:
        t = pd.Timestamp(iso)
    except (ValueError, TypeError):
        return iso or ""
    return iso or "" if pd.isna(t) else f"{t.strftime('%B')} {t.day}, {t.year}"


def _month(ym: str) -> str:
    return pd.Period(ym, "M").strftime("%B %Y")


def _name(key: str) -> str:
    return f"{reference.area_label(key)}, {reference.province_display(reference.province_of(key))}"


def _short(key: str) -> str:
    return reference.area_label(key)


def _list(items: list[str], n: int = 6) -> str:
    items = list(items)
    more = len(items) - n
    items = items[:n]
    s = items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""
    return s + (f" and {more} more" if more > 0 else "")


def _fit(cv: Canvas, text: str, style: str, size: float, maxw: float, low: float = 10) -> float:
    while cv.width(text, style, size) > maxw and size > low:
        size -= 0.5
    return size


def _header(cv: Canvas, payload: dict, kicker: str) -> float:
    """Logos, product title and period (summary / recommendations pages); returns the y below it."""
    W = cv.W
    logos = envi_config.LOGO_DIR
    da = logos / "DA CAR LOGO no background.png"
    if da.exists():
        cv.paste(da, 40, 28, 100, 88, align="left")
    x = W - 40
    for name in ("AMIA_Logo.png", "Bagong_Pilipinas_logo.png"):
        p = logos / name
        if p.exists():
            px, _, _, _ = cv.paste(p, x - 84, 34, 84, 76)
            x = px - 14
    t = payload.get("texts", {})
    cv.text(W / 2, 48, kicker.upper(), "bold", _fit(cv, kicker.upper(), "bold", 26, W - 400, 18), AMBER, anchor="mm")
    title = t.get("title") or payload.get("title", "")
    cv.text(W / 2, 92, title, "bold", _fit(cv, title, "bold", 40, W - 400, 22), GREEN_DARK, anchor="mm")
    sub = f"{payload['period']['label']}  ·  as of {_date(payload.get('issued', ''))}"
    cv.text(W / 2, 136, sub, "semibold", _fit(cv, sub, "semibold", 26, W - 400, 18), MUTED, anchor="mm")
    cv.d.line([(40 * cv.s, 166 * cv.s), ((W - 40) * cv.s, 166 * cv.s)], fill=GREEN, width=int(5 * cv.s))
    return 190


def _source_line(payload: dict) -> str:
    return ("Drought forecast: DOST-PAGASA · Damage and standing crops: DA-RFO-CAR" if payload["type"] == "envi"
            else "Weather source: DOST-PAGASA")


def _footer(cv: Canvas, payload: dict, page: str):
    W, H = cv.W, cv.H
    t = payload.get("texts", {})
    y = H - 80
    cv.d.line([(40 * cv.s, y * cv.s), ((W - 40) * cv.s, y * cv.s)], fill=(205, 212, 206), width=max(1, int(2 * cv.s)))
    src = f"Sources: {t.get('sources') or payload.get('source', '')}"
    lab_w = max(cv.width(page, "bold", 22), cv.width("DA-RFO-CAR · AMIA", "regular", 18)) + 40
    for i, l in enumerate(cv.wrap(src, "italic", 18, W - 80 - lab_w)[:2]):
        cv.text(40, y + 12 + i * 24, l, "italic", 18, MUTED)
    cv.text(W - 40, y + 12, page, "bold", 22, GREEN_DARK, anchor="ra")
    cv.text(W - 40, y + 42, "DA-RFO-CAR · AMIA", "regular", 18, MUTED, anchor="ra")


def _table(cv: Canvas, x, y, cols: list[tuple[str, float, str]], rows: list[list], size=15, row_h=None,
           fills: list[list] | None = None) -> float:
    """Simple table. cols: (title, width, align 'l'|'r'|'c'); rows of cell texts; optional cell fill colours."""
    row_h = row_h or size * 1.75
    tw = sum(c[1] for c in cols)
    cv.rect(x, y, tw, row_h, GREEN)
    cx = x
    for title, w, al in cols:
        tx = cx + 8 if al == "l" else cx + w - 8 if al == "r" else cx + w / 2
        cv.text(tx, y + row_h / 2, title, "semibold", size - 1, PANEL_TEXT, anchor={"l": "lm", "r": "rm", "c": "mm"}[al])
        cx += w
    y += row_h
    for i, r in enumerate(rows):
        if i % 2 == 0:
            cv.rect(x, y, tw, row_h, LIGHT)
        cx = x
        for j, (cell, (_, w, al)) in enumerate(zip(r, cols)):
            fill = fills[i][j] if fills and fills[i][j] else None
            if fill:
                cv.rect(cx + 2, y + 2, w - 4, row_h - 4, _hex(fill))
            tx = cx + 8 if al == "l" else cx + w - 8 if al == "r" else cx + w / 2
            cv.text(tx, y + row_h / 2, str(cell), "regular", size, INK, anchor={"l": "lm", "r": "rm", "c": "mm"}[al])
            cx += w
        y += row_h
    return y


def _card(cv: Canvas, x, y, w, h, big: str, small: str, color=GREEN_DARK):
    cv.rrect(x, y, w, h, LIGHT, r=12)
    cv.text(x + 18, y + 14, big, "bold", _fit(cv, big, "bold", 28, w - 36, 16), color)
    cv.para(x + 18, y + 52, small, w - 36, size=14, fill=MUTED, lh=1.3)


def _save(cv: Canvas, out: Path, preview: Path, preview_px: int = 3000) -> tuple[Path, Path]:
    cv.img.save(out, dpi=(300, 300))
    im = cv.img.copy()
    im.thumbnail((preview_px, preview_px), Image.LANCZOS)
    im.save(preview, "JPEG", quality=92, optimize=True, progressive=True)
    gc.collect()
    return out, preview


def _files(payload: dict, out_dir: Path, page: str, suffix: str) -> tuple[Path, Path]:
    stem = f"{payload['type']}_page_{page}{'_' + suffix if suffix else ''}"
    return out_dir / f"{stem}.png", out_dir / f"{stem}_preview.jpg"


# --------------------------------------------------------------- title page ---

def _qr(url: str) -> Image.Image:
    import segno
    buf = io.BytesIO()
    segno.make(url, error="m").save(buf, kind="png", scale=12, border=1)
    buf.seek(0)
    return Image.open(buf).convert("RGB")


def _cover_band(cv: Canvas) -> float:
    """Logos and the DA-RFO-CAR AMIA Program header (as on the DA-RFO-CAR covers); returns its bottom."""
    W = cv.W
    x = 40
    for name, w in (("Bagong_Pilipinas_logo.png", 92), ("DA CAR LOGO no background.png", 104), ("AMIA_Logo.png", 84)):
        p = envi_config.LOGO_DIR / name
        if p.exists():
            _, _, lw, _ = cv.paste(p, x, 26, w, 84, align="left")
            x += lw + 14
    cv.d.line([((x + 4) * cv.s, 30 * cv.s), ((x + 4) * cv.s, 108 * cv.s)], fill=(150, 150, 150), width=int(2 * cv.s))
    tx, tw = x + 22, W - x - 62
    l1 = "DEPARTMENT OF AGRICULTURE - RFO Cordillera Administrative Region"
    l2 = "Adaptation and Mitigation Initiative in Agriculture Program"
    l3 = "Building farming and fishing communities, livelihoods, and enterprises resilient to economic and climate shocks."
    cv.text(tx, 26, l1, "semibold", _fit(cv, l1, "semibold", 24, tw), GREEN)
    cv.text(tx, 58, l2, "bold", _fit(cv, l2, "bold", 30, tw), AMBER)
    cv.text(tx, 96, l3, "italic", _fit(cv, l3, "italic", 20, tw), INK)
    return 132


def _legend_items(payload: dict) -> tuple[dict, list]:
    lyr = next((l for l in payload["layers"] if l["id"] == "envi"), payload["layers"][0])
    return lyr["legend"], lyr["legend"]["classes"]


def _legend_height(payload: dict, max_h: float, row: float = 52) -> float:
    return min(max_h, 100 + row * len(_legend_items(payload)[1]) + 12)


def _legend_panel(cv: Canvas, payload: dict, x: float, y: float, w: float, h: float, max_row: float = 52):
    lg, items = _legend_items(payload)
    title = (payload.get("texts", {}).get("legend_title") or lg.get("title") or "").rstrip(":")
    title = re.sub(r"(?i)^legend\s*", "", title).strip()               # "LEGEND in millimeters (mm)" → "in millimeters (mm)"
    if title.startswith("(") and title.endswith(")") and title.count("(") == 1:
        title = title[1:-1]
    if title.lower().startswith("in "):
        title = ("Rainfall " if lg.get("unit") == "mm" else "") + title
    cv.rrect(x, y, w, h, LIGHT, r=14)
    cv.text(x + 22, y + 16, "LEGEND", "bold", 26, GREEN_DARK)
    if title:
        cv.text(x + 22, y + 52, title, "semibold", _fit(cv, title, "semibold", 22, w - 44), MUTED)
    row = min(max_row, (h - 100) / max(len(items), 1))
    fs = min(30, row * 0.56)
    for i, c in enumerate(items):
        yy = y + 92 + i * row
        cv.rect(x + 22, yy, 50, row * 0.72, _hex(c["color"]), outline=(90, 90, 90))
        unit = " mm" if lg.get("unit") == "mm" and lg.get("kind") == "graduated" else ""
        label = c["label"] + unit
        if payload["type"] == "envi" and c.get("lo") is not None and c.get("hi") is not None:
            label = f"{c['lo']:.2f}–{c['hi']:.2f}  {c['label']}"
        text = f"{label}  –  {c['desc']}" if c.get("desc") else label
        cv.text(x + 86, yy + row * 0.36, text, "regular", _fit(cv, text, "regular", fs, w - 110), INK, anchor="lm")


def _qr_block(cv: Canvas, x: float, y: float, w: float, size: float, caption: str, url: str):
    cv.text(x + w / 2, y, caption, "italic", _fit(cv, caption, "italic", 24, w - 10), INK, anchor="ma")
    shown = url.replace("https://", "").replace("http://", "").rstrip("/")
    fs = _fit(cv, shown, "bold", 30, w - 10)
    cv.text(x + w / 2, y + 32, shown, "bold", fs, AMBER, anchor="ma")
    tw = cv.width(shown, "bold", fs)
    cv.d.line([((x + w / 2 - tw / 2) * cv.s, (y + 34 + fs * 1.15) * cv.s), ((x + w / 2 + tw / 2) * cv.s,
               (y + 34 + fs * 1.15) * cv.s)], fill=AMBER, width=int(3 * cv.s))
    cv.paste(_qr(url), x + (w - size) / 2, y + 84, size, size)


def title_page(payload: dict, out_dir: Path, size=SQUARE, suffix: str = "") -> dict:
    """Cover page: program header, product title, period, legend, QR codes and the weather source."""
    cv = _canvas(size)
    W, H = cv.W, cv.H
    y = _cover_band(cv) + (40 if H < 1300 else 90)
    title = COVER_TITLES.get(payload["type"], payload.get("title", "").upper())
    fs = 96
    while cv.d.textlength(title, font=_extrabold(cv, fs)) / cv.s > W - 160 and fs > 40:
        fs -= 2
    cv.d.text((W / 2 * cv.s, y * cv.s), title, font=_extrabold(cv, fs), fill=_hex("#0b6237"), anchor="ma")
    y += fs * 1.2
    # "for Cordillera Administrative Region" banner with the three dots
    sub = "for Cordillera Administrative Region"
    pw = min(W - 200, max(560, cv.width(sub, "bold", 30) + 200))
    px = (W - pw) / 2
    ph = 50
    cv.rrect(px + 40, y, pw - 40, ph, _hex("#108a08"), r=ph / 2)
    for i, col in enumerate(("#0aa50a", "#1f7a1f", "#0b6237")):
        cx = px + 24 + i * 30
        cv.d.ellipse([(cx - 25) * cv.s, y * cv.s, (cx + 25) * cv.s, (y + ph) * cv.s], fill=_hex(col))
    cv.text(px + 40 + (pw - 40) / 2 + 30, y + ph / 2, sub, "bold", 28, PANEL_TEXT, anchor="mm")
    y += ph + (40 if H < 1300 else 70)
    period = payload["period"]["label"]
    cv.text(W / 2, y, period, "bold", _fit(cv, period, "bold", 64, W - 160, 30), INK, anchor="ma")
    y += 84
    issued = f"Issued (as of) {_date(payload.get('issued', ''))}"
    if payload.get("valid_text"):
        issued = f"{payload['valid_text']}  ·  {issued}"
    cv.text(W / 2, y, issued, "semibold", _fit(cv, issued, "semibold", 28, W - 80, 18), GREEN_DARK, anchor="ma")
    y += 56

    # legend + QR codes, centred in the space left above the source line
    bottom = H - 140
    avail = bottom - y
    links = (("Visit the ACAP website:", ACAP_URL), ("View the interactive maps:", PORTAL_URL))
    if H > W * 1.2:      # portrait (A4): a full-width legend, the two QR codes side by side below it
        lh = _legend_height(payload, avail * 0.45, 52)
        half = (W - 80 - 40) / 2
        qs = min(360, half - 60, avail - lh - 150)
        block = lh + 50 + qs + 80
        top = y + max(0, (avail - block) / 2)
        _legend_panel(cv, payload, 40, top, W - 80, lh, 52)
        for i, (cap, url) in enumerate(links):
            _qr_block(cv, 40 + i * (half + 40), top + lh + 50, half, qs, cap, url)
    else:                # square / landscape: legend left, the two QR codes side by side on the right
        lw = W * (0.40 if W > H else 0.46)
        lh = _legend_height(payload, avail)
        qx, qw = 40 + lw + 30, W - 80 - lw - 30
        half = (qw - 20) / 2
        qs = min(half - 30, avail - 90, 300)
        qh = qs + 80
        top = y + max(0, (avail - max(lh, qh)) / 2)
        _legend_panel(cv, payload, 40, top + (max(lh, qh) - lh) / 2, lw, lh)
        for i, (cap, url) in enumerate(links):
            _qr_block(cv, qx + i * (half + 20), top + (max(lh, qh) - qh) / 2, half, qs, cap, url)
    src = _source_line(payload)
    cv.text(W / 2, H - 112, src, "bold", _fit(cv, src, "bold", 30, W - 80), GREEN_DARK, anchor="mm")
    _footer(cv, payload, "Title page")
    png, jpg = _save(cv, *_files(payload, out_dir, "cover", suffix))
    kind = PRODUCT_NAMES.get(payload["type"], payload["type"])
    return {"layer": "cover", "label": "Title page", "png": png, "jpg": jpg,
            "alt": f"{kind}, {payload['period']['label']}: title page with the legend, QR codes and sources"}


# -------------------------------------------------------- summary: in words ---

def _values(layer: dict, field: str = "value") -> pd.Series:
    return pd.Series({k: v.get(field) for k, v in layer["values"].items() if isinstance(v.get(field), (int, float))},
                     dtype=float)


def _rain_text(payload: dict) -> tuple[list[str], list[str]]:
    dekad = payload["type"] == "rainfall_dekad"
    series = [l for l in payload["layers"] if l["id"].startswith(("d_", "m_"))]
    total = _values(common.total_layer(payload))
    unit_word = "day" if dekad else "month"
    cur, exp = [], []
    if series:
        f = series[0]
        v = _values(f)
        if not v.empty:
            light = int((v < (5 if dekad else 50)).sum())
            cur.append(f"{f['label']} (first {unit_word} of the forecast): CAR average {v.mean():,.0f} mm, heaviest in "
                       f"{_name(v.idxmax())} ({v.max():,.0f} mm).")
            cur.append(f"{light} of {len(v)} municipalities get less than {5 if dekad else 50} mm"
                       f"{' (no rain to very light rain)' if dekad else ' (minimal rainfall)'}.")
    if not total.empty:
        what = "10-day total" if dekad else "season total"
        exp.append(f"{what.capitalize()}: {total.min():,.0f}–{total.max():,.0f} mm, CAR average {total.mean():,.0f} mm.")
    means = [(l, _values(l)) for l in series]
    means = [(l, v) for l, v in means if not v.empty]
    if len(means) > 1:
        wet = max(means, key=lambda lv: lv[1].mean())
        dry = min(means, key=lambda lv: lv[1].mean())
        exp.append(f"Wettest {unit_word}: {wet[0]['label']} (CAR average {wet[1].mean():,.0f} mm, up to "
                   f"{wet[1].max():,.0f} mm in {_short(wet[1].idxmax())}); driest: {dry[0]['label']} "
                   f"({dry[1].mean():,.0f} mm).")
        first, last = means[0][1].mean(), means[-1][1].mean()
        if not dekad and abs(last - first) > 0.25 * max(first, 1):
            exp.append(f"Rainfall {'decreases' if last < first else 'increases'} through the season, from "
                       f"{first:,.0f} mm in {means[0][0]['label']} to {last:,.0f} mm in {means[-1][0]['label']}.")
    if not total.empty:
        hi, lo = (150, 25) if dekad else (1200, 400)
        wet = total[total >= hi].sort_values(ascending=False)
        dry = total[total < lo].sort_values()
        if len(wet):
            exp.append(f"Heavy totals (≥ {hi:,} mm) in {len(wet)} municipalities: {_list([_short(k) for k in wet.index])}.")
        if len(dry):
            exp.append(f"Low totals (< {lo:,} mm) in {len(dry)} municipalities: {_list([_short(k) for k in dry.index])}.")
    pct = next((l for l in payload["layers"] if l["id"] == "pct_normal"), None)
    if pct:
        counts = {c["label"]: c.get("count", 0) for c in pct["legend"]["classes"] if c.get("count")}
        if counts:
            exp.append("Season rainfall vs normal: " + "; ".join(f"{v} municipalities {k.lower()}" for k, v in counts.items()) + ".")
    return cur, exp


def _drought_groups(by: dict, month: str) -> list[str]:
    groups: dict[str, list[str]] = {}
    for p, c in (by.get(month) or {}).items():
        groups.setdefault(str(c), []).append(p)
    order = ["Drought", "Dry spell", "Dry condition", "Not affected"]
    return [f"{_list(sorted(ps), 6)}: {c.lower()}" for c, ps in sorted(groups.items(), key=lambda kv: order.index(kv[0]) if kv[0] in order else 9)]


def _current_observed(payload: dict) -> list[str]:
    cur = payload.get("current")
    if not cur or not cur.get("by_province"):
        return []
    groups: dict[str, list[str]] = {}
    for p, c in cur["by_province"].items():
        if c:
            groups.setdefault(str(c).lower(), []).append(p)
    parts = "; ".join(f"{_list(sorted(ps))}: {c}" for c, ps in groups.items())
    src = re.sub(r"\s*\(observed\)", "", cur.get("source") or "PAGASA")
    return [f"Observed in {cur.get('label') or cur.get('month')} ({src}): {parts}."]


def _drought_text(payload: dict) -> tuple[list[str], list[str]]:
    by = payload.get("summary", {}).get("by_month_province") or {}
    months = payload["period"].get("months") or list(by)
    cur = _current_observed(payload)
    if months:
        cur.append(f"Forecast for {_month(months[0])}: " + "; ".join(_drought_groups(by, months[0])) + ".")
    exp = []
    provs = sorted({p for m in months for p in by.get(m, {})})
    onset: dict[tuple, list[str]] = {}
    for p in provs:
        seq = [str(by.get(m, {}).get(p, "")).lower() for m in months]
        first = lambda c: next((_month(m) for m, s in zip(months, seq) if s == c), None)  # noqa: E731
        onset.setdefault((first("dry spell"), first("drought"), sum(s == "drought" for s in seq)), []).append(p)
    for (spell, drought, n), ps in sorted(onset.items(), key=lambda kv: -kv[0][2]):
        bits = ([f"dry spell from {spell}"] if spell else []) + ([f"drought from {drought} ({n} month{'s' if n != 1 else ''})"] if drought else [])
        exp.append(f"{_list(ps)}: {', '.join(bits) if bits else 'no dry spell or drought forecast'}.")
    if months:
        last = months[-1]
        n = sum(1 for p in provs if str(by.get(last, {}).get(p, "")).lower() == "drought")
        exp.append(f"By {_month(last)}: {n} of {len(provs)} provinces under drought.")
    return cur, exp


def _envi_text(payload: dict) -> tuple[list[str], list[str]]:
    layers = [l for l in payload["layers"] if l["id"] == "envi" or l["id"].startswith("m_")]
    season, months = layers[0], layers[1:]

    def risk(l):
        return [k for k, v in l["values"].items() if v.get("class") in RISK]

    cur = _current_observed(payload)
    if months:
        m0 = months[0]
        r0 = risk(m0)
        cur.append(f"{m0['label']} (first month of the outlook): {len(r0)} municipalities High or Very High"
                   + (f" – {_list([_short(k) for k in r0])}." if r0 else "."))
    s_risk = risk(season)
    vh = [k for k, v in season["values"].items() if v.get("class") == "Very High"]
    crops = sum(season["values"][k].get("crops_raw") or 0 for k in s_risk)
    has_lv = any(isinstance(v.get("livestock_raw"), (int, float)) for v in season["values"].values())
    lv = sum(season["values"][k].get("livestock_raw") or 0 for k in s_risk)
    exp = [f"Season outlook: {len(s_risk)} of {len(season['values'])} municipalities High or Very High, holding "
           f"{crops:,.0f} ha of standing crops" + (f" and {lv:,.0f} livestock units (TLU)." if has_lv else ".")]
    if vh:
        exp.append(f"Very High: {_list([_short(k) for k in vh])}.")
    if months:
        peak = max(months, key=lambda l: len(risk(l)))
        exp.append(f"Vulnerability rises from {len(risk(months[0]))} High / Very High municipalities in "
                   f"{months[0]['label']} to {len(risk(peak))} in {peak['label']}, as the drought forecast worsens.")
    top = max(season["values"].items(), key=lambda kv: kv[1].get("envi") or -1)
    if top[1].get("envi") is not None:
        exp.append(f"Most vulnerable: {_name(top[0])} (ENVI {top[1]['envi']:.2f}).")
    return cur, exp


# ------------------------------------------------- phone-first page flow ---
# The pages are viewed as images: on a phone a 1200-unit page is shown ~400 px wide (1 unit ≈ 0.33 px), so text
# below ~28 units cannot be read without zooming. Text starts large and shrinks with the amount of content, but
# never below MIN_FS: what does not fit then continues on another page ("Summary (2/2)").

MAX_FS, MIN_FS = 40, 28
FS_STEPS = (40, 38, 36, 34, 32, 30, 28)
TABLE_FS = 27
FOOT_H = 96          # room kept for the footer


class Flow:
    """Lays blocks out top to bottom and starts a new page when the next one does not fit."""

    def __init__(self, payload: dict, size, kicker: str, fs: float, measure: bool = False):
        self.payload, self.size, self.kicker, self.fs, self.measure = payload, size, kicker, fs, measure
        self.pages: list[Canvas] = []
        self.new_page()

    def new_page(self):
        self.cv = _canvas(self.size, self.measure)
        self.y = self.top = _header(self.cv, self.payload, self.kicker)
        self.pages.append(self.cv)

    @property
    def W(self):
        return self.cv.W

    def room(self) -> float:
        return self.cv.H - FOOT_H - self.y

    def ensure(self, h: float):
        if h > self.room() and self.y > self.top + 1:
            self.new_page()

    def gap(self, h: float):
        self.y += h

    def table_keep(self, n_rows: int, extra: float = 0, size: float = TABLE_FS) -> float:
        """Room a heading reserves so that it moves to the next page together with its table (if that fits a page)."""
        full = (n_rows + 1) * size * 1.75 + 18 + extra
        return full if full <= self.cv.H - FOOT_H - self.top - 120 else size * 1.75 * 4

    # --- blocks ---
    def heading(self, text: str, keep: float = 0):
        hs = self.fs + 8
        self.ensure(hs * 1.5 + keep)
        self.cv.rect(40, self.y + 4, 10, hs * 1.05, GREEN)
        self.cv.text(64, self.y, text, "bold", hs, GREEN_DARK)
        self.y += hs * 1.55

    def bullets(self, lines: list[str]):
        fs = self.fs
        for l in lines or ["No data."]:
            wrapped = self.cv.wrap(l, "regular", fs, self.W - 130)
            lh = fs * 1.36
            if len(wrapped) * lh > self.room() and self.y > self.top + 1:
                # split a long sentence over two pages rather than leaving a big gap
                fit = max(1, int(self.room() // lh))
                if fit < len(wrapped) and fit >= 2:
                    self._bullet(wrapped[:fit], fs, first=True)
                    self.new_page()
                    self._bullet(wrapped[fit:], fs, first=False)
                    continue
                self.new_page()
            self._bullet(wrapped, fs, first=True)

    def _bullet(self, wrapped: list[str], fs: float, first: bool):
        cv = self.cv
        if first:
            r = fs * 0.2
            cv.d.ellipse([(58 - r) * cv.s, (self.y + fs * 0.62 - r) * cv.s, (58 + r) * cv.s,
                          (self.y + fs * 0.62 + r) * cv.s], fill=GREEN)
        for w in wrapped:
            cv.text(80, self.y, w, "regular", fs, INK)
            self.y += fs * 1.36
        self.y += fs * 0.35

    def paragraph(self, text: str, style="regular", color=INK, size=None):
        fs = size or self.fs
        for w in self.cv.wrap(text, style, fs, self.W - 100):
            self.ensure(fs * 1.4)
            self.cv.text(50, self.y, w, style, fs, color)
            self.y += fs * 1.36
        self.y += fs * 0.3

    def cards(self, items: list[tuple[str, str]], color=GREEN_DARK):
        cols = 4 if self.W > 1600 else 2
        cw = (self.W - 80 - (cols - 1) * 20) / cols
        big, small = self.fs + 8, max(MIN_FS - 4, self.fs - 6)
        for i in range(0, len(items), cols):
            row = items[i:i + cols]
            h = max(24 + big * 1.25 + len(self.cv.wrap(s, "regular", small, cw - 40)) * small * 1.3 + 18 for _, s in row)
            self.ensure(h)
            for j, (b, s) in enumerate(row):
                x = 40 + j * (cw + 20)
                self.cv.rrect(x, self.y, cw, h, LIGHT, r=14)
                self.cv.text(x + 20, self.y + 18, b, "bold", _fit(self.cv, b, "bold", big, cw - 40, 20), color)
                self.cv.para(x + 20, self.y + 24 + big * 1.25, s, cw - 40, size=small, fill=MUTED, lh=1.3)
            self.y += h + 18

    def table(self, cols: list[tuple[str, float, str]], rows: list[list], fills: list[list] | None = None,
              size: float = TABLE_FS, row_h: float | None = None):
        """Rows split across pages; the header row is repeated on each page."""
        row_h = row_h or size * 1.75
        scale = (self.W - 80) / sum(c[1] for c in cols)          # stretch the columns to the page width
        cols = [(t, w * scale, a) for t, w, a in cols]
        full = (len(rows) + 1) * row_h + 18
        if full <= self.cv.H - FOOT_H - self.top:                 # fits a page: keep it in one piece
            self.ensure(full)
        i = 0
        while i < len(rows):
            self.ensure(row_h * 3)
            n = max(1, int((self.room() - row_h) // row_h))
            if 0 < len(rows) - (i + n) < 3:                       # never leave one or two rows on their own
                n = max(1, len(rows) - i - 3)
            part = rows[i:i + n]
            pf = fills[i:i + n] if fills else None
            self.y = _table(self.cv, 40, self.y, cols, part, size=size, row_h=row_h, fills=pf) + 18
            i += n
            if i < len(rows):
                self.new_page()

    def advice_card(self, label: str, color: str, text: str):
        fs = self.fs
        lines = self.cv.wrap(text, "regular", fs, self.W - 150)
        h = 22 + (fs + 4) * 1.35 + len(lines) * fs * 1.36 + 20
        self.ensure(h)
        cv = self.cv
        cv.rrect(40, self.y, self.W - 80, h, LIGHT, r=14)
        cv.rect(40, self.y, 12, h, _hex(color))
        cv.text(72, self.y + 18, label, "bold", fs + 4, _hex(color))
        yy = self.y + 22 + (fs + 4) * 1.35
        for l in lines:
            cv.text(72, yy, l, "regular", fs, INK)
            yy += fs * 1.36
        self.y += h + 18


def _flow_pages(payload: dict, size, kicker: str, build) -> list[Canvas]:
    """Largest text (MAX_FS → MIN_FS) with which everything fits one page; at MIN_FS, as many pages as needed."""
    for fs in FS_STEPS:
        f = Flow(payload, size, kicker, fs)
        build(f)
        if len(f.pages) == 1 or fs == FS_STEPS[-1]:
            return f.pages
    return f.pages


def _finish(payload: dict, pages: list[Canvas], out_dir: Path, page_id: str, label: str, suffix: str, alt: str) -> list[dict]:
    out = []
    n = len(pages)
    for i, cv in enumerate(pages, start=1):
        tag = label + (f" ({i}/{n})" if n > 1 else "")
        _footer(cv, payload, tag)
        pid = page_id if i == 1 else f"{page_id}_{i}"
        png, jpg = _save(cv, *_files(payload, out_dir, pid, suffix))
        out.append({"layer": pid, "label": label if i == 1 else f"{label} ({i})", "png": png, "jpg": jpg,
                    "alt": alt + (f" (page {i} of {n})" if n > 1 else "")})
    return out


# ------------------------------------------------- summary: key figures ---

def _rain_figures(f: Flow, payload: dict, level: int = 0):
    """Key figure cards (range, average, highest, lowest of the 10-day / season total); none at level ≥ 1."""
    total = _values(common.total_layer(payload))
    if total.empty or level >= 1:
        return
    dekad = payload["type"] == "rainfall_dekad"
    what = "10-day total" if dekad else "season total"
    f.heading("Key figures", keep=200)
    f.cards([(f"{total.min():,.0f}–{total.max():,.0f} mm", f"range of the {what}"),
             (f"{total.mean():,.0f} mm", f"CAR average {what}"),
             (f"{total.max():,.0f} mm", f"highest: {_name(total.idxmax())}"),
             (f"{total.min():,.0f} mm", f"lowest: {_name(total.idxmin())}")])


_ABBR = {"not affected": "N", "dry condition": "DC", "dry spell": "DS", "drought": "D"}


def _drought_figures(f: Flow, payload: dict, level: int = 0):
    """Province × month table with its key; none at level ≥ 1."""
    by = payload.get("summary", {}).get("by_month_province") or {}
    months = payload["period"].get("months") or list(by)
    if not by or not months or level >= 1:
        return
    legend = payload["layers"][0]["legend"]["classes"]
    color = {c["label"]: c["color"] for c in legend}
    provs = sorted({p for m in months for p in by.get(m, {})})
    short = {"Mountain Province": "Mt. Province"}
    f.heading("Province outlook by month", keep=f.table_keep(len(provs), extra=f.fs * 1.7))
    f.paragraph("N = not affected · DC = dry condition · DS = dry spell · D = drought", "regular", MUTED,
                max(MIN_FS - 4, f.fs - 6))                 # the key stays with its table (above it)
    cols = [("Province", 270, "l")] + [(pd.Period(m, "M").strftime("%b"), 140, "c") for m in months]
    rows = [[short.get(p, p)] + [_ABBR.get(str(by.get(m, {}).get(p, "")).lower(), "–") for m in months] for p in provs]
    fills = [[None] + [color.get(by.get(m, {}).get(p, ""), None) for m in months] for p in provs]
    f.table(cols, rows, fills=fills)


def _envi_figures(f: Flow, payload: dict, level: int = 0):
    """Municipalities per class (season and months) and the top 10; level 1: without the top 10; level ≥ 2: none."""
    if level >= 2:
        return
    layers = [l for l in payload["layers"] if l["id"] == "envi" or l["id"].startswith("m_")]
    season = layers[0]
    classes = season["legend"]["classes"]
    color = {c["label"]: c["color"] for c in classes}
    abbr = {"Very Low": "VL", "Low": "L", "Moderate": "M", "High": "H", "Very High": "VH"}
    f.heading("Municipalities per class", keep=f.table_keep(len(layers), extra=f.fs * 1.7))
    f.paragraph("VL = very low · L = low · M = moderate · H = high · VH = very high", "regular", MUTED,
                max(MIN_FS - 4, f.fs - 6))
    cols = [("Period", 260, "l")] + [(abbr.get(c["label"], c["label"]), 105, "c") for c in classes] + [("Crops at risk", 230, "r")]
    rows, fills = [], []
    for l in layers:
        vals = [v for v in l["values"].values() if isinstance(v.get("envi"), (int, float))]
        counts = {c["label"]: sum(1 for v in vals if v["class"] == c["label"]) for c in classes}
        crops = sum(v.get("crops_raw") or 0 for v in vals if v["class"] in RISK)
        name = "Season" if l["id"] == "envi" else pd.Period(l["id"][2:], "M").strftime("%b %Y")
        rows.append([name] + [counts[c["label"]] for c in classes] + [f"{crops:,.0f} ha"])
        fills.append([None] + [color[c["label"]] if counts[c["label"]] else None for c in classes] + [None])
    f.table(cols, rows, fills=fills)
    if level >= 1:
        return
    top = sorted(((k, v) for k, v in season["values"].items() if isinstance(v.get("envi"), (int, float))),
                 key=lambda kv: -kv[1]["envi"])[:10]
    f.heading("Top 10 most vulnerable (season)", keep=f.table_keep(len(top)))
    f.table([("#", 60, "c"), ("Municipality", 520, "l"), ("ENVI", 140, "r"), ("Class", 200, "c")],
            [[i + 1, _name(k), f"{v['envi']:.2f}", v["class"]] for i, (k, v) in enumerate(top)],
            fills=[[None, None, None, color.get(v["class"])] for _, v in top])


SUMMARY_LEVELS = {"envi": 3, "drought": 2}       # figure detail levels (0 = all); rainfall: 2


def summary_pages(payload: dict, out_dir: Path, size=SQUARE, suffix: str = "") -> list[dict]:
    """Current condition and expected forecast in words, then the key figures – always ONE page.

    Tried in order (measured on a tiny canvas first, drawn once): all figures at phone-readable text (40 → 28),
    then with fewer figures (e.g. no ENVI top 10, then none) at 40 → 28, then smaller text (26 → 20)."""
    text = {"drought": _drought_text, "envi": _envi_text}.get(payload["type"], _rain_text)
    figures = {"drought": _drought_figures, "envi": _envi_figures}.get(payload["type"], _rain_figures)
    cur, exp = text(payload)

    def build(level: int):
        def run(f: Flow):
            f.heading("Current condition")
            f.bullets(cur)
            f.gap(10)
            f.heading("Expected forecast")
            f.bullets(exp)
            f.gap(10)
            figures(f, payload, level)
        return run

    levels = range(SUMMARY_LEVELS.get(payload["type"], 2))
    plan = [(lv, fs) for lv in levels for fs in FS_STEPS] + [(lv, fs) for lv in levels for fs in (26, 24, 22, 20)]
    level, fs = plan[-1]
    for lv, size_ in plan:
        m = Flow(payload, size, "Summary", size_, measure=True)
        build(lv)(m)
        if len(m.pages) == 1:
            level, fs = lv, size_
            break
    f = Flow(payload, size, "Summary", fs)
    build(level)(f)
    pages = f.pages[:1]                                    # never more than one summary page
    return _finish(payload, pages, out_dir, "summary", "Summary", suffix,
                   f"{PRODUCT_NAMES.get(payload['type'], '')}, {payload['period']['label']}: current condition, "
                   "expected forecast and key figures")


# -------------------------------------------- agricultural recommendations ---

_ADVICE = [("advice_rice", "Rice", "#2e7d32"), ("advice_corn", "Corn", "#e0a100"), ("advice_hvc", "High-value crops", "#7b3fa0"),
           ("advice_livestock", "Livestock & poultry", "#8d5524")]


def _rec_lines(text: str) -> list[tuple[str, str]]:
    """[(kind, text)] with kind head | bullet | num."""
    out = []
    for l in (text or "").replace("\r", "").split("\n"):
        l = l.strip()
        if not l:
            continue
        if re.match(r"^\d+[.)]", l):
            out.append(("num", l))
        elif re.match(r"^[-•*]", l):
            out.append(("bullet", re.sub(r"^[-•*]\s*", "", l)))
        else:
            out.append(("head", l))
    return out


def recommendations_pages(payload: dict, out_dir: Path, size=SQUARE, suffix: str = "") -> list[dict]:
    """Agricultural recommendations: crop advice first (rice, corn, high-value crops), then the advisory."""
    t = payload.get("texts", {})
    advice = [(lab, col, t.get(k)) for k, lab, col in _ADVICE if t.get(k)]
    lines = _rec_lines(t.get("recommendations", ""))

    def build(f: Flow):
        if advice:
            f.heading("Crop advice", keep=200)
            for lab, col, txt in advice:
                f.advice_card(lab, col, txt)
        if lines:
            f.heading("Agricultural advisory" if advice else "Recommended actions", keep=f.fs * 3)
            for kind, line in lines:
                if kind == "head":
                    f.ensure(f.fs * 3.2)
                    f.paragraph(line.rstrip(":") + ":", "bold", GREEN_DARK)
                else:
                    f.bullets([line])
        if t.get("notes"):
            f.gap(6)
            f.paragraph(t["notes"], "italic", MUTED, max(MIN_FS - 6, f.fs - 10))

    pages = _flow_pages(payload, size, "Agricultural recommendations", build)
    return _finish(payload, pages, out_dir, "recommendations", "Recommendations", suffix,
                   f"{PRODUCT_NAMES.get(payload['type'], '')}, {payload['period']['label']}: agricultural recommendations")


# ------------------------------------------------------------------ ENVI ---

def envi_pages(payload: dict, out_dir: Path) -> tuple[dict, list[dict]]:
    """ENVI title, summary and recommendations pages, each landscape (presentation) and portrait (A4 poster).
    Returns (title entry, [summary and recommendations entries, in order]) for the manifest. The two formats may
    need a different number of pages; a page that exists in one format only is shown in that format only."""
    out: dict[str, dict] = {}
    order: list[str] = []
    for fmt, size, kind in (("landscape", LANDSCAPE, "presentation"), ("portrait", PORTRAIT, "poster")):
        made = [title_page(payload, out_dir, size, fmt), *summary_pages(payload, out_dir, size, fmt),
                *recommendations_pages(payload, out_dir, size, fmt)]
        for p in made:
            if p["layer"] not in out:
                out[p["layer"]] = {"layer": p["layer"], "label": p["label"], "alt": p["alt"]}
                order.append(p["layer"])
            out[p["layer"]][kind], out[p["layer"]][f"{kind}_web"] = p["png"].name, p["jpg"].name

    def rank(pid: str):
        base, _, n = pid.partition("_")
        return ({"cover": 0, "summary": 1, "recommendations": 2}.get(base, 9), int(n or 1))

    rest = sorted((pid for pid in order if pid != "cover"), key=rank)
    return out["cover"], [out[pid] for pid in rest]
