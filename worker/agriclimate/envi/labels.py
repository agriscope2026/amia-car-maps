"""Collision-free label placement for the matplotlib fallback renderer.

Same rules as the PyQGIS renderer:
  * every municipality gets a label; labels never overlap each other;
  * a label is placed inside its own polygon when it fits (nearest to the pole of inaccessibility);
  * otherwise it goes to the nearest free spot outside, joined to its area by a thin leader line;
  * province names are placed afterwards inside their province;
  * if a name cannot be placed at all, every municipality label is shrunk by 0.5 pt and the layout retried.
"""
from __future__ import annotations

import math

import matplotlib.patheffects as pe
from shapely.geometry import Point, box
from shapely.ops import polylabel

MUNI_HALO = [pe.withStroke(linewidth=1.6, foreground="black")]
PROV_HALO = [pe.withStroke(linewidth=2.5, foreground="#fafafa")]


class _Measure:
    """Text sizes in data units for one axes (cached)."""

    def __init__(self, ax):
        self.ax = ax
        fig = ax.figure
        ax.apply_aspect()
        self.renderer = fig.canvas.get_renderer()
        inv = ax.transData.inverted()
        (x0, y0), (x1, y1) = inv.transform([(0, 0), (1, 1)])
        self.dx, self.dy = abs(x1 - x0), abs(y1 - y0)   # data units per display pixel
        self.cache = {}

    def size(self, text, fontsize, weight="normal", pad_px=2.0):
        key = (text, fontsize, weight)
        if key not in self.cache:
            t = self.ax.text(0, 0, text, fontsize=fontsize, fontweight=weight)
            bb = t.get_window_extent(self.renderer)
            t.remove()
            self.cache[key] = ((bb.width + 2 * pad_px) * self.dx, (bb.height + 2 * pad_px) * self.dy)
        return self.cache[key]


def _free(b, taken):
    return all(not (b[0] < t[2] and t[0] < b[2] and b[1] < t[3] and t[1] < b[3]) for t in taken)


def _inside_candidates(geom, anchor, step):
    """Grid points inside the polygon, nearest to the anchor first."""
    minx, miny, maxx, maxy = geom.bounds
    pts = [anchor]
    nx = max(2, min(40, int((maxx - minx) / step)))
    ny = max(2, min(40, int((maxy - miny) / step)))
    for i in range(nx + 1):
        for j in range(ny + 1):
            p = Point(minx + (maxx - minx) * i / nx, miny + (maxy - miny) * j / ny)
            if geom.contains(p):
                pts.append(p)
    return sorted(pts, key=lambda p: p.distance(anchor))


def _try_place(geom, anchor, w, h, taken, outside=True):
    """Return ((cx, cy), inside) for the best free label box, or None."""
    step = h * 0.8
    for p in _inside_candidates(geom, anchor, step):
        b = (p.x - w / 2, p.y - h / 2, p.x + w / 2, p.y + h / 2)
        if _free(b, taken) and geom.intersection(box(*b)).area >= 0.8 * w * h:
            return (p.x, p.y), True
    if not outside:
        return None
    for ring in range(1, 16):
        r = ring * h
        for k in range(24):
            a = math.radians(k * 15)
            cx, cy = anchor.x + r * math.cos(a) * max(1.0, w / h / 2), anchor.y + r * math.sin(a)
            b = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
            if _free(b, taken):
                return (cx, cy), False
    return None


def place_labels(ax, areas, name_col, size, prov=None, prov_size=13, min_size=4.5, style=None, obstacles=None):
    """Draw non-overlapping labels on ``ax``. Returns a small report.

    ``style`` (optional) overrides the text look: muni_color, muni_halo (colour), muni_weight, prov_color,
    prov_halo, prov_weight, leader_color.
    """
    st = {"muni_color": "white", "muni_halo": "black", "muni_weight": "bold", "prov_color": "#323232",
          "prov_halo": "#fafafa", "prov_weight": "normal", "leader_color": "#444444", **(style or {})}
    muni_halo = [pe.withStroke(linewidth=1.6, foreground=st["muni_halo"])]
    prov_halo = [pe.withStroke(linewidth=2.5, foreground=st["prov_halo"])]
    m = _Measure(ax)
    items = []
    for _, r in areas.iterrows():
        g = r.geometry
        if g is None or g.is_empty:
            continue
        poly = max(getattr(g, "geoms", [g]), key=lambda x: x.area)
        try:
            anchor = polylabel(poly, tolerance=poly.length / 500)
        except Exception:  # noqa: BLE001
            anchor = poly.representative_point()
        items.append((str(r[name_col]), g, anchor, r.get("envi")))
    # hardest first: smallest areas, then higher ENVI
    items.sort(key=lambda it: (it[1].area, -(it[3] if it[3] == it[3] and it[3] is not None else 0)))

    fs = size
    while True:
        taken, placed, failed = list(obstacles or []), [], []
        for name, g, anchor, _ in items:
            w, h = m.size(name, fs, st["muni_weight"])
            res = _try_place(g, anchor, w, h, taken)
            if res is None:
                failed.append(name)
                continue
            (cx, cy), inside = res
            taken.append((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2))
            placed.append((name, cx, cy, inside, anchor, w, h))
        if not failed or fs - 0.5 < min_size:
            break
        fs -= 0.5

    prov_placed = []
    if prov is not None:
        for _, r in prov.iterrows():
            name = str(r.Pro_Name)
            res = None
            for s in (prov_size, prov_size * 0.85, prov_size * 0.7):   # shrink rather than drop the name
                w, h = m.size(name, s, st["prov_weight"], pad_px=3.0)
                res = _try_place(r.geometry, r.geometry.representative_point(), w, h, taken, outside=False)
                if res:
                    break
            if res:
                (cx, cy), _ = res
                taken.append((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2))
                prov_placed.append((name, cx, cy))
                ax.text(cx, cy, name, fontsize=s, color=st["prov_color"], ha="center", fontweight=st["prov_weight"],
                        va="center", alpha=0.95, path_effects=prov_halo, zorder=6)

    leaders = []
    for name, cx, cy, inside, anchor, w, h in placed:
        if not inside:
            # leader line from the box edge towards the area's anchor
            ex = min(max(anchor.x, cx - w / 2), cx + w / 2)
            ey = min(max(anchor.y, cy - h / 2), cy + h / 2)
            ax.plot([ex, anchor.x], [ey, anchor.y], color=st["leader_color"], lw=0.5, zorder=5)
            leaders.append(name)
        ax.text(cx, cy, name, fontsize=fs, fontweight=st["muni_weight"], color=st["muni_color"], ha="center",
                va="center", path_effects=muni_halo, zorder=7)
    return {"placed": len(placed) + len(prov_placed), "missing": failed, "leader_lines": sorted(leaders),
            "municipal_label_size_pt": fs, "overlaps": []}
