"""Print-ready maps in the DA-RFO-CAR layout of the official samples (``sample data/*_sample.jpg``).

Square page (300 × 300 mm):
  * left: map frame with zebra border, coordinate ticks (3 decimals) on all sides, compass north arrow,
    scale bar and CRS note; municipality and province names (dark text, white halo);
  * right: Bagong Pilipinas + DA logos, "Department of Agriculture" heading, the green title box
    ("10-day Rainfall Forecast" / "SEASONAL RAINFALL OUTLOOK" …, in millimeters (mm)), the big date
    ("September 24" / "September"), the validity and "as of" lines, the legend with range + category,
    the mm → litres note, the disclaimer and the "Maps from / Weather data from" credits with logos.

Labels use the prototype's collision-free engine (inside the polygon when it fits, otherwise outside with
a leader line, shrink in 0.5 pt steps). After saving, every label box is re-measured at 300 dpi and the
result is stored as a label report (placed / missing / overlaps).
"""
from __future__ import annotations

import json
import math
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patheffects as pe  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Ellipse, FancyBboxPatch, Polygon, Rectangle  # noqa: E402

from . import classes, reference  # noqa: E402
from .envi import config  # noqa: E402
from .envi.labels import place_labels  # noqa: E402
from . import mapinfo as info  # noqa: E402
from .envi.mapping import MM, _logo, _use_montserrat  # noqa: E402

_use_montserrat()
# the frame keeps a fixed data aspect by widening the extent; matplotlib reports that on every map
import logging  # noqa: E402

logging.getLogger("matplotlib.axes._base").setLevel(logging.ERROR)

DPI = 400          # print maps (the PDF is vector)
N_LABELS = reference.N_MUNICIPALITIES + reference.N_PROVINCES
GREEN = "#0b6237"
TITLE_GOLD = "#f6b40e"
DATE_GREEN = "#1b6b34"
PAGASA_LOGO = config.LOGO_DIR / "PAGASA_logo.png"     # optional: drop the official logo here to show it

DARK_LABELS = {"muni_color": "#1e1e1e", "muni_halo": "white", "muni_weight": "normal",
               "prov_color": "#141414", "prov_halo": "white", "prov_weight": "normal", "leader_color": "#333333"}

# map line styles and title box per product (from the sample layouts)
STYLES = {
    "rainfall_dekad": {"title": "10-day Rainfall\nForecast", "box_sub": "in millimeters (mm)",
                       "muni_edge": "#3c3c3c", "muni_lw": 0.4, "prov_edge": "#111111", "prov_lw": 1.7},
    "rainfall_seasonal": {"title": "SEASONAL\nRAINFALL\nOUTLOOK", "box_sub": "in millimeters (mm)",
                          "muni_edge": "#ffffff", "muni_lw": 0.5, "prov_edge": "#ffffff", "prov_lw": 2.6},
    "drought": {"title": "DROUGHT\nFORECAST", "box_sub": "PAGASA drought categories",
                "muni_edge": "#8a8a8a", "muni_lw": 0.35, "prov_edge": "#000000", "prov_lw": 1.8},
    "envi": {"title": "EL NIÑO\nVULNERABILITY\nINDEX", "box_sub": "ENVI classes (0–1)",
             "muni_edge": "#8a8a8a", "muni_lw": 0.35, "prov_edge": "#000000", "prov_lw": 1.6},
}
DEFAULT_STYLE = STYLES["drought"]


def _areas_for(layer: dict):
    muni, prov = reference.boundaries()
    vals = layer["values"]
    muni = muni.copy()
    muni["class_label"] = muni.area_key.map(lambda k: vals.get(k, {}).get("class", classes.NO_DATA))
    muni["class_color"] = muni.area_key.map(lambda k: vals.get(k, {}).get("color", classes.NO_DATA_COLOR))
    muni["value"] = muni.area_key.map(lambda k: vals.get(k, {}).get("value"))
    return muni, prov


