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


def _canvas(size: tuple[int, int]) -> Canvas:
    cv = Canvas(int(size[0] * SCALE), int(size[1] * SCALE), SCALE)
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
    cv.text(W / 2, 52, kicker.upper(), "semibold", 17, MUTED, anchor="mm")
    title = t.get("title") or payload.get("title", "")
    cv.text(W / 2, 88, title, "bold", _fit(cv, title, "bold", 34, W - 380, 20), GREEN_DARK, anchor="mm")
    cv.text(W / 2, 122, f"{payload['period']['label']}  ·  as of {_date(payload.get('issued', ''))}", "italic", 18,
            MUTED, anchor="mm")
    cv.d.line([(40 * cv.s, 146 * cv.s), ((W - 40) * cv.s, 146 * cv.s)], fill=GREEN, width=int(4 * cv.s))
    return 166


def _source_line(payload: dict) -> str:
    return ("Drought forecast: DOST-PAGASA · Damage and standing crops: DA-RFO-CAR" if payload["type"] == "envi"
            else "Weather source: DOST-PAGASA")


def _footer(cv: Canvas, payload: dict, page: str):
    W, H = cv.W, cv.H
    t = payload.get("texts", {})
    y = H - 58
    cv.d.line([(40 * cv.s, y * cv.s), ((W - 40) * cv.s, y * cv.s)], fill=(205, 212, 206), width=max(1, int(cv.s)))
    src = f"Sources: {t.get('sources') or payload.get('source', '')}"
    for i, l in enumerate(cv.wrap(src, "italic", 12.5, W - 260)[:2]):
        cv.text(40, y + 10 + i * 17, l, "italic", 12.5, MUTED)
    cv.text(W - 40, y + 10, page, "semibold", 13, GREEN_DARK, anchor="ra")
    cv.text(W - 40, y + 28, "DA-RFO-CAR · AMIA Program", "regular", 12, MUTED, anchor="ra")


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
    cv.text(tx, 32, l1, "regular", _fit(cv, l1, "regular", 19, tw), GREEN)
    cv.text(tx, 58, l2, "bold", _fit(cv, l2, "bold", 24, tw), AMBER)
    cv.text(tx, 92, l3, "italic", _fit(cv, l3, "italic", 14.5, tw), INK)
    return 128


def _legend_items(payload: dict) -> tuple[dict, list]:
    lyr = next((l for l in payload["layers"] if l["id"] == "envi"), payload["layers"][0])
    return lyr["legend"], lyr["legend"]["classes"]


def _legend_height(payload: dict, max_h: float, row: float = 40) -> float:
    return min(max_h, 86 + row * len(_legend_items(payload)[1]) + 10)


def _legend_panel(cv: Canvas, payload: dict, x: float, y: float, w: float, h: float, max_row: float = 40):
    lg, items = _legend_items(payload)
    title = (payload.get("texts", {}).get("legend_title") or lg.get("title") or "").rstrip(":")
    title = re.sub(r"(?i)^legend\s*", "", title).strip()               # "LEGEND in millimeters (mm)" → "in millimeters (mm)"
    if title.startswith("(") and title.endswith(")") and title.count("(") == 1:
        title = title[1:-1]
    if title.lower().startswith("in "):
        title = ("Rainfall " if lg.get("unit") == "mm" else "") + title
    cv.rrect(x, y, w, h, LIGHT, r=14)
    cv.text(x + 22, y + 18, "LEGEND", "bold", 18, GREEN_DARK)
    if title:
        cv.text(x + 22, y + 44, title, "regular", _fit(cv, title, "regular", 15, w - 44), MUTED)
    row = min(max_row, (h - 86) / max(len(items), 1))
    fs = min(22, row * 0.45)
    for i, c in enumerate(items):
        yy = y + 76 + i * row
        cv.rect(x + 22, yy, 44, row * 0.7, _hex(c["color"]), outline=(90, 90, 90))
        unit = " mm" if lg.get("unit") == "mm" and lg.get("kind") == "graduated" else ""
        label = c["label"] + unit
        if payload["type"] == "envi" and c.get("lo") is not None and c.get("hi") is not None:
            label = f"{c['lo']:.2f}–{c['hi']:.2f}  {c['label']}"
        text = f"{label}  –  {c['desc']}" if c.get("desc") else label
        cv.text(x + 80, yy + row * 0.35, text, "regular", _fit(cv, text, "regular", fs, w - 104), INK, anchor="lm")


