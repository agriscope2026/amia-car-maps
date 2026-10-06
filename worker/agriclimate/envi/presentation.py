"""Presentation-ready infographic (Pillow), styled after canva_template.pdf.

Two formats:
  * ``slide``  – 1920×1080 (16:9): header, left info column + legend, map centre, summary right
  * ``poster`` – A4 portrait at 300 dpi (2480×3508): header, large map, summary + methodology below
"""
from __future__ import annotations

import re
from pathlib import Path

import matplotlib
from PIL import Image, ImageDraw, ImageFont

from . import config

GREEN = (11, 98, 55)          # DA green used in the Canva template
GREEN_DARK = (8, 74, 41)
INK = (33, 37, 41)
MUTED = (95, 99, 104)
PANEL_TEXT = (255, 255, 255)
LIGHT = (241, 246, 242)

# Montserrat (bundled in assets/fonts) first; system fonts only as a fallback.
_FONT_DIRS = [config.FONT_DIR, Path(r"C:\Windows\Fonts"), Path(matplotlib.get_data_path()) / "fonts" / "ttf"]
_FONT_FILES = {
    "regular": ["Montserrat-Regular.ttf", "segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"],
    "bold": ["Montserrat-Bold.ttf", "segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"],
    "semibold": ["Montserrat-SemiBold.ttf", "seguisb.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf"],
    "italic": ["Montserrat-Italic.ttf", "segoeuii.ttf", "ariali.ttf", "DejaVuSans-Oblique.ttf"],
}


def font(style: str, size: float) -> ImageFont.FreeTypeFont:
    for name in _FONT_FILES[style]:
        for d in _FONT_DIRS:
            p = d / name
            if p.exists():
                return ImageFont.truetype(str(p), int(round(size)))
    return ImageFont.load_default(size=int(size))


def _hex(c: str) -> tuple:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


class Canvas:
    """Thin wrapper over ImageDraw working in design units (scaled by ``s``)."""

    def __init__(self, w: int, h: int, s: float = 1.0):
        self.img = Image.new("RGB", (w, h), "white")
        self.d = ImageDraw.Draw(self.img)
        self.s = s

    def f(self, style, size):
        return font(style, size * self.s)

    def text(self, x, y, s, style="regular", size=16, fill=INK, anchor="la"):
        self.d.text((x * self.s, y * self.s), s, font=self.f(style, size), fill=fill, anchor=anchor)

    def width(self, s, style, size):
        return self.d.textlength(s, font=self.f(style, size)) / self.s

    def wrap(self, s, style, size, maxw):
        words, lines, cur = s.split(), [], ""
        for w in words:
            t = (cur + " " + w).strip()
            if self.width(t, style, size) <= maxw or not cur:
                cur = t
            else:
                lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines

    def para(self, x, y, s, maxw, style="regular", size=16, fill=INK, lh=1.38):
        for line in self.wrap(s, style, size, maxw):
            self.text(x, y, line, style, size, fill)
            y += size * lh
        return y

    def rich_bullet(self, x, y, head, body, maxw, size=16, fill=INK, lh=1.38, bullet=True):
        """Bullet with a bold lead-in followed by regular text, wrapped."""
        if bullet:
            r = size * 0.18
            self.d.ellipse([(x + 4 - r) * self.s, (y + size * 0.62 - r) * self.s,
                            (x + 4 + r) * self.s, (y + size * 0.62 + r) * self.s], fill=fill)
            x += 18
            maxw -= 18
        tokens = [(w, "bold") for w in head.split()] + [(w, "regular") for w in body.split()]
        cx = x
        for word, st in tokens:
            ww = self.width(word, st, size)
            if cx > x and cx + ww > x + maxw:
                cx = x
                y += size * lh
            self.text(cx, y, word, st, size, fill)
            cx += ww + self.width(" ", "regular", size)
        return y + size * lh

    def rrect(self, x, y, w, h, fill, r=14, outline=None, width=1):
        self.d.rounded_rectangle([x * self.s, y * self.s, (x + w) * self.s, (y + h) * self.s], radius=r * self.s,
                                 fill=fill, outline=outline, width=int(width * self.s) or 1)

    def rect(self, x, y, w, h, fill, outline=None, width=1):
        self.d.rectangle([x * self.s, y * self.s, (x + w) * self.s, (y + h) * self.s], fill=fill, outline=outline,
                         width=max(1, int(width * self.s)))

    def paste(self, path_or_img, x, y, w, h, align="center"):
        im = path_or_img if isinstance(path_or_img, Image.Image) else Image.open(path_or_img)
        im = im.convert("RGBA")
        sc = min(w / im.width, h / im.height)
        nw, nh = int(im.width * sc * self.s), int(im.height * sc * self.s)
        im = im.resize((nw, nh), Image.LANCZOS)
        px = int(x * self.s + ((w * self.s - nw) / 2 if align == "center" else 0))
        py = int(y * self.s + (h * self.s - nh) / 2)
        self.img.paste(im, (px, py), im)
        return px / self.s, py / self.s, nw / self.s, nh / self.s