def _draw(ax, muni, prov, label_size=6.0, prov_label_size=13, pad=0.04, style: dict | None = None,
          extent=None, label_style=None, reserve=None):
    """Choropleth + boundaries + collision-free labels. Returns (label report, label artists)."""
    st = style or DEFAULT_STYLE
    muni.plot(ax=ax, color=muni.class_color, edgecolor=st["muni_edge"], linewidth=st["muni_lw"], zorder=2)
    nod = muni[muni.class_label == classes.NO_DATA]
    if len(nod):
        nod.plot(ax=ax, facecolor="none", edgecolor="#777777", hatch="////", linewidth=0, zorder=2.5)
    prov.boundary.plot(ax=ax, color=st["prov_edge"], linewidth=st["prov_lw"], zorder=3)
    if st["prov_edge"].lower() in ("#ffffff", "white"):           # white boundaries need a dark region outline
        from shapely.ops import unary_union
        import geopandas as gpd
        gpd.GeoSeries([unary_union(list(prov.geometry))]).boundary.plot(ax=ax, color="#5a5a5a", linewidth=0.8,
                                                                         zorder=3.5)
    ax.set_axis_off()
    if extent:
        ax.set_xlim(extent[0], extent[2])
        ax.set_ylim(extent[1], extent[3])
        ax.set_aspect(1 / math.cos(math.radians(17.4)), adjustable="datalim")
    else:
        ax.set_aspect(1 / math.cos(math.radians(17.4)))
        minx, miny, maxx, maxy = prov.total_bounds
        padx = (maxx - minx) * pad
        ax.set_xlim(minx - padx, maxx + padx)
        ax.set_ylim(miny - (maxy - miny) * 0.01, maxy + (maxy - miny) * 0.01)
    before = set(map(id, ax.texts))
    obstacles = []
    if reserve is not None:
        ax.apply_aspect()
        obstacles = reserve(ax)            # data-coordinate boxes that labels must avoid
    rep = place_labels(ax, muni, "MunName2", label_size, prov, prov_label_size, style=label_style,
                       obstacles=obstacles)
    label_artists = [t for t in ax.texts if id(t) not in before]
    return rep, label_artists


def verify_labels(fig, label_artists) -> dict:
    """Measure label boxes at the export resolution: count placed names and pairwise overlaps."""
    fig.set_dpi(DPI)
    fig.canvas.draw()
    r = fig.canvas.get_renderer()
    boxes = [(t.get_text(), t.get_window_extent(r)) for t in label_artists]
    overlaps = [[a, b] for (i, (a, ba)), (b, bb) in
                ((x, y) for x in enumerate(boxes) for y in boxes[x[0] + 1:]) if ba.overlaps(bb)]
    return {"placed": len(boxes), "expected": N_LABELS, "overlaps": overlaps,
            "ok": len(boxes) == N_LABELS and not overlaps}


def _wrap(s: str, width: int) -> str:
    return "\n".join("\n".join(textwrap.wrap(p, width)) if p.strip() else "" for p in s.split("\n"))


def _num(v: float) -> str:
    return f"{v:g}"


def legend_rows(layer: dict) -> list[dict]:
    """Legend rows: range ("5 - 15", "400 +") and category ("Very Light Rain") when the legend has them."""
    lg = layer["legend"]
    rows = []
    for c in lg["classes"]:
        if lg["kind"] == "categorical" and c.get("lo") is not None and c.get("hi") is not None:
            rows.append({"label": c["label"], "range": f"{c['lo']:.2f} - {c['hi']:.2f}", "desc": c["label"],
                         "color": c["color"], "hatch": False})
        elif lg["kind"] == "graduated" and c.get("desc"):
            rng = f"{_num(c['lo'])} +" if c.get("hi") is None else f"{_num(c['lo'])} - {_num(c['hi'])}"
            rows.append({"label": c["label"], "range": rng, "desc": c["desc"], "color": c["color"], "hatch": False})
        else:
            unit = f" {lg['unit']}" if lg["kind"] == "graduated" and lg["unit"] == "mm" else ""
            rows.append({"label": c["label"] + unit, "range": c["label"] + unit, "desc": "", "color": c["color"],
                         "hatch": False})
    if lg["no_data"].get("count"):
        rows.append({"label": classes.NO_DATA, "range": classes.NO_DATA, "desc": "", "color": classes.NO_DATA_COLOR,
                     "hatch": True})
    return rows


# ------------------------------------------------------------ map frame ---