def _qr_block(cv: Canvas, x: float, y: float, w: float, size: float, caption: str, url: str):
    cv.text(x + w / 2, y, caption, "italic", 17, INK, anchor="ma")
    shown = url.replace("https://", "").replace("http://", "").rstrip("/")
    cv.text(x + w / 2, y + 26, shown, "semibold", _fit(cv, shown, "semibold", 24, w - 10), AMBER, anchor="ma")
    tw = cv.width(shown, "semibold", _fit(cv, shown, "semibold", 24, w - 10))
    cv.d.line([((x + w / 2 - tw / 2) * cv.s, (y + 58) * cv.s), ((x + w / 2 + tw / 2) * cv.s, (y + 58) * cv.s)],
              fill=AMBER, width=int(2 * cv.s))
    cv.paste(_qr(url), x + (w - size) / 2, y + 70, size, size)


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
    cv.text(W / 2, y, issued, "semibold", 20, GREEN_DARK, anchor="ma")
    y += 48

    # legend + QR codes, centred in the space left above the source line
    bottom = H - 120
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
    cv.text(W / 2, H - 92, src, "bold", _fit(cv, src, "bold", 20, W - 80), GREEN_DARK, anchor="mm")
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
    exp = [f"Season outlook: {len(s_risk)} of {len(season['values'])} municipalities High or Very High, holding "
           f"{crops:,.0f} ha of standing crops."]
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


def _text_panel(cv: Canvas, x, y, w, title: str, lines: list[str], size=16) -> float:
    """Light panel with a title and bullet sentences; returns its bottom."""
    body_h = sum(len(cv.wrap(l, "regular", size, w - 62)) * size * 1.38 + 6 for l in lines) or size * 1.4
    h = 56 + body_h + 14
    cv.rrect(x, y, w, h, LIGHT, r=14)
    cv.rect(x, y, 8, h, GREEN)
    cv.text(x + 26, y + 16, title, "bold", 21, GREEN_DARK)
    yy = y + 52
    for l in lines or ["No data."]:
        yy = cv.rich_bullet(x + 26, yy, "", l, w - 50, size=size) + 6
    return y + h


# ------------------------------------------------- summary: key figures ---

def _rain_figures(cv: Canvas, payload: dict, y: float):
    W = cv.W
    total = _values(common.total_layer(payload))
    if total.empty:
        return
    dekad = payload["type"] == "rainfall_dekad"
    what = "10-day total" if dekad else "season total"
    w = (W - 80 - 3 * 16) / 4
    cards = [(f"{total.min():,.0f}–{total.max():,.0f} mm", f"range of the {what}"),
             (f"{total.mean():,.0f} mm", f"CAR average {what}"),
             (f"{total.max():,.0f} mm", f"highest: {_name(total.idxmax())}"),
             (f"{total.min():,.0f} mm", f"lowest: {_name(total.idxmin())}")]
    for i, (big, small) in enumerate(cards):
        _card(cv, 40 + i * (w + 16), y, w, 100, big, small)
    y += 118
    cv.text(40, y, "Day by day" if dekad else "Month by month", "bold", 20, GREEN_DARK)
    y += 30
    rows = []
    for l in [l for l in payload["layers"] if l["id"].startswith(("d_", "m_"))]:
        v = _values(l)
        if not v.empty:
            rows.append([l["label"], f"{v.mean():,.0f}", f"{v.min():,.0f}", f"{v.max():,.0f}", _name(v.idxmax())])
    room = cv.H - 80 - y - 30
    row_h = max(22, min(30, room / max(len(rows) + 1, 1)))
    _table(cv, 40, y, [("Day" if dekad else "Month", 170, "l"), ("Average mm", 140, "r"), ("Lowest mm", 130, "r"),
                       ("Highest mm", 130, "r"), ("Wettest municipality", W - 80 - 570, "l")], rows,
           size=min(15, row_h * 0.52), row_h=row_h)