# ------------------------------------------------------------------ content ---

def _content(meta: dict) -> dict:
    w = meta["weights"]
    lab = meta.get("labels") or config.period_labels()
    pct = {k: f"{round(v * 100):d}%" for k, v in w.items()}
    meth = {"equal": "equal intervals (0–0.2–0.4–0.6–0.8–1.0)", "quantile": "quantiles (20% of areas per class)",
            "jenks": "natural breaks (Jenks)"}[meta["classification"]]
    level = "municipalities" if meta["level"] == "municipal" else "provinces"
    n_months = len(meta.get("hazard_months") or []) or "outlook"
    years = ", ".join(meta.get("damage_years") or [])
    years_txt = f" ({years})" if years else ""
    if meta.get("hazard_type") == "numeric":
        hazard = f"PAGASA monthly outlook for {lab['period']}, by province; mean of the monthly values."
    else:
        hazard = (f"PAGASA monthly outlook for {lab['period']}, by province. Not affected = 0, dry condition = 1, "
                  f"dry spell = 2, drought = 3, summed over the {n_months} months.")
    return {
        "title": "El Niño Vulnerability Index (ENVI) – Cordillera Administrative Region",
        "subtitle": f"Outlook: {lab['period']}  ·  as of {lab['issued']}  ·  "
                    "drought forecast + historical El Niño damage + standing crops",
        "overview": (f"This map combines the drought hazard forecast, historical El Niño crop damage and the standing "
                     f"rice and corn area of CAR's {meta['n_areas']} {level} into one index. It is meant to guide "
                     "mitigation, pre-positioning of resources and emergency response during the El Niño dry spell."),
        "method": ("Each indicator is rescaled to 0–1 with min–max normalization, x′ = (x − min) / (max − min), "
                   "where higher always means more vulnerable. ENVI is the weighted sum of the normalized "
                   f"indicators. Classes: {meth}."),
        "indicators": [
            (f"Drought forecast ({pct['hazard']}):", hazard),
            (f"Historical damage ({pct['damage']}):",
             f"mean area damaged (ha) in past El Niño / drought events{years_txt}."),
            (f"Standing crops ({pct['crops']}):",
             f"rice + corn standing area (ha) as of {lab['crops_as_of']}."),
        ],
        "footnote": (f"Indicators: drought forecast, historical El Niño damage, standing crops  ·  Min–max "
                     f"normalization (0–1)  ·  Weights: {pct['hazard']} / {pct['damage']} / {pct['crops']}  ·  "
                     f"Period: {lab['period']}  ·  Issued: {lab['issued']}"),
        "sources": (f"Data sources: DOST-PAGASA drought forecast ({lab['period']}); DA-RFO-CAR historical El Niño "
                    f"damage logs{years_txt}; DA-RFO-CAR standing crops inventory as of {lab['crops_as_of']}. "
                    "Map: DA-RFO-CAR AMIA."),
    }


# --------------------------------------------------------- recommendations ---

_ITEM_RE = re.compile(r"^(\d+[.)]|[•\-*])\s*(.*)$")


def _rec_rows(cv: Canvas, text: str, w: float, size: float):
    """Wrap recommendation text into rows: None = paragraph gap, else (indent, marker, [(word, style)]).

    Headings ending in ':' are bold; numbered / bulleted items get a hanging indent and a bold lead-in
    (the text before the first ':').
    """
    rows = []
    space = cv.width(" ", "regular", size)
    for raw in text.replace("\r", "").split("\n"):
        line = raw.strip()
        if not line:
            if rows and rows[-1] is not None:
                rows.append(None)
            continue
        marker, indent = None, 0
        m = _ITEM_RE.match(line)
        if m:
            marker = "•" if m.group(1) in "-*" else m.group(1)
            indent = max(20, cv.width(marker, "bold", size) + 8)
            rest = m.group(2)
            head, sep, body = rest.partition(":")
            segs = [(head + ":", "bold"), (body, "regular")] if sep and len(head) <= 40 else [(rest, "regular")]
        elif line.endswith(":") and len(line) < 70:
            segs = [(line, "bold")]
        else:
            segs = [(line, "regular")]
        words = [(wd, st) for t, st in segs for wd in t.split()]
        cur, cw, first = [], 0.0, True
        for wd, st in words:
            ww = cv.width(wd, st, size)
            if cur and cw + ww > w - indent:
                rows.append((indent, marker if first else None, cur))
                first, cur, cw = False, [], 0.0
            cur.append((wd, st))
            cw += ww + space
        if cur:
            rows.append((indent, marker if first else None, cur))
    while rows and rows[-1] is None:
        rows.pop()
    return rows


