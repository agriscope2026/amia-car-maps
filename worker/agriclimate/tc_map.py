"""Tropical cyclone track map for the Special Farm Weather Outlook, in the style of PAGASA's track map: the forecast
track with the category at each position, the forecast cone, the strong-wind (yellow) and storm-force (red) circles,
PAGASA's area of responsibility – and CAR (our municipal boundaries) coloured by wind signal, with a zoomed inset.

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
# colours as on PAGASA's track maps
SEA, LAND_FILL, LAND_EDGE = "#bee8ff", "#ffeabe", "#9c8f72"
TRACK, WINDS_FILL, WINDS_EDGE = "#111111", "#ffe600", "#c9a800"
STORM_FILL, STORM_EDGE = "#d0453a", "#9e2a20"
CONE_FILL, CONE_EDGE = "#8f9aa3", "#5f6b73"
HALO = [pe.withStroke(linewidth=3, foreground="white")]
HALO_BIG = [pe.withStroke(linewidth=3.5, foreground="white")]


def _short_time(t: str) -> str:
    from .pagasa_tc import short_time
    return short_time(t)


def _extent(tc: dict, aspect: float) -> tuple[float, float, float, float]:
    """Bounds covering the track, the strong-wind circle, PAR and CAR, widened to the panel's aspect (width / height)."""
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


def _feature(feats: list, *kinds: str):
    return next((f for f in feats if f["properties"]["kind"] in kinds), None)


def _inset(fig, ax, payload: dict, extent, feats: list, size_in):
    """CAR, zoomed, coloured by wind signal, in the map corner farthest from the storm."""
    import geopandas as gpd
    from shapely.ops import unary_union
    x0, x1, y0, y1 = extent
    w_in, h_in = size_in
    fw = 0.27
    fh = min(0.62, fw * w_in / 0.57 / h_in)
    pad = 0.012
    pts = [f["geometry"]["coordinates"] for f in feats if f["properties"]["kind"] in ("now", "forecast")]
    frac = [((x - x0) / (x1 - x0), (y - y0) / (y1 - y0)) for x, y in pts]
    corners = {(pad, pad): (pad + fw / 2, pad + fh / 2), (1 - fw - pad, pad): (1 - pad - fw / 2, pad + fh / 2),
               (pad, 1 - fh - pad): (pad + fw / 2, 1 - pad - fh / 2),
               (1 - fw - pad, 1 - fh - pad): (1 - pad - fw / 2, 1 - pad - fh / 2)}
    # the corner whose box is farthest from the storm positions; CAR itself must stay visible
    car_f = ((121.0 - x0) / (x1 - x0), (17.35 - y0) / (y1 - y0))

    def score(item):
        (lx, ly), (cx, cy) = item
        inside_car = lx <= car_f[0] <= lx + fw and ly <= car_f[1] <= ly + fh
        return (not inside_car, min((math.hypot(px - cx, py - cy) for px, py in frac), default=1))
    (lx, ly), _ = max(corners.items(), key=score)
    ia = fig.add_axes([lx, ly, fw, fh])
    ia.set_facecolor("white")
    muni, prov = reference.boundaries()
    vals = payload["layers"][0]["values"]
    muni = muni.copy()
    muni["c"] = muni.area_key.map(lambda k: vals.get(k, {}).get("color", "#eeeeee"))
    muni.plot(ax=ia, color=muni.c, edgecolor="#8a8a8a", linewidth=0.2)
    prov.boundary.plot(ax=ia, color="#3a3a3a", linewidth=0.6)
    gpd.GeoSeries([unary_union(list(prov.geometry))], crs=prov.crs).boundary.plot(ax=ia, color="#0b6237", linewidth=1.2)
    for _, r in prov.iterrows():
        c = r.geometry.representative_point()
        ia.text(c.x, c.y, reference.province_display(r["area_key"]).replace("Mountain Province", "Mt. Province"),
                fontsize=6.3, fontweight="bold", ha="center", va="center", color="#202020", path_effects=HALO)
    bx0, by0, bx1, by1 = prov.total_bounds
    k = math.cos(math.radians((by0 + by1) / 2))
    ia.set_aspect(1 / k)
    # fill the inset box: widen the shorter side
    bw, bh = (bx1 - bx0) * k, by1 - by0
    box = fw * w_in / (fh * h_in)
    if bw / bh < box:
        add = (bh * box - bw) / k / 2
        bx0, bx1 = bx0 - add, bx1 + add
    else:
        add = (bw / box - bh) / 2
        by0, by1 = by0 - add, by1 + add
    m = 0.06 * (by1 - by0)
    ia.set_xlim(bx0 - m, bx1 + m)
    ia.set_ylim(by0 - m, by1 + m)
    ia.set_xticks([])
    ia.set_yticks([])
    for sp in ia.spines.values():
        sp.set_edgecolor("#0b6237")
        sp.set_linewidth(1.4)
    ia.text(0.03, 0.985, "CAR – wind signals", transform=ia.transAxes, fontsize=7.5, fontweight="bold", color="#0b6237",
            ha="left", va="top", path_effects=HALO)
    # a line from CAR on the main map to the inset
    from matplotlib.patches import ConnectionPatch
    side = 1 if lx < 0.5 else 0
    fig.add_artist(ConnectionPatch(xyA=(121.0, 17.4), coordsA=ax.transData, xyB=(side, 0.5), coordsB=ia.transAxes,
                                   color="#0b6237", lw=1.1, zorder=8))


