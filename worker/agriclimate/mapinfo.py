"""Map-frame furniture and the farm-recommendations block of the print maps.

* compass (top-left, as in the DA samples), scale bar (bottom-right) and the mm → litres note, which is placed
  automatically in an empty spot of the frame (map labels avoid it);
* the "Farm Recommendations" block under the legend: advice for rice, corn and high-value crops (HVC).
"""
from __future__ import annotations

import math
import re
import textwrap
from functools import lru_cache

import numpy as np
from matplotlib.patches import FancyBboxPatch, Rectangle
from shapely.geometry import box as sbox
from shapely.ops import unary_union

from . import reference
from .products.crop_advice import LABELS

COMPASS = (0.22, 0.84, 0.055)                 # x, y, radius (axes fraction) – sample position
SCALE_BAR = (0.60, 0.035, 0.30, 0.03)         # x, y, w, h (axes fraction), bottom-right
INK = "#1f2428"
CROP_COLORS = {"rice": "#2e7d32", "corn": "#e0a100", "hvc": "#7b3fa0"}


# ------------------------------------------------------------- geometry ---

@lru_cache(maxsize=1)
def _region():
    _, prov = reference.boundaries()
    return unary_union(list(prov.geometry)).buffer(0.012)


def frac_to_data(ax, r):
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    fx, fy, fw, fh = r
    return (x0 + fx * (x1 - x0), y0 + fy * (y1 - y0), x0 + (fx + fw) * (x1 - x0), y0 + (fy + fh) * (y1 - y0))


def _overlaps(a, b) -> bool:
    return not (a[0] + a[2] <= b[0] or b[0] + b[2] <= a[0] or a[1] + a[3] <= b[1] or b[1] + b[3] <= a[1])


def _find(ax, w, h, taken, corner: str):
    """First free spot of size w×h (axes fraction) scanning from a corner; None if CAR is in the way."""
    region = _region()
    xs = np.arange(0.015, 0.985 - w + 1e-9, 0.01)
    ys = np.arange(0.02, 0.975 - h + 1e-9, 0.01)
    if "right" in corner:
        xs = xs[::-1]
    if "top" in corner:
        ys = ys[::-1]
    for y in ys:
        for x in xs:
            r = (float(x), float(y), w, h)
            if any(_overlaps(r, t) for t in taken):
                continue
            x0, y0, x1, y1 = frac_to_data(ax, r)
            if not region.intersects(sbox(x0, y0, x1, y1)):
                return r
    return None


def _note_lines(note: str) -> list[str]:
    return textwrap.wrap("Note: " + note, 62)


def plan_note(ax, note: str):
    """Spot for the note inside the frame (bottom-right first), or None when it does not fit."""
    if not note:
        return None
    cx, cy, r = COMPASS
    aspect = ax.bbox.width / ax.bbox.height
    taken = [(cx - r - 0.01, cy - r * aspect - 0.01, 2 * r + 0.02, 2 * r * aspect + 0.07),
             (SCALE_BAR[0] - 0.02, 0.0, 1 - SCALE_BAR[0] + 0.02, SCALE_BAR[1] + SCALE_BAR[3] + 0.04)]
    h = 0.012 * (len(_note_lines(note)) + 1)
    return _find(ax, 0.40, h, taken, "bottom-right") or _find(ax, 0.40, h, taken, "top-left")


def draw_note(ax, rect, note: str) -> None:
    ax.text(rect[0], rect[1] + rect[3], "\n".join(_note_lines(note)), transform=ax.transAxes, ha="left", va="top",
            fontsize=5.9, color="#333333", linespacing=1.3, zorder=22)


def scale_bar(ax, r=SCALE_BAR, km: int = 30, segments: int = 3) -> None:
    x0, y0, x1, y1 = frac_to_data(ax, r)
    lat = (y0 + y1) / 2
    deg = km / (111.32 * math.cos(math.radians(lat)))
    h = (y1 - y0) * 0.32
    by = y0 + (y1 - y0) * 0.55
    for i in range(segments):
        ax.add_patch(Rectangle((x0 + i * deg / segments, by), deg / segments, h,
                               facecolor="black" if i % 2 == 0 else "white", edgecolor="black", lw=0.6, zorder=25))
    for i in range(segments + 1):
        ax.text(x0 + i * deg / segments, by - h * 0.4, f"{int(i * km / segments)}", ha="center", va="top",
                fontsize=6.5, zorder=25)
    ax.text(x0 + deg * 1.04, by + h / 2, "km", ha="left", va="center", fontsize=6.5, zorder=25)


