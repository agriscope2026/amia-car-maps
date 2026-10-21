"""Tropical cyclone track map for the Special Farm Weather Outlook: the forecast track (PAGASA bulletin), its buffer
(the extent of the strong winds along the track), PAGASA's area of responsibility and CAR with its wind signals.

Land: Natural Earth 1:50m admin-0 countries (public domain), clipped to 100–160°E, 2°S–42°N
(``data/gis/ne_countries_region.geojson``).
"""
from __future__ import annotations

import gc
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.patheffects as pe  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

from . import reference  # noqa: E402
from .envi import config  # noqa: E402
from .envi.mapping import _use_montserrat  # noqa: E402

_use_montserrat()
LAND = config.ROOT / "data" / "gis" / "ne_countries_region.geojson"
# Philippine Area of Responsibility (PAGASA)
PAR = [(120, 25), (135, 25), (135, 5), (115, 5), (115, 15), (120, 21), (120, 25)]
SEA, LAND_FILL, LAND_EDGE = "#d6eaf6", "#f4f0e6", "#8f8f82"
TRACK, BUFFER_FILL, BUFFER_EDGE = "#b71c1c", "#ff9800", "#e65100"
HALO = [pe.withStroke(linewidth=3, foreground="white")]
HALO_BIG = [pe.withStroke(linewidth=3.5, foreground="white")]


def _short_time(t: str) -> str:
    from .pagasa_tc import short_time
    return short_time(t)


def _extent(tc: dict, aspect: float) -> tuple[float, float, float, float]:
    """Bounds covering the track, its buffer and CAR, widened to the panel's aspect (width / height)."""
    from shapely.geometry import shape
    xs, ys = [120.3, 121.8], [16.1, 18.6]                   # CAR
    feats = (tc.get("track_geojson") or {}).get("features", [])
    for f in feats:
        b = shape(f["geometry"]).bounds
        xs += [b[0], b[2]]
        ys += [b[1], b[3]]
    x0, x1, y0, y1 = min(xs) - 1.2, max(xs) + 1.2, min(ys) - 1.2, max(ys) + 1.2
    x0, x1 = max(x0, 101), min(x1, 159)
    y0, y1 = max(y0, -1), min(y1, 41)
    k = math.cos(math.radians((y0 + y1) / 2))
    w, h = (x1 - x0) * k, y1 - y0
    if w / h < aspect:                                      # too tall: widen
        add = (h * aspect - w) / k / 2
        x0, x1 = x0 - add, x1 + add
    else:                                                   # too wide: heighten
        add = (w / aspect - h) / 2
        y0, y1 = y0 - add, y1 + add
    return x0, x1, y0, y1