def _frame(ax, step=0.3, zebra=0.1):
    """Zebra border + coordinate ticks with 3 decimals on all four sides (as in the DA samples)."""
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    w = (x1 - x0) * 0.0075
    h = w / math.cos(math.radians(17.4))
    kw = dict(transform=ax.transData, zorder=20, clip_on=False, linewidth=0.4, edgecolor="black")
    # zebra segments along the four edges
    i = 0
    v = math.floor(x0 / zebra) * zebra
    while v < x1:
        a, b = max(v, x0), min(v + zebra, x1)
        col = "black" if i % 2 == 0 else "white"
        ax.add_patch(Rectangle((a, y1), b - a, h, facecolor=col, **kw))
        ax.add_patch(Rectangle((a, y0 - h), b - a, h, facecolor=col, **kw))
        v += zebra
        i += 1
    i = 0
    v = math.floor(y0 / zebra) * zebra
    while v < y1:
        a, b = max(v, y0), min(v + zebra, y1)
        col = "black" if i % 2 == 0 else "white"
        ax.add_patch(Rectangle((x0 - w, a), w, b - a, facecolor=col, **kw))
        ax.add_patch(Rectangle((x1, a), w, b - a, facecolor=col, **kw))
        v += zebra
        i += 1
    ax.add_patch(Rectangle((x0, y0), x1 - x0, y1 - y0, fill=False, lw=1.0, edgecolor="black", zorder=21,
                           clip_on=False))
    tk = dict(fontsize=6.5, color="#222222", zorder=22, clip_on=False)
    v = math.ceil(x0 / step - 1e-9) * step
    while v <= x1 + 1e-9:
        ax.text(v, y1 + h * 1.6, f"{v:.3f}", ha="center", va="bottom", **tk)
        ax.text(v, y0 - h * 1.6, f"{v:.3f}", ha="center", va="top", **tk)
        v += step
    v = math.ceil(y0 / step - 1e-9) * step
    while v <= y1 + 1e-9:
        ax.text(x0 - w * 1.6, v, f"{v:.3f}", ha="right", va="center", rotation=90, **tk)
        ax.text(x1 + w * 1.6, v, f"{v:.3f}", ha="left", va="center", rotation=270, **tk)
        v += step


def _compass(ax, x=0.22, y=0.84, r=0.055, *_):
    """Circle north arrow with a two-tone needle (as in the samples). Coordinates in axes fraction."""
    aspect = ax.bbox.width / ax.bbox.height
    ry = r * aspect
    t = ax.transAxes
    ax.add_patch(Ellipse((x, y), 2 * r, 2 * ry, transform=t, fill=False, lw=1.6, edgecolor="black", zorder=15))
    top, bottom = (x, y + ry * 1.35), (x, y - ry * 1.0)
    ax.add_patch(Polygon([top, (x - r * 0.42, y - ry * 0.55), bottom], closed=True, transform=t, facecolor="black",
                         edgecolor="black", lw=1, zorder=16))
    ax.add_patch(Polygon([top, (x + r * 0.42, y - ry * 0.55), bottom], closed=True, transform=t, facecolor="white",
                         edgecolor="black", lw=1, zorder=16))
    ax.text(x, y + ry * 1.45, "N", transform=t, ha="center", va="bottom", fontsize=15, fontweight="bold", zorder=16)


def map_extent(prov) -> tuple[float, float, float, float]:
    minx, miny, maxx, maxy = prov.total_bounds
    return (minx - 0.22, miny - 0.1, maxx + 0.25, maxy + 0.08)


# ------------------------------------------------------------- titles ---

def big_date(payload: dict, layer: dict) -> str:
    """'September 24' (daily), 'September' (month), 'Season Total', '10-day Total' …"""
    lid = layer["id"]
    if lid.startswith("d_"):
        return layer["label"]
    if lid.startswith("m_"):
        return layer["label"].split(" ")[0]
    return {"total": "10-day Total", "season_total": "Season Total", "pct_normal": "% of Normal"}.get(
        lid, payload["period"]["label"] if lid == "envi" else layer["label"])


def legend_title(payload: dict, layer: dict) -> tuple[str, str]:
    if layer["unit"] == "%":
        return "Legend (% of normal rainfall):", ""
    if layer["unit"] == "mm":
        t = payload.get("texts", {}).get("legend_title") or "Legend in millimeters (mm):"
        sub = {"m_": "(average rainfall)", "season_total": "(season total)", "total": "(10-day total)"}
        key = "m_" if layer["id"].startswith("m_") else layer["id"]
        return t, sub.get(key, "")
    return (payload.get("texts", {}).get("legend_title") or layer["legend"]["title"]) + ":", ""