def render(payload: dict, path: Path, size_in: tuple[float, float] = (8, 6.5), dpi: int = 300, legend: bool = True,
           inset: bool = False) -> Path:
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
        if y0 + (y1 - y0) * 0.06 < lat < y1 - (y1 - y0) * 0.03:            # right edge: the legend is bottom left
            ax.text(x1 - (x1 - x0) * 0.008, lat, f"{lat}°N", fontsize=7.5, color="#4f6577", ha="right", va="bottom", zorder=6,
                    path_effects=HALO)
    # PAR
    px, py = zip(*PAR)
    ax.plot(px, py, color="#37474f", lw=1.0, ls=(0, (6, 4)), zorder=2)
    ax.text(134.8, 24.75, "PAR", fontsize=9, fontweight="bold", color="#37474f", ha="right", va="top", zorder=6, path_effects=HALO)
    # like PAGASA: the area with at least strong winds around the present centre (yellow)
    feats = (tc.get("track_geojson") or {}).get("features", [])

    def area(f, fill, edge, alpha, z):
        g = gpd.GeoSeries([shape(f["geometry"])], crs="EPSG:4326")
        g.plot(ax=ax, color=fill, alpha=alpha, zorder=z)
        b = g.iloc[0].boundary
        for part in getattr(b, "geoms", [b]):
            bx, by = part.xy
            ax.plot(bx, by, color=edge, lw=1.0, zorder=z + 0.05)
    cone = _feature(feats, "cone")
    if cone:
        area(cone, CONE_FILL, CONE_EDGE, 0.28, 2.1)
    circ = _feature(feats, "strong_winds", "buffer")
    if circ:
        area(circ, WINDS_FILL, WINDS_EDGE, 0.38, 2.2)
    storm = _feature(feats, "storm_force")
    if storm:
        area(storm, STORM_FILL, STORM_EDGE, 0.42, 2.3)
    # CAR: municipalities by wind signal, region outline
    muni, prov = reference.boundaries()
    vals = payload["layers"][0]["values"]
    muni = muni.copy()
    muni["c"] = muni.area_key.map(lambda k: vals.get(k, {}).get("color", "#e0e0e0"))
    muni.plot(ax=ax, color=muni.c, edgecolor="#7a7a7a", linewidth=0.15, zorder=3)
    from shapely.ops import unary_union
    car = gpd.GeoSeries([unary_union(list(prov.geometry))], crs=prov.crs)
    car.boundary.plot(ax=ax, color="#0b6237", lw=1.6, zorder=3.2)
    if inset:
        _inset(fig, ax, payload, (x0, x1, y0, y1), feats, size_in)
    cx, cy = 121.0, 17.35
    if not inset:
        ax.annotate("CAR", (cx - 0.5, cy - 0.4), xytext=(cx - (x1 - x0) * 0.1, cy - (y1 - y0) * 0.09), fontsize=11, fontweight="bold",
                    color="#0b6237", ha="center", path_effects=HALO, zorder=7,
                    arrowprops={"arrowstyle": "-", "color": "#0b6237", "lw": 1})
    # track: present position, then the forecast positions
    line = next((f for f in feats if f["properties"]["kind"] == "track"), None)
    if line:
        lx, ly = zip(*line["geometry"]["coordinates"])
        ax.plot(lx, ly, color=TRACK, lw=2.0, zorder=4, solid_capstyle="round")
    # positions as PAGASA marks them: a black disc with the category (TD, TS, STS, TY, STY), the date beside it
    def marker(x, y, cat, size, outside=False):
        ax.scatter([x], [y], s=size, color="white" if outside else TRACK, edgecolor=TRACK, linewidth=1.3, zorder=5)
        ax.text(x, y, cat, fontsize=5.6 if len(cat) > 2 else 6.4, fontweight="bold", color=TRACK if outside else "white",
                ha="center", va="center", zorder=5.5)
    now = next((f for f in feats if f["properties"]["kind"] == "now"), None)
    if now:
        nx, ny = now["geometry"]["coordinates"]
        marker(nx, ny, now["properties"].get("cat") or "", 330)
        name = (tc.get("name") or "").title()
        ax.text(nx + (x1 - x0) * 0.022, ny - (y1 - y0) * 0.022, f"{name} now" if name else "Now", fontsize=10.5,
                fontweight="bold", color=TRACK, ha="left", va="top", path_effects=HALO, zorder=6)
    for i, f in enumerate(p for p in feats if p["properties"]["kind"] == "forecast"):
        fx, fy = f["geometry"]["coordinates"]
        outside = fy > 25 or fx > 135 or fx < 115
        marker(fx, fy, f["properties"]["cat"], 250, outside)
        # dates on alternate sides of the track, so that close positions do not cover each other
        left = i % 2 == 0
        ax.text(fx + (x1 - x0) * (-0.022 if left else 0.022), fy, _short_time(f["properties"].get("time") or ""),
                fontsize=8.5, fontweight="bold", color="#1a1a1a", ha="right" if left else "left", va="center",
                path_effects=HALO_BIG, zorder=6)
    # closest approach to CAR
    d = (payload.get("summary") or {}).get("car_distance") or {}
    if d.get("closest_km") is not None:
        txt = f"Closest to CAR: about {d['closest_km']:,} km\n({_short_time(d.get('closest_time') or '')})"
        ax.text(x1 - (x1 - x0) * 0.02, y0 + (y1 - y0) * 0.04, txt, fontsize=8.5, fontweight="bold", ha="right", va="bottom", zorder=7,
                bbox={"boxstyle": "round,pad=0.4", "fc": "white", "ec": "#b0b0b0", "lw": 0.6})
    if legend:
        km = tc.get("wind_extent_km")
        items = [Line2D([], [], color=TRACK, lw=1.5, marker="o", markersize=7, label="Forecast track and positions (PAGASA)"),
                 Line2D([], [], color=TRACK, lw=0, marker="o", markerfacecolor="white", markersize=6, label="Outside PAR")]
        if km:
            items.append(Patch(facecolor=WINDS_FILL, alpha=0.5, edgecolor=WINDS_EDGE,
                               label=f"Area with strong winds or higher (up to {km:,.0f} km)"))
        if tc.get("storm_force_km"):
            items.append(Patch(facecolor=STORM_FILL, alpha=0.5, edgecolor=STORM_EDGE,
                               label=f"Area with storm-force winds or higher (up to {tc['storm_force_km']:,.0f} km)"))
        if cone:
            items.append(Patch(facecolor=CONE_FILL, alpha=0.4, edgecolor=CONE_EDGE, label="Forecast cone (approximate)"))
        items.append(Line2D([], [], color="#37474f", lw=1, ls="--", label="Philippine Area of Responsibility"))
        # lower left: open sea west of Mindanao, clear of the track (which runs north-west)
        ax.legend(handles=items, loc="lower left", fontsize=8.5, frameon=True, framealpha=0.92, borderpad=0.6,
                  bbox_to_anchor=(0.01, 0.01))
    ax.set_xlim(x0, x1)
    ax.set_ylim(y0, y1)
    ax.set_aspect(1 / math.cos(math.radians((y0 + y1) / 2)))
    ax.set_axis_off()
    fig.savefig(path, dpi=dpi, facecolor=SEA)
    plt.close(fig)
    gc.collect()
    return path