def render(payload: dict, path: Path, size_in: tuple[float, float] = (8, 6.5), dpi: int = 300, legend: bool = True) -> Path:
    import geopandas as gpd
    from shapely.geometry import shape
    tc = payload.get("tc") or {}
    w_in, h_in = size_in
    x0, x1, y0, y1 = _extent(tc, w_in / h_in)
    fig = plt.figure(figsize=size_in, dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor(SEA)
    land = gpd.read_file(LAND)
    land.plot(ax=ax, color=LAND_FILL, edgecolor=LAND_EDGE, linewidth=0.5, zorder=1)
    # graticule
    step = 5 if (x1 - x0) > 14 else 2
    for lon in range(int(math.floor(x0 / step) * step), int(x1) + 1, step):
        ax.axvline(lon, color="#9fb7c7", lw=0.4, zorder=1.5)
        if x0 + (x1 - x0) * 0.05 < lon < x1 - (x1 - x0) * 0.12:           # clear of the corners and the distance box
            ax.text(lon, y0 + (y1 - y0) * 0.012, f"{lon}°E", fontsize=7.5, color="#4f6577", ha="center", va="bottom", zorder=6,
                    path_effects=HALO)
    for lat in range(int(math.floor(y0 / step) * step), int(y1) + 1, step):
        ax.axhline(lat, color="#9fb7c7", lw=0.4, zorder=1.5)
        if y0 + (y1 - y0) * 0.06 < lat < y1 - (y1 - y0) * 0.03:            # right edge: the legend is top left
            ax.text(x1 - (x1 - x0) * 0.008, lat, f"{lat}°N", fontsize=7.5, color="#4f6577", ha="right", va="bottom", zorder=6,
                    path_effects=HALO)
    # PAR
    px, py = zip(*PAR)
    ax.plot(px, py, color="#37474f", lw=1.0, ls=(0, (6, 4)), zorder=2)
    ax.text(134.8, 24.75, "PAR", fontsize=9, fontweight="bold", color="#37474f", ha="right", va="top", zorder=6, path_effects=HALO)
    # buffer (extent of the strong winds along the track)
    feats = (tc.get("track_geojson") or {}).get("features", [])
    buf = next((f for f in feats if f["properties"]["kind"] == "buffer"), None)
    if buf:
        g = gpd.GeoSeries([shape(buf["geometry"])], crs="EPSG:4326")
        g.plot(ax=ax, color=BUFFER_FILL, alpha=0.2, zorder=2.2)
        edge = g.iloc[0].boundary
        for part in getattr(edge, "geoms", [edge]):
            bx, by = part.xy
            ax.plot(bx, by, color=BUFFER_EDGE, lw=1.0, ls=(0, (4, 3)), zorder=2.3)
    # CAR: municipalities by wind signal, region outline
    muni, prov = reference.boundaries()
    vals = payload["layers"][0]["values"]
    muni = muni.copy()
    muni["c"] = muni.area_key.map(lambda k: vals.get(k, {}).get("color", "#e0e0e0"))
    muni.plot(ax=ax, color=muni.c, edgecolor="#7a7a7a", linewidth=0.15, zorder=3)
    from shapely.ops import unary_union
    car = gpd.GeoSeries([unary_union(list(prov.geometry))], crs=prov.crs)
    car.boundary.plot(ax=ax, color="#0b6237", lw=1.6, zorder=3.2)
    cx, cy = 121.0, 17.35
    ax.annotate("CAR", (cx - 0.5, cy - 0.4), xytext=(cx - (x1 - x0) * 0.1, cy - (y1 - y0) * 0.09), fontsize=11, fontweight="bold",
                color="#0b6237", ha="center", path_effects=HALO, zorder=7,
                arrowprops={"arrowstyle": "-", "color": "#0b6237", "lw": 1})
    # track: present position, then the forecast positions
    line = next((f for f in feats if f["properties"]["kind"] == "track"), None)
    if line:
        lx, ly = zip(*line["geometry"]["coordinates"])
        ax.plot(lx, ly, color=TRACK, lw=2.0, zorder=4, solid_capstyle="round")
    now = next((f for f in feats if f["properties"]["kind"] == "now"), None)
    if now:
        nx, ny = now["geometry"]["coordinates"]
        ax.scatter([nx], [ny], s=460, color="none", edgecolor=TRACK, linewidth=1.4, zorder=5)    # storm centre: ring + dot
        ax.scatter([nx], [ny], s=170, color=TRACK, edgecolor="white", linewidth=1.5, zorder=5.2)
        name = (tc.get("name") or "").title()
        ax.text(nx + (x1 - x0) * 0.02, ny - (y1 - y0) * 0.02, f"{name} now" if name else "Now", fontsize=10.5,
                fontweight="bold", color=TRACK, ha="left", va="top", path_effects=HALO, zorder=6)
    for i, f in enumerate(p for p in feats if p["properties"]["kind"] == "forecast"):
        fx, fy = f["geometry"]["coordinates"]
        outside = fy > 25 or fx > 135 or fx < 115
        ax.scatter([fx], [fy], s=75, color="white" if outside else TRACK, edgecolor=TRACK, linewidth=1.2, zorder=5)
        # dates on alternate sides of the track, so that close positions do not cover each other
        left = i % 2 == 0
        ax.text(fx + (x1 - x0) * (-0.016 if left else 0.016), fy,
                f"{_short_time(f['properties'].get('time') or '')} ({f['properties']['cat']})",
                fontsize=8.5, fontweight="bold", color="#3a0d0d", ha="right" if left else "left", va="center",
                path_effects=HALO_BIG, zorder=6)
    # closest approach to CAR
    d = (payload.get("summary") or {}).get("car_distance") or {}
    if d.get("closest_km") is not None:
        txt = f"Closest to CAR: about {d['closest_km']:,} km\n({_short_time(d.get('closest_time') or '')})"
        ax.text(x1 - (x1 - x0) * 0.02, y0 + (y1 - y0) * 0.04, txt, fontsize=8.5, fontweight="bold", ha="right", va="bottom", zorder=7,
                bbox={"boxstyle": "round,pad=0.4", "fc": "white", "ec": "#b0b0b0", "lw": 0.6})
    if legend:
        km = tc.get("wind_extent_km")
        items = [Line2D([], [], color=TRACK, lw=0, marker="o", markersize=8, markeredgecolor="white", label="Storm centre now"),
                 Line2D([], [], color=TRACK, lw=2, marker="o", markersize=5, label="Forecast track (PAGASA)"),
                 Line2D([], [], color=TRACK, lw=0, marker="o", markerfacecolor="white", markersize=5, label="Outside PAR")]
        if km:
            items.append(Patch(facecolor=BUFFER_FILL, alpha=0.35, edgecolor=BUFFER_EDGE, ls="--",
                               label=f"Strong winds or higher: {km:,.0f} km of the track"))
        items.append(Line2D([], [], color="#37474f", lw=1, ls="--", label="Philippine Area of Responsibility"))
        ax.legend(handles=items, loc="upper left", fontsize=8.5, frameon=True, framealpha=0.92, borderpad=0.6,
                  bbox_to_anchor=(0.01, 0.99))
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect(1 / math.cos(math.radians((y0 + y1) / 2)))
    ax.set_axis_off()
    fig.savefig(path, dpi=dpi, facecolor=SEA)
    plt.close(fig)
    gc.collect()
    return path