def condense_recommendations(text: str, limit: int = 120) -> str:
    """Short version for the slide: numbered/bulleted items keep their lead-in and first clause."""
    out = []
    for raw in text.replace("\r", "").split("\n"):
        line = raw.strip()
        m = _ITEM_RE.match(line)
        if m:
            body = m.group(2)
            for sep in (". ", "; ", " – "):
                cut = body.find(sep, 25)
                if 0 < cut < limit:
                    body = body[:cut].rstrip(".;") + "."
                    break
            if len(body) > limit:
                body = body[:limit].rsplit(" ", 1)[0].rstrip(",;") + "…"
            line = f"{m.group(1)} {body}"
        out.append(line)
    return "\n".join(out)


def _rec_block(cv: Canvas, x, y, w, y_max, text: str, max_size=15.5, min_size=11.5,
               title="Recommended Actions", title_size=21):
    """Draw the recommendations, shrinking the font until they fit between y and y_max (truncated if needed)."""
    if not text or not text.strip():
        return y
    cv.text(x + 4, y, title, "bold", title_size, INK)
    y += title_size * 1.7
    size = max_size
    while True:
        rows = _rec_rows(cv, text, w - 8, size)
        h = sum(size * (0.55 if r is None else 1.36) for r in rows)
        if y + h <= y_max or size <= min_size:
            break
        size -= 0.5
    yy = y
    for r in rows:
        if r is not None and yy + size * 1.36 > y_max:
            cv.text(x + 4, yy, "… full recommendations in the A4 poster and Excel report", "italic", size - 1, MUTED)
            break
        if r is None:
            yy += size * 0.55
            continue
        indent, marker, words = r
        if marker:
            cv.text(x + 4, yy, marker, "bold", size, GREEN_DARK)
        cx = x + 4 + indent
        for wd, st in words:
            cv.text(cx, yy, wd, st, size, INK)
            cx += cv.width(wd, st, size) + cv.width(" ", "regular", size)
        yy += size * 1.36
    return yy


def _fmt_ha(v: float) -> str:
    return f"{v:,.0f} ha"


def _legend(cv: Canvas, x, y, w, meta, size=17, panel=True):
    items = meta["summary"]["legend"]
    row = size * 2.0
    h = 64 + row * len(items) + 14
    if panel:
        cv.rrect(x, y, w, h, GREEN, r=16)
    tc = PANEL_TEXT if panel else INK
    cv.text(x + 24, y + 18, "Vulnerability Index Legend", "bold", size + 4, tc)
    yy = y + 64
    for it in items:
        cv.rrect(x + 24, yy, 40, row - 10, _hex(it["color"]), r=6, outline=(255, 255, 255), width=1.5)
        rng = f"{it['range']} ({it['class']})" if it["range"] else it["class"]
        cv.text(x + 78, yy + (row - 10) / 2, rng, "regular", size, tc, anchor="lm")
        cnt = f"{it['count']} area{'s' if it['count'] != 1 else ''}"
        cv.text(x + w - 24, yy + (row - 10) / 2, cnt, "semibold", size - 2, tc, anchor="rm")
        yy += row
    return y + h


def _class_bars(cv: Canvas, x, y, w, meta, size=16):
    counts = meta["summary"]["class_counts"]
    names = config.CLASS_NAMES + ([config.NO_DATA_LABEL] if counts.get(config.NO_DATA_LABEL) else [])
    mx = max(counts.values()) or 1
    lw = 110
    bw = w - lw - 50
    for n in names:
        c = counts.get(n, 0)
        col = _hex(config.CLASS_COLORS.get(n, config.NO_DATA_COLOR))
        cv.text(x, y + 13, n, "semibold", size, INK, anchor="lm")
        cv.rrect(x + lw, y + 2, bw, 22, LIGHT, r=6)
        if c:
            cv.rrect(x + lw, y + 2, max(10, bw * c / mx), 22, col, r=6)
        cv.text(x + lw + bw + 12, y + 13, str(c), "bold", size, INK, anchor="lm")
        y += 32
    return y