def _drought_figures(cv: Canvas, payload: dict, y: float):
    W = cv.W
    by = payload.get("summary", {}).get("by_month_province") or {}
    months = payload["period"].get("months") or list(by)
    if not by or not months:
        return
    legend = payload["layers"][0]["legend"]["classes"]
    color = {c["label"]: c["color"] for c in legend}
    provs = sorted({p for m in months for p in by.get(m, {})})
    cv.text(40, y, "Province outlook by month", "bold", 20, GREEN_DARK)
    y += 30
    mw = (W - 80 - 230) / len(months)
    cols = [("Province", 230, "l")] + [(pd.Period(m, "M").strftime("%b %Y"), mw, "c") for m in months]
    rows = [[p] + [by.get(m, {}).get(p, "–") for m in months] for p in provs]
    fills = [[None] + [color.get(by.get(m, {}).get(p, ""), None) for m in months] for p in provs]
    y = _table(cv, 40, y, cols, rows, size=13.5, row_h=36, fills=fills) + 16
    x = 40
    for c in legend:
        cv.rect(x, y + 2, 26, 18, _hex(c["color"]), outline=(80, 80, 80))
        cv.text(x + 34, y + 11, c["label"], "regular", 15, INK, anchor="lm")
        x += 54 + cv.width(c["label"], "regular", 15)
    y += 46
    if cv.H - 80 - y > 190:
        cv.text(40, y, "Number of provinces per category", "bold", 20, GREEN_DARK)
        rows = [[c["label"]] + [sum(1 for p in provs if by.get(m, {}).get(p) == c["label"]) for m in months] for c in legend]
        _table(cv, 40, y + 30, [("Category", 230, "l")] + cols[1:], rows, size=14, row_h=28)


def _envi_figures(cv: Canvas, payload: dict, y: float):
    W, H = cv.W, cv.H
    layers = [l for l in payload["layers"] if l["id"] == "envi" or l["id"].startswith("m_")]
    season = layers[0]
    classes = season["legend"]["classes"]
    color = {c["label"]: c["color"] for c in classes}
    cv.text(40, y, "Season outlook and month by month (number of municipalities per class)", "bold", 20, GREEN_DARK)
    y += 30
    cw = 92 if W < 1500 else 120
    rest = W - 80 - 190 - cw * len(classes) - 150
    cols = [("Period", 190, "l")] + [(c["label"], cw, "c") for c in classes] + [("Crops at risk (ha)", 150, "r"),
                                                                                ("Most vulnerable", rest, "l")]
    rows, fills = [], []
    for l in layers:
        vals = [(k, v) for k, v in l["values"].items() if isinstance(v.get("envi"), (int, float))]
        counts = {c["label"]: sum(1 for _, v in vals if v["class"] == c["label"]) for c in classes}
        crops = sum(v.get("crops_raw") or 0 for _, v in vals if v["class"] in RISK)
        top = max(vals, key=lambda kv: kv[1]["envi"]) if vals else None
        rows.append(["Season outlook" if l["id"] == "envi" else l["label"]] + [counts[c["label"]] for c in classes]
                    + [f"{crops:,.0f}", _name(top[0]) if top else "–"])
        fills.append([None] + [color[c["label"]] if counts[c["label"]] else None for c in classes] + [None, None])
    room = H - 80 - y
    row_h = max(22, min(30, room / (len(rows) + 1)))
    y = _table(cv, 40, y, cols, rows, size=min(14.5, row_h * 0.5), row_h=row_h, fills=fills) + 16
    vals = sorted(((k, v) for k, v in season["values"].items() if isinstance(v.get("envi"), (int, float))),
                  key=lambda kv: -kv[1]["envi"])[:10]
    if H - 80 - y > 200:
        cv.text(40, y, "Top 10 most vulnerable areas (season outlook)", "bold", 20, GREEN_DARK)
        y += 30
        parts = [vals[:5], vals[5:]]
        pw = (W - 80 - 24) / 2
        for i, part in enumerate(parts):
            _table(cv, 40 + i * (pw + 24), y, [("#", 44, "c"), ("Municipality", pw - 44 - 90 - 130, "l"),
                                                ("ENVI", 90, "r"), ("Class", 130, "c")],
                   [[i * 5 + j + 1, _name(k), f"{v['envi']:.3f}", v["class"]] for j, (k, v) in enumerate(part)],
                   size=13.5, row_h=26, fills=[[None, None, None, color.get(v["class"])] for _, v in part])