# ------------------------------------------------- farm recommendations ---

def _wrap_mm(text: str, width_mm: float, fs: float) -> list[str]:
    chars = max(10, int(width_mm / (fs * 0.3528 * 0.54)))
    return textwrap.wrap(text, chars)


def farm_block(fig, W: float, H: float, x: float, y0: float, y1: float, advice: dict[str, str]) -> float:
    """Draw 'Farm Recommendations' (rice, corn, HVC) between y0 and y1 (mm from the top). Returns the bottom y."""
    if not advice:
        return y0

    def ftxt(xx, yy, s, **kw):
        fig.text(xx / W, 1 - yy / H, s, **kw)

    ftxt(x + 2, y0, "FARM RECOMMENDATIONS", ha="left", va="top", fontsize=8.6, fontweight="bold", color="#0b532f")
    y = y0 + 5.2
    chip_w, gap = 12.5, 2.0
    text_w = 86 - chip_w - gap - 2
    avail = y1 - y
    # largest font that fits every crop
    # largest font that fits (bigger text when the legend is short, so the panel is not left empty)
    for fs in (9.0, 8.6, 8.2, 7.8, 7.4, 7.0, 6.7, 6.4, 6.1, 5.8, 5.5, 5.2):
        wrapped = {c: _wrap_mm(t, text_w, fs) for c, t in advice.items()}
        line_h = fs * 0.3528 * 1.32 * 1.18          # matplotlib line height = linespacing × font height
        need = sum(max(len(v), 1) * line_h + 3.0 for v in wrapped.values())
        if need <= avail:
            break
    else:
        max_lines = max(1, int((avail / len(advice) - 2.2) / line_h))
        wrapped = {c: (v[:max_lines - 1] + [v[max_lines - 1].rstrip(".,;") + "…"]) if len(v) > max_lines else v
                   for c, v in wrapped.items()}
    for crop, lines in wrapped.items():
        h = max(len(lines), 1) * line_h
        chip_h = max(4.6, min(h, fs * 0.3528 * 1.75))
        fig.add_artist(FancyBboxPatch(((x + 2) / W, 1 - (y + chip_h) / H), chip_w / W, chip_h / H,
                                      boxstyle="round,pad=0,rounding_size=0.004", transform=fig.transFigure,
                                      facecolor=CROP_COLORS.get(crop, "#555555"), edgecolor="none"))
        ftxt(x + 2 + chip_w / 2, y + chip_h / 2, LABELS.get(crop, crop).upper(), ha="center", va="center",
             fontsize=min(7.4, fs), fontweight="bold", color="white")
        ftxt(x + 2 + chip_w + gap, y - 0.3, "\n".join(lines), ha="left", va="top", fontsize=fs, color=INK,
             linespacing=1.32)
        y += max(h, chip_h) + 3.0
    return y


# ------------------------------------------------- standing crops overlay ---
# payload["crop_overlay"] = {"as_of": "2026-09-15", "crops": {"Rice": "#2e7d32", …}, "values": {area_key: {crop: ha}}}

CIRCLE_MAX_PT = 15.0          # radius of the largest circle (points)


@lru_cache(maxsize=1)
def _anchors() -> dict:
    from shapely.ops import polylabel
    muni, _ = reference.boundaries()
    out = {}
    for _, r in muni.iterrows():
        poly = max(getattr(r.geometry, "geoms", [r.geometry]), key=lambda g: g.area)
        try:
            pt = polylabel(poly, tolerance=poly.length / 500)
        except Exception:  # noqa: BLE001
            pt = poly.representative_point()
        out[r.area_key] = (pt.x, pt.y)
    return out