def _top10(cv: Canvas, x, y, w, meta, size=16, rows=10):
    top = meta["summary"]["top10"][:rows]
    rh = size * 1.95
    cv.text(x, y, "#", "bold", size - 1, MUTED)
    cv.text(x + 40, y, "Municipality / Province" if meta["level"] == "municipal" else "Province", "bold", size - 1, MUTED)
    cv.text(x + w - 150, y, "ENVI", "bold", size - 1, MUTED, anchor="ra")
    cv.text(x + w, y, "Class", "bold", size - 1, MUTED, anchor="ra")
    y += size * 1.6
    cv.d.line([(x * cv.s, y * cv.s), ((x + w) * cv.s, y * cv.s)], fill=(200, 205, 200), width=max(1, int(cv.s)))
    y += 6
    for i, r in enumerate(top):
        if i % 2 == 0:
            cv.rect(x - 6, y - 2, w + 12, rh, (247, 249, 247))
        mid = y + rh / 2 - 2
        cv.text(x, mid, str(r["rank"]), "bold", size, GREEN_DARK, anchor="lm")
        name = r["area"] + (f", {r['province']}" if meta["level"] == "municipal" else "")
        cv.text(x + 40, mid, name, "regular", size, INK, anchor="lm")
        cv.text(x + w - 150, mid, f"{r['envi']:.3f}", "semibold", size, INK, anchor="rm")
        col = _hex(r["color"])
        tw = cv.width(r["class"], "semibold", size - 3) + 20
        cv.rrect(x + w - tw, mid - 12, tw, 24, col, r=12)
        dark = sum(col) < 420
        cv.text(x + w - tw / 2, mid, r["class"], "semibold", size - 3, (255, 255, 255) if dark else INK, anchor="mm")
        y += rh
    return y


def _hotspots(cv: Canvas, x, y, w, y_max, meta, size=15.5):
    """Hotspots (High + Very High) grouped by province, as many as fit above ``y_max``."""
    hs = meta["summary"].get("hotspots", [])
    if not hs or y + 70 > y_max:
        return y
    cv.text(x + 4, y, "Risk Hotspots (High + Very High)", "bold", 21, INK)
    y += 36
    for h in hs:
        names = ", ".join(a.split(" (")[0] for a in h["areas"])
        lines = cv.wrap(f"{h['province']}: {names}", "regular", size, w - 28)
        if y + len(lines) * size * 1.38 > y_max:
            break
        y = cv.rich_bullet(x + 6, y, f"{h['province']}:", names, w - 10, size=size) + 2
    return y


def _at_risk(cv: Canvas, x, y, w, meta, size=17):
    s = meta["summary"]
    h = 116
    cv.rrect(x, y, w, h, LIGHT, r=14, outline=(205, 220, 208), width=1.5)
    cv.text(x + 22, y + 16, "Standing crop area at risk (High + Very High)", "semibold", size - 1, MUTED)
    cv.text(x + 22, y + 44, _fmt_ha(s["crop_at_risk_ha"]), "bold", size * 2.1, (200, 50, 40))
    share = s["crop_at_risk_ha"] / s["crop_total_ha"] * 100 if s["crop_total_ha"] else 0
    by = "  ·  ".join(f"{k} {_fmt_ha(v)}" for k, v in s["crop_at_risk_by_crop"].items())
    vx = x + 22 + cv.width(_fmt_ha(s["crop_at_risk_ha"]), "bold", size * 2.1) + 22
    cv.text(vx, y + 50, f"{share:.0f}% of {_fmt_ha(s['crop_total_ha'])} in {s['n_at_risk']} areas", "regular",
            size - 2, INK)
    cv.text(vx, y + 76, by, "regular", size - 2, MUTED)
    return y + h