def render_layer(payload: dict, layer: dict, out_dir: Path, stem: str) -> dict:
    """Render PNG (300 dpi) + vector PDF of one layer. Returns paths, label report and alt text."""
    out_dir.mkdir(parents=True, exist_ok=True)
    st = STYLES.get(payload["type"], DEFAULT_STYLE)
    muni, prov = _areas_for(layer)
    t = payload.get("texts", {})
    W = H = 300.0
    fig = plt.figure(figsize=(W * MM, H * MM), dpi=100)

    def rect(x, y, w, h):
        return [x / W, 1 - (y + h) / H, w / W, h / H]

    def ftxt(x, y, s, **kw):
        return fig.text(x / W, 1 - y / H, s, **kw)

    # ---- map ----
    ax = fig.add_axes(rect(14, 11, 182, 278))
    note = (t.get("notes") or "").strip()
    note = note if len(note) < 400 else ""
    spots: dict = {}

    def reserve(a):                       # the note goes in an empty spot of the frame; labels keep clear of it
        spots["note"] = info.plan_note(a, note)
        return [info.frac_to_data(a, spots["note"])] if spots["note"] else []

    rep_layout, label_artists = _draw(ax, muni, prov, label_size=6.2, prov_label_size=12.5, style=st,
                                      extent=map_extent(prov), label_style=DARK_LABELS, reserve=reserve)
    overlay = payload.get("crop_overlay")
    if overlay:
        info.draw_crop_circles(ax, overlay)
    _frame(ax)
    _compass(ax, *info.COMPASS)
    info.scale_bar(ax, info.SCALE_BAR)
    if spots.get("note"):
        info.draw_note(ax, spots["note"], note)
    ax.text(0.985, 0.012, "CRS: EPSG 4326 - WGS 84", transform=ax.transAxes, ha="right", va="bottom", fontsize=6.5,
            zorder=22)

    # ---- right panel ----
    cx = 251
    _logo(fig, config.LOGO_DIR / "Bagong_Pilipinas_logo.png", rect(214, 6, 36, 33))
    _logo(fig, config.LOGO_DIR / "DA CAR LOGO no background.png", rect(254, 4, 38, 36))
    ftxt(cx, 44, "Department of Agriculture", ha="center", va="top", fontsize=9.5, fontweight="bold")
    ftxt(cx, 49.5, "Cordillera Administrative Region\nAdaptation and Mitigation Initiative in Agriculture\n"
                   "(AMIA) Program", ha="center", va="top", fontsize=7, linespacing=1.35)
    fig.add_artist(plt.Line2D([207 / W, 295 / W], [1 - 66 / H] * 2, color="black", lw=0.8))
    title = st["title"]
    n_lines = title.count("\n") + 1
    tsize = {1: 27, 2: 25, 3: 22}.get(n_lines, 19)
    block = n_lines * tsize * 0.3528 * 1.08                  # title height in mm
    box_top, box_h = 69.0, 5 + block + 9
    fig.add_artist(FancyBboxPatch((207 / W, 1 - (box_top + box_h) / H), 88 / W, box_h / H,
                                  boxstyle="round,pad=0,rounding_size=0.008", transform=fig.transFigure,
                                  facecolor=GREEN, edgecolor="#0a3f24", lw=1.2))
    ftxt(cx, box_top + 4, title, ha="center", va="top", fontsize=tsize, fontweight="bold", color=TITLE_GOLD,
         linespacing=1.02)
    ftxt(cx, box_top + 5 + block + 1.5, st["box_sub"], ha="center", va="top", fontsize=7.5, color="white")
    top = box_top + box_h + 5                                  # everything below follows the box

    date = big_date(payload, layer)
    dsize = 27
    while dsize > 13 and len(date) * dsize * 0.62 * 0.3528 > 90:     # rough width in mm
        dsize -= 1
    ftxt(cx, top, date, ha="center", va="top", fontsize=dsize, fontweight="bold", color=DATE_GREEN)
    valid = payload.get("valid_text") or f"Valid for {payload['period']['label']}"
    ftxt(cx, top + 12.5, f"({valid})", ha="center", va="top", fontsize=7)
    ftxt(cx, top + 17, f"as of {payload_issued_label(payload)}", ha="center", va="top", fontsize=6.6, style="italic",
         color="#444444")

    lt, lsub = legend_title(payload, layer)
    ftxt(209, top + 25, lt, ha="left", va="top", fontsize=9.5, fontweight="bold")
    y = top + 31
    if lsub:
        ftxt(209, y - 0.5, lsub, ha="left", va="top", fontsize=7.5)
        y += 4.5
    rows = legend_rows(layer)
    from .products.crop_advice import advice_of
    advice = advice_of(payload)
    farm_h = 56 if advice else 0                  # room kept under the legend for the farm recommendations
    crop_h = info.crop_legend_height(overlay)
    if crop_h:
        farm_h = min(farm_h, 46)
    row_h = min(8.0, (250 - farm_h - crop_h - y) / max(1, len(rows)))
    sw_h = min(6.4, row_h - 1.4)
    has_desc = any(r["desc"] for r in rows)
    for r in rows:
        fig.add_artist(Rectangle((209 / W, 1 - (y + sw_h) / H), 13 / W, sw_h / H, transform=fig.transFigure,
                                 facecolor=r["color"], edgecolor="#4d4d4d", lw=0.6,
                                 hatch="////" if r["hatch"] else None))
        ftxt(225, y + sw_h / 2, r["range"], ha="left", va="center", fontsize=8)
        if has_desc and r["desc"]:
            ftxt(245, y + sw_h / 2, r["desc"], ha="left", va="center", fontsize=8)
        y += row_h
    if crop_h:
        y = info.draw_crop_legend(fig, W, H, 207, y + 3, overlay)
    if advice:
        info.farm_block(fig, W, H, 207, y + 3, 251, advice)
    elif payload["type"] == "envi":                    # ENVI: its recommended actions fill the panel
        info.recs_block(fig, W, H, 207, y + 5, 251, t.get("recommendations") or "")
    elif note and not spots.get("note"):
        ftxt(207, y + 3, _wrap("Note: " + note, 78), ha="left", va="top", fontsize=5.8, linespacing=1.3)
    fig.add_artist(plt.Line2D([207 / W, 295 / W], [1 - 254 / H] * 2, color="black", lw=0.8))
    ftxt(207, 256, "Disclaimer:\n" + _wrap(t.get("disclaimer") or "", 72), ha="left", va="top", fontsize=6.2,
         linespacing=1.3)
    credit = t.get("data_credit") or "DOST-PAGASA"
    first = "Data from" if payload["type"] == "envi" else "Weather data from"
    ftxt(207, 281, f"Maps from: DA-RFO-CAR AMIA\n{first}: {credit}", ha="left", va="center", fontsize=6.4,
         linespacing=1.35)
    _logo(fig, config.LOGO_DIR / "AMIA_Logo.png", rect(259, 273, 16, 16))
    if PAGASA_LOGO.exists():
        _logo(fig, PAGASA_LOGO, rect(277, 273, 16, 16))

    png, pdf = out_dir / f"{stem}.png", out_dir / f"{stem}.pdf"
    meta_title = f"{(t.get('title') or payload['title'])} – {layer['label']}"
    fig.savefig(png, dpi=DPI, metadata={"Title": meta_title})
    report = verify_labels(fig, label_artists)
    report.update({"municipal_label_size_pt": rep_layout["municipal_label_size_pt"],
                   "leader_lines": rep_layout["leader_lines"], "missing": rep_layout["missing"]})
    fig.savefig(pdf, metadata={"Title": meta_title, "Author": "DA-RFO-CAR AMIA"})
    plt.close(fig)
    return {"png": png, "pdf": pdf, "label_report": report, "alt": alt_text(payload, layer)}


def payload_issued_label(payload: dict) -> str:
    from .products.common import fmt_day, to_date
    try:
        return fmt_day(to_date(payload["issued"]))
    except Exception:  # noqa: BLE001
        return str(payload.get("issued", ""))


def alt_text(payload: dict, layer: dict) -> str:
    """Accessible description of an exported map."""
    lg = layer["legend"]
    parts = [f"{c['label']}{' (' + c['desc'] + ')' if c.get('desc') else ''}: {c.get('count', 0)} municipalities"
             for c in lg["classes"] if c.get("count")]
    if lg["no_data"].get("count"):
        parts.append(f"no data: {lg['no_data']['count']}")
    unit = " (mm)" if layer["unit"] == "mm" else ""
    return (f"Map of the Cordillera Administrative Region showing {payload['title'].replace(' – CAR', '')}{unit}, "
            f"{layer['label']}, by municipality. " + "; ".join(parts) + ".")


def write_label_reports(reports: dict, path: Path) -> Path:
    path.write_text(json.dumps(reports, indent=1, ensure_ascii=False), encoding="utf-8")
    return path


__all__ = ["render_layer", "legend_rows", "alt_text", "payload_issued_label", "pe"]