def overlay_max(ov: dict) -> float:
    crops = list(ov.get("crops") or {})
    return max([v.get(c, 0) or 0 for v in (ov.get("values") or {}).values() for c in crops] + [0])


def draw_crop_circles(ax, ov: dict) -> None:
    """Proportional circles (area ~ ha) per municipality and crop; bigger circles drawn first."""
    crops = ov.get("crops") or {}
    mx = overlay_max(ov)
    if not crops or mx <= 0:
        return
    pts = []
    anchors = _anchors()
    for key, vals in (ov.get("values") or {}).items():
        if key not in anchors:
            continue
        for crop, color in crops.items():
            ha = vals.get(crop) or 0
            if ha > 0:
                r = max(1.6, math.sqrt(ha / mx) * CIRCLE_MAX_PT)
                pts.append((r, anchors[key], color))
    pts.sort(key=lambda t: -t[0])
    if pts:
        ax.scatter([p[1][0] for p in pts], [p[1][1] for p in pts], s=[(2 * p[0]) ** 2 for p in pts],
                   c=[p[2] for p in pts], alpha=0.72, edgecolors="#222222", linewidths=0.5, zorder=4.5)


def crop_legend_height(ov: dict | None) -> float:
    if not ov or not ov.get("crops"):
        return 0.0
    return 7 + math.ceil(len(ov["crops"]) / 2) * 4.6 + 13