def _header(cv: Canvas, W, c, title_size=40, sub_size=21, logo_h=96, y=18):
    da = config.LOGO_DIR / "DA CAR LOGO no background.png"
    x0 = 28
    if da.exists():
        _, _, lw, _ = cv.paste(da, x0, y, logo_h * 1.15, logo_h, align="left")
        x0 += lw + 22
    right = W - 28
    for name in ("AMIA_Logo.png", "Bagong_Pilipinas_logo.png"):
        p = config.LOGO_DIR / name
        if p.exists():
            px, _, lw, _ = cv.paste(p, right - logo_h * 0.95, y + logo_h * 0.08, logo_h * 0.95, logo_h * 0.84)
            right = px - 14
    cx = (x0 + right) / 2
    tsize = title_size
    while cv.width(c["title"], "bold", tsize) > right - x0 and tsize > 20:
        tsize -= 1
    cv.text(cx, y + logo_h * 0.42, c["title"], "bold", tsize, GREEN_DARK, anchor="mm")
    ssize = sub_size
    while cv.width(c["subtitle"], "italic", ssize) > right - x0 and ssize > 12:
        ssize -= 1
    cv.text(cx, y + logo_h * 0.86, c["subtitle"], "italic", ssize, MUTED, anchor="mm")
    return y + logo_h + 14


# ------------------------------------------------------------------- slide ---

def build_slide(meta: dict, map_png: Path, out: Path, scale: float = 1.0, recommendations: str = "") -> Path:
    W, H = 1920, 1080
    cv = Canvas(int(W * scale), int(H * scale), scale)
    c = _content(meta)
    top = _header(cv, W, c)

    # left column
    lx, lw = 28, 600
    y = top + 6
    ov_lines = cv.wrap(c["overview"], "regular", 17, lw - 44)
    oh = 58 + len(ov_lines) * 17 * 1.38 + 16
    cv.rrect(lx, y, lw, oh, GREEN, r=16)
    cv.text(lx + 22, y + 16, "Overview & Objective", "bold", 21, PANEL_TEXT)
    cv.para(lx + 22, y + 54, c["overview"], lw - 44, size=17, fill=PANEL_TEXT)
    y += oh + 22
    recs = (recommendations or "").strip()
    if not recs:   # the min–max formula is also in the footnote, so it gives way to recommendations
        cv.text(lx + 4, y, "Assessment Formula & Methodology", "bold", 21, INK)
        y = cv.para(lx + 4, y + 36, c["method"], lw - 8, size=16.5) + 10
    cv.text(lx + 4, y, "Criteria & Factor Weights", "bold", 21, INK)
    y += 36
    for head, body in c["indicators"]:
        y = cv.rich_bullet(lx + 6, y, head, body, lw - 10, size=16 if not recs else 15) + 4
    legend_h = 64 + 17 * 2.0 * len(meta["summary"]["legend"]) + 14
    legend_y = H - 66 - legend_h - 6
    if recs:
        _rec_block(cv, lx, y + 10, lw, legend_y - 12, condense_recommendations(recs), max_size=14.5,
                   min_size=11.5, title_size=20)
    else:
        _hotspots(cv, lx, y + 10, lw, legend_y - 14, meta)
    _legend(cv, lx, max(y + 12, legend_y), lw, meta, size=17)

    # map centre
    mx, mw = 648, 610
    cv.paste(map_png, mx, top - 4, mw, H - top - 68)

    # right column
    rx, rw = 1276, 616
    y = top + 6
    cv.rrect(rx, y, rw, 52, GREEN, r=14)
    cv.text(rx + 22, y + 26, "Summary of Results", "bold", 21, PANEL_TEXT, anchor="lm")
    y += 66
    cv.text(rx + 4, y, "Number of areas per class", "bold", 18, INK)
    y = _class_bars(cv, rx + 4, y + 32, rw - 8, meta, size=16) + 8
    y = _at_risk(cv, rx, y, rw, meta, size=17) + 16
    cv.text(rx + 4, y, "Top 10 most vulnerable areas", "bold", 18, INK)
    _top10(cv, rx + 10, y + 34, rw - 20, meta, size=15.5)

    # footer
    fy = H - 58
    cv.d.line([(28 * scale, fy * scale), ((W - 28) * scale, fy * scale)], fill=(205, 212, 206), width=max(1, int(scale)))
    cv.text(W / 2, fy + 17, c["footnote"], "semibold", 14.5, GREEN_DARK, anchor="mm")
    cv.text(W / 2, fy + 39, c["sources"], "italic", 12.5, MUTED, anchor="mm")
    out.parent.mkdir(parents=True, exist_ok=True)
    cv.img.save(out, dpi=(96 * scale, 96 * scale))
    return out


# ------------------------------------------------------------------ poster ---