def summary_page(payload: dict, out_dir: Path, size=SQUARE, suffix: str = "") -> dict:
    """Current condition and expected forecast in words, then the key figures."""
    text = {"drought": _drought_text, "envi": _envi_text}.get(payload["type"], _rain_text)
    figures = {"drought": _drought_figures, "envi": _envi_figures}.get(payload["type"], _rain_figures)
    cur, exp = text(payload)
    for fs in (16, 15, 14, 13):
        cv = _canvas(size)
        W = cv.W
        y = _header(cv, payload, "Summary")
        if W >= 1100:   # two panels side by side
            pw = (W - 80 - 20) / 2
            y = max(_text_panel(cv, 40, y, pw, "Current condition", cur, fs),
                    _text_panel(cv, 40 + pw + 20, y, pw, "Expected forecast", exp, fs)) + 20
        else:
            y = _text_panel(cv, 40, y, W - 80, "Current condition", cur, fs) + 14
            y = _text_panel(cv, 40, y, W - 80, "Expected forecast", exp, fs) + 20
        if y < cv.H * 0.55:
            break
    figures(cv, payload, y)
    _footer(cv, payload, "Summary")
    png, jpg = _save(cv, *_files(payload, out_dir, "summary", suffix))
    return {"layer": "summary", "label": "Summary", "png": png, "jpg": jpg,
            "alt": f"{PRODUCT_NAMES.get(payload['type'], '')}, {payload['period']['label']}: current condition, "
                   "expected forecast and key figures"}


# -------------------------------------------- agricultural recommendations ---

_ADVICE = [("advice_rice", "Rice", "#2e7d32"), ("advice_corn", "Corn", "#e0a100"), ("advice_hvc", "High-value crops", "#7b3fa0")]


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


def recommendations_page(payload: dict, out_dir: Path, size=SQUARE, suffix: str = "") -> dict:
    """Agricultural recommendations: crop advice first (rice, corn, high-value crops), then the advisory."""
    t = payload.get("texts", {})
    advice = [(lab, col, t.get(k)) for k, lab, col in _ADVICE if t.get(k)]
    lines = _rec_lines(t.get("recommendations", ""))
    for fs in (19, 18, 17, 16, 15, 14, 13, 12, 11, 10):
        cv = _canvas(size)
        W, H = cv.W, cv.H
        y = _header(cv, payload, "Agricultural recommendations")
        if advice:
            cv.text(40, y, "Crop advice", "bold", 24, GREEN_DARK)
            y += 38
            colw = (W - 80 - 2 * 16) / len(advice)
            top = y
            for i, (lab, col, txt) in enumerate(advice):
                x = 40 + i * (colw + 16)
                lh = len(cv.wrap(txt, "regular", fs, colw - 40)) * fs * 1.38
                cv.rrect(x, top, colw, lh + 66, LIGHT, r=12)
                cv.rect(x, top, 8, lh + 66, _hex(col))
                cv.text(x + 24, top + 16, lab, "bold", fs + 3, _hex(col))
                y = max(y, cv.para(x + 24, top + 50, txt, colw - 40, size=fs) + 22)
            y += 8
        if lines:
            cv.text(40, y, "Agricultural advisory" if advice else "Recommended actions", "bold", 24, GREEN_DARK)
            y += 40
            for kind, line in lines:
                if kind == "head":
                    y = cv.para(40, y + 4, line, W - 80, "bold", fs, GREEN_DARK) + 2
                elif kind == "num":
                    y = cv.para(52, y, line, W - 104, size=fs) + 3
                else:
                    y = cv.rich_bullet(52, y, "", line, W - 104, size=fs) + 2
        if y <= H - 80:
            break
    if t.get("notes"):
        cv.para(40, min(y + 8, cv.H - 110), t["notes"], cv.W - 80, "italic", 13, MUTED)
    _footer(cv, payload, "Agricultural recommendations")
    png, jpg = _save(cv, *_files(payload, out_dir, "recommendations", suffix))
    return {"layer": "recommendations", "label": "Recommendations", "png": png, "jpg": jpg,
            "alt": f"{PRODUCT_NAMES.get(payload['type'], '')}, {payload['period']['label']}: agricultural recommendations"}


# ------------------------------------------------------------------ ENVI ---

def envi_pages(payload: dict, out_dir: Path) -> tuple[dict, list[dict]]:
    """ENVI title, summary and recommendations pages, each landscape (presentation) and portrait (A4 poster).
    Returns (title entry, [summary entry, recommendations entry]) for the manifest."""
    out: dict[str, dict] = {}
    for fmt, size, kind in (("landscape", LANDSCAPE, "presentation"), ("portrait", PORTRAIT, "poster")):
        made = [title_page(payload, out_dir, size, fmt), summary_page(payload, out_dir, size, fmt),
                recommendations_page(payload, out_dir, size, fmt)]
        for p in made:
            e = out.setdefault(p["layer"], {"layer": p["layer"], "label": p["label"], "alt": p["alt"]})
            e[kind], e[f"{kind}_web"] = p["png"].name, p["jpg"].name
    return out["cover"], [out["summary"], out["recommendations"]]