def draw_crop_legend(fig, W: float, H: float, x: float, y: float, ov: dict) -> float:
    """Crop colours + size key under the map legend. Returns the bottom y (mm)."""
    from matplotlib.lines import Line2D  # noqa: F401
    crops = ov.get("crops") or {}

    def ftxt(xx, yy, s, **kw):
        fig.text(xx / W, 1 - yy / H, s, **kw)

    as_of = ov.get("as_of", "")
    ftxt(x + 2, y, f"STANDING CROPS (ha){' – as of ' + as_of if as_of else ''}", ha="left", va="top", fontsize=7.6,
         fontweight="bold", color="#0b532f")
    y += 5
    for i, (crop, color) in enumerate(crops.items()):
        cx = x + 4 + (i % 2) * 44
        cy = y + (i // 2) * 4.6 + 1.8
        fig.patches.append(FancyBboxPatch(((cx - 1.5) / W, 1 - (cy + 1.5) / H), 3 / W, 3 / H,
                                          boxstyle="circle,pad=0", transform=fig.transFigure, facecolor=color,
                                          edgecolor="#222222", lw=0.4, alpha=0.85, figure=fig))
        ftxt(cx + 3, cy, crop, ha="left", va="center", fontsize=7)
    y += math.ceil(len(crops) / 2) * 4.6 + 2
    mx = overlay_max(ov)
    # size key: largest value and a quarter of it (circle area ∝ ha)
    for j, frac in enumerate((1.0, 0.25)):
        r_mm = math.sqrt(frac) * CIRCLE_MAX_PT * 0.3528
        cx = x + 6 + j * 30 + r_mm
        cy = y + CIRCLE_MAX_PT * 0.3528
        fig.patches.append(FancyBboxPatch(((cx - r_mm) / W, 1 - (cy + r_mm) / H), 2 * r_mm / W, 2 * r_mm / H,
                                          boxstyle="circle,pad=0", transform=fig.transFigure, facecolor="none",
                                          edgecolor="#333333", lw=0.6, figure=fig))
        ftxt(cx + r_mm + 1, cy, f"{mx * frac:,.0f} ha", ha="left", va="center", fontsize=6.4)
    return y + 2 * CIRCLE_MAX_PT * 0.3528 + 1


# ------------------------------------------------ recommendations (ENVI) ---

def recs_block(fig, W: float, H: float, x: float, y0: float, y1: float, text: str,
               title: str = "RECOMMENDED ACTIONS") -> float:
    """Recommendations under the legend (ENVI map). Headings bold, items wrapped; shrinks to fit, else truncates."""
    lines = [l.strip() for l in (text or "").replace("\r", "").split("\n") if l.strip()]
    if not lines or y1 - y0 < 20:
        return y0

    def ftxt(xx, yy, s, **kw):
        fig.text(xx / W, 1 - yy / H, s, **kw)

    ftxt(x + 2, y0, title, ha="left", va="top", fontsize=8.6, fontweight="bold", color="#0b532f")
    y = y0 + 5.2
    width = 84
    for fs in (7.4, 7.0, 6.6, 6.2, 5.9, 5.6, 5.3):
        line_h = fs * 0.3528 * 1.3 * 1.18
        blocks = []
        for l in lines:
            head = not re.match(r"^([-•]|\d+\.)", l)
            bullet = bool(re.match(r"^[-•]", l))
            body = re.sub(r"^[-•]\s*", "", l)
            blocks.append((head, _wrap_mm(body, width - (0 if head else 4), fs), bullet))
        need = sum(len(b) * line_h + (1.2 if h else 0.6) for h, b, _ in blocks)
        if need <= y1 - y:
            break
    for k, (head, wrapped, bullet) in enumerate(blocks):
        for i, part in enumerate(wrapped):
            if y + line_h > y1 - (line_h if k < len(blocks) - 1 else 0):
                ftxt(x + 2, y, "… full recommendations in the A4 poster", ha="left", va="top", fontsize=fs,
                     style="italic", color="#5f6368")
                return y + line_h
            ftxt(x + (2 if head else 6), y, part, ha="left", va="top", fontsize=fs, color=INK,
                 fontweight="bold" if head else "normal")
            if bullet and i == 0:
                ftxt(x + 3, y, "•", ha="left", va="top", fontsize=fs, color="#0b532f")
            y += line_h
        y += 1.2 if head else 0.6
    return y


def draw_crop_legend_in_map(ax, ov: dict) -> None:
    """Crop colours + size key drawn inside the map image (an empty corner), sized like the circles on the map."""
    crops = ov.get("crops") or {}
    mx = overlay_max(ov)
    if not crops or mx <= 0:
        return
    rows = math.ceil(len(crops) / 2)
    sub = f"as of {ov['as_of']}" if ov.get("as_of") else ""
    h = 0.035 + (0.022 if sub else 0) + rows * 0.032 + 0.075
    spot = _find(ax, 0.40, h, [], "bottom-right") or _find(ax, 0.40, h, [], "top-left") or (0.58, 0.02, 0.40, h)
    x0, y0, w, _ = spot
    t = ax.transAxes
    ax.add_patch(FancyBboxPatch((x0, y0), w, h, boxstyle="round,pad=0,rounding_size=0.01", transform=t,
                                facecolor=(1, 1, 1, 0.92), edgecolor="#555555", lw=0.6, zorder=30))
    top = y0 + h - 0.012
    ax.text(x0 + 0.015, top, "Standing crops (ha)", transform=t, ha="left", va="top", fontsize=7.6,
            fontweight="bold", color=INK, zorder=31)
    if sub:
        top -= 0.022
        ax.text(x0 + 0.015, top, sub, transform=t, ha="left", va="top", fontsize=6.8, style="italic",
                color="#555555", zorder=31)
    for i, (crop, color) in enumerate(crops.items()):
        cx = x0 + 0.03 + (i % 2) * w / 2
        cy = top - 0.036 - (i // 2) * 0.032
        ax.scatter([cx], [cy], s=80, c=[color], edgecolors="#222222", linewidths=0.5, transform=t, zorder=31)
        ax.text(cx + 0.022, cy, crop, transform=t, ha="left", va="center", fontsize=7.6, color=INK, zorder=31)
    ky = y0 + 0.042
    for j, frac in enumerate((1.0, 0.25)):
        r = math.sqrt(frac) * CIRCLE_MAX_PT
        kx = x0 + 0.065 + j * w / 2
        ax.scatter([kx], [ky], s=(2 * r) ** 2, facecolors="none", edgecolors="#333333", linewidths=0.6, transform=t,
                   zorder=31)
        ax.annotate(f"{mx * frac:,.0f} ha", (kx, ky), xycoords=t, xytext=(r + 3, 0), textcoords="offset points",
                    ha="left", va="center", fontsize=7.4, zorder=31)