def build_poster(meta: dict, map_png: Path, out: Path, recommendations: str = "", scale: float = 2.0) -> Path:
    """A4 portrait. Design units: 1240 × 1754; scale 2 = 300 dpi (2480 × 3508), scale 3 = 450 dpi."""
    W, H, s = 1240, 1754, scale
    cv = Canvas(int(W * s), int(H * s), s)
    c = _content(meta)
    lab = meta.get("labels") or config.period_labels()
    c["subtitle"] = f"Outlook: {lab['period']}  ·  as of {lab['issued']}"
    recs = (recommendations or "").strip()
    map_h = 800 if recs else 1110
    top = _header(cv, W, c, title_size=30, sub_size=19, logo_h=84, y=24)

    # map with legend (left) and summary (right)
    cv.paste(map_png, 20, top, 700, map_h)
    rx, rw = 730, 486
    y = top + 4
    y = _legend(cv, rx, y, rw, meta, size=16) + 20
    cv.text(rx + 4, y, "Number of areas per class", "bold", 18, INK)
    y = _class_bars(cv, rx + 4, y + 32, rw - 8, meta, size=15) + 10
    y = _at_risk_compact(cv, rx, y, rw, meta) + 24
    _hotspots(cv, rx, y, rw, top + map_h - 10, meta, size=15)

    # lower band
    y = top + map_h + 15
    cv.rrect(24, y, W - 48, 52, GREEN, r=14)
    cv.text(46, y + 26, "Top 10 most vulnerable areas", "bold", 21, PANEL_TEXT, anchor="lm")
    cv.text(W / 2 + 24, y + 26, "Methodology", "bold", 21, PANEL_TEXT, anchor="lm")
    top10_end = _top10(cv, 40, y + 74, W / 2 - 80, meta, size=15)
    mx = W / 2 + 24
    yy = cv.para(mx, y + 74, c["method"], W / 2 - 64, size=15.5) + 8
    for head, body in c["indicators"]:
        yy = cv.rich_bullet(mx, yy, head, body, W / 2 - 64, size=15) + 2
    yy += 10
    if not recs:
        cv.para(mx, yy, c["overview"], W / 2 - 64, size=14, fill=MUTED, style="italic")

    foot = cv.wrap(c["footnote"], "semibold", 14, W - 60)
    srcs = cv.wrap(c["sources"], "italic", 12, W - 60)
    fy = H - 18 - (12 + 21 * len(foot) + 18 * len(srcs))    # footer sized to its wrapped lines
    if recs:
        ry = max(yy, top10_end) + 14
        cv.rrect(24, ry, W - 48, fy - ry - 14, LIGHT, r=14, outline=(205, 220, 208), width=1.5)
        _rec_block(cv, 40, ry + 14, W - 80, fy - 28, recs, max_size=15, min_size=11, title_size=21)
    cv.d.line([(24 * s, fy * s), ((W - 24) * s, fy * s)], fill=(205, 212, 206), width=2)
    yy = fy + 12
    for line in foot:
        cv.text(W / 2, yy, line, "semibold", 14, GREEN_DARK, anchor="ma")
        yy += 21
    for line in srcs:
        cv.text(W / 2, yy, line, "italic", 12, MUTED, anchor="ma")
        yy += 18
    out.parent.mkdir(parents=True, exist_ok=True)
    cv.img.save(out, dpi=(150 * s, 150 * s))
    return out


def _at_risk_compact(cv: Canvas, x, y, w, meta):
    s = meta["summary"]
    h = 150
    cv.rrect(x, y, w, h, LIGHT, r=14, outline=(205, 220, 208), width=1.5)
    cv.text(x + 20, y + 16, "Standing crop area at risk", "semibold", 16, MUTED)
    cv.text(x + 20, y + 38, "(High + Very High classes)", "regular", 14, MUTED)
    cv.text(x + 20, y + 64, _fmt_ha(s["crop_at_risk_ha"]), "bold", 34, (200, 50, 40))
    share = s["crop_at_risk_ha"] / s["crop_total_ha"] * 100 if s["crop_total_ha"] else 0
    by = "  ·  ".join(f"{k} {_fmt_ha(v)}" for k, v in s["crop_at_risk_by_crop"].items())
    cv.text(x + 20, y + 112, f"{share:.0f}% of total, {s['n_at_risk']} areas  ·  {by}", "regular", 14, INK)
    return y + h


def build_all(meta: dict, map_png: Path, out_dir: Path, recommendations: str = "") -> dict:
    return {
        "slide": build_slide(meta, map_png, out_dir / "presentation_1920x1080.png", recommendations=recommendations),
        "poster": build_poster(meta, map_png, out_dir / "presentation_A4_poster.png", recommendations=recommendations),
    }
