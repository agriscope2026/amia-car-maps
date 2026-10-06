"""Join ENVI results to the CAR boundaries and render the map.

Preferred renderer: headless PyQGIS (envi/qgis_render.py, run with QGIS's own python) using the
GIS template project + print layout. Fallback: geopandas + matplotlib reproducing the template
layout (map left, title/legend/notes panel right, north arrow, scale bar, labels, logos).
"""
from __future__ import annotations

import json
import math
import subprocess
import textwrap
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from . import config  # noqa: E402
from .io_loader import PROVINCE_DISPLAY, clean_name  # noqa: E402
from .labels import place_labels  # noqa: E402


def _use_montserrat():
    """Register the bundled Montserrat fonts with matplotlib and make them the default."""
    from matplotlib import font_manager
    for f in sorted(config.FONT_DIR.glob("Montserrat-*.ttf")):
        font_manager.fontManager.addfont(str(f))
    matplotlib.rcParams["font.family"] = config.FONT_FAMILY


_use_montserrat()

RESULT_FIELDS = ["area_key", "area", "province_label", "rank", "envi", "envi_class", "class_color",
                 "hazard_raw", "damage_raw", "crops_raw", "hazard_norm", "damage_norm", "crops_norm",
                 "missing_indicators"]


# ------------------------------------------------------------------- data ---

def load_boundaries() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    muni = gpd.read_file(config.MUNI_SHP)
    muni["area_key"] = muni.Pro_Name.map(clean_name) + "|" + muni.Mun_Name.map(clean_name)
    prov = gpd.read_file(config.PROV_SHP)
    prov["area_key"] = prov.Pro_Name.map(clean_name)
    prov["Pro_Name"] = prov.area_key.map(PROVINCE_DISPLAY).fillna(prov.Pro_Name)
    return muni, prov


def join_results(df: pd.DataFrame, level: str) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Return (areas with ENVI attributes, provinces). Areas without results get class 'No data'."""
    muni, prov = load_boundaries()
    cols = [c for c in RESULT_FIELDS if c in df.columns]
    if level == "municipal":
        areas = muni.merge(df[cols], on="area_key", how="left")
        prov_out = prov
    else:
        areas = prov.merge(df[cols], on="area_key", how="left")
        prov_out = areas
    areas["envi_class"] = areas["envi_class"].fillna(config.NO_DATA_LABEL)
    areas.loc[areas.envi.isna(), "envi_class"] = config.NO_DATA_LABEL
    areas["class_color"] = areas.envi_class.map({**config.CLASS_COLORS, config.NO_DATA_LABEL: config.NO_DATA_COLOR})
    if "area" in areas:
        fallback = areas.Mun_Name if "Mun_Name" in areas else areas.Pro_Name
        areas["area"] = areas["area"].fillna(fallback.str.replace(r"\s*\(.*\)\s*$", "", regex=True))
    if "rank" in areas:
        areas["rank"] = areas["rank"].astype("float")
    return areas, prov_out


def write_gpkg(areas: gpd.GeoDataFrame, prov: gpd.GeoDataFrame, path: Path, level: str) -> Path:
    path.unlink(missing_ok=True)
    muni_layer = areas if level == "municipal" else load_boundaries()[0]
    muni_layer.to_file(path, layer="municipalities", driver="GPKG")
    prov.to_file(path, layer="provinces", driver="GPKG")
    return path


def to_geojson(areas: gpd.GeoDataFrame, prov: gpd.GeoDataFrame, tolerance: float = 0.0004) -> dict:
    """Simplified GeoJSON for the Leaflet preview (areas + province outlines)."""
    keep = [c for c in RESULT_FIELDS if c in areas.columns]
    a = areas[keep + ["geometry"]].copy()
    a["geometry"] = a.geometry.simplify(tolerance, preserve_topology=True)
    p = prov[["Pro_Name", "geometry"]].copy()
    p["geometry"] = p.geometry.simplify(tolerance, preserve_topology=True)
    return {"areas": json.loads(a.to_json(na="null")), "provinces": json.loads(p.to_json())}


# --------------------------------------------------------------- rendering ---

def texts(meta: dict) -> dict:
    w = meta["weights"]
    lab = meta.get("labels") or config.period_labels()
    meth = {"equal": "equal intervals", "quantile": "quantiles", "jenks": "natural breaks (Jenks)"}[meta["classification"]]
    return {
        "title": config.MAP_TITLE,
        "subtitle": lab["subtitle"],
        "period": f"Outlook: {lab['period']}",
        "issued": f"(as of {lab['issued']})",
        "legend_title": "LEGEND",
        "note": ("Note: ENVI = weighted sum of min–max normalized indicators – drought forecast "
                 f"({w['hazard']:.2f}), historical El Niño damage ({w['damage']:.2f}) and standing crops "
                 f"({w['crops']:.2f}); higher = more vulnerable. Classes: {meth}."),
        "source_short": "Data: DOST-PAGASA; DA-RFO-CAR\nMap: DA-RFO-CAR AMIA",
        "disclaimer": ("Disclaimer:\nDA RFO CAR is not liable for any loss or damage arising from the use of this "
                       "vulnerability index. The index is valid only for the outlook period and areas stated."),
        "source": ("Data sources: DOST-PAGASA drought forecast; DA-RFO-CAR historical damage & standing crops "
                   f"(as of {lab['crops_as_of']}).\nMap: DA-RFO-CAR AMIA"),
    }


def render(df: pd.DataFrame, meta: dict, out_dir: Path, settings: dict, log=print) -> dict:
    """Render map PNG (300 dpi), PDF and a transparent map-only PNG. Returns paths + renderer used."""
    out_dir.mkdir(parents=True, exist_ok=True)
    areas, prov = join_results(df, meta["level"])
    gpkg = write_gpkg(areas, prov, out_dir / "envi_results.gpkg", meta["level"])
    outs = {"png": out_dir / "envi_map.png", "pdf": out_dir / "envi_map.pdf",
            "map_only": out_dir / "envi_map_only.png", "gpkg": gpkg}
    has_nodata = bool((areas.envi_class == config.NO_DATA_LABEL).any())
    legend = meta["summary"]["legend"]
    if has_nodata and not any(i["class"] == config.NO_DATA_LABEL for i in legend):
        legend = legend + [{"class": config.NO_DATA_LABEL, "color": config.NO_DATA_COLOR, "lo": None, "hi": None,
                            "label": config.NO_DATA_LABEL}]

    choice = settings.get("renderer", "auto")
    qgis_py = config.find_qgis_python() if choice in ("auto", "qgis") else None
    if qgis_py:
        job = {
            "gpkg": str(gpkg), "qgz": str(config.QGZ_PATH), "qpt": str(config.QPT_PATH),
            "layout": settings.get("layout", "qgz"), "level": meta["level"], "legend": legend,
            "classification": meta["classification"], "has_nodata": has_nodata,
            "texts": texts(meta), "logo_dir": str(config.LOGO_DIR), "basemap": settings.get("basemap", False),
            "out_png": str(outs["png"]), "out_pdf": str(outs["pdf"]), "out_map_only": str(outs["map_only"]),
            "out_label_report": str(out_dir / "label_report.json"),
            "font_dir": str(config.FONT_DIR), "font_family": config.FONT_FAMILY,
            "dpi": 300,
        }
        job_path = out_dir / "qgis_job.json"
        job_path.write_text(json.dumps(job, indent=1), encoding="utf-8")
        log(f"Rendering with PyQGIS ({qgis_py})")
        try:
            proc = subprocess.run([qgis_py, str(Path(__file__).with_name("qgis_render.py")), str(job_path)],
                                  capture_output=True, text=True, timeout=600,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            ok = proc.returncode == 0 and outs["png"].exists() and outs["map_only"].exists()
            (out_dir / "qgis_render.log").write_text(proc.stdout + "\n" + proc.stderr, encoding="utf-8")
            if ok:
                job_path.unlink(missing_ok=True)
                return {**outs, "renderer": "qgis", "areas": areas, "prov": prov}
            log("PyQGIS rendering failed – falling back to matplotlib. See qgis_render.log")
            if choice == "qgis":
                raise RuntimeError("PyQGIS rendering failed:\n" + proc.stderr[-2000:])
        except subprocess.TimeoutExpired:
            log("PyQGIS rendering timed out – falling back to matplotlib")
    elif choice == "qgis":
        raise RuntimeError("QGIS was not found. Install QGIS or set QGIS_PYTHON to python-qgis*.bat")

    report = render_matplotlib(areas, prov, meta, legend, outs)
    (out_dir / "label_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    return {**outs, "renderer": "matplotlib", "areas": areas, "prov": prov}


# ----------------------------------------------------- matplotlib fallback ---

MM = 1 / 25.4


def _draw_map(ax, areas, prov, label_size=6.0, prov_label_size=13, pad=0.04):
    areas.plot(ax=ax, color=areas.class_color, edgecolor="#939393", linewidth=0.35)
    nod = areas[areas.envi_class == config.NO_DATA_LABEL]
    if len(nod):
        nod.plot(ax=ax, facecolor="none", edgecolor="#777777", hatch="////", linewidth=0)
    prov.boundary.plot(ax=ax, color="#232323", linewidth=1.3)
    ax.set_axis_off()
    ax.set_aspect(1 / math.cos(math.radians(17.4)))
    minx, miny, maxx, maxy = prov.total_bounds
    padx = (maxx - minx) * pad
    ax.set_xlim(minx - padx, maxx + padx)
    ax.set_ylim(miny - (maxy - miny) * 0.01, maxy + (maxy - miny) * 0.01)
    name_col = "MunName2" if "MunName2" in areas else "Pro_Name"
    return place_labels(ax, areas, name_col, label_size, prov if name_col == "MunName2" else None, prov_label_size)


def _north_arrow(ax, x=0.12, y=0.86, size=0.07):
    ax.annotate("", xy=(x, y + size), xytext=(x, y), xycoords="axes fraction",
                arrowprops=dict(facecolor="black", edgecolor="black", width=6, headwidth=18, headlength=16))
    ax.text(x, y + size + 0.012, "N", transform=ax.transAxes, ha="center", va="bottom", fontsize=14,
            fontweight="bold")


def _scale_bar(ax, km=30, segments=3):
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    deg = km / (111.32 * math.cos(math.radians((y0 + y1) / 2)))
    bx, by = x0 + (x1 - x0) * 0.62, y0 + (y1 - y0) * 0.06
    h = (y1 - y0) * 0.008
    for i in range(segments):
        ax.add_patch(Rectangle((bx + i * deg / segments, by), deg / segments, h,
                               facecolor="black" if i % 2 == 0 else "white", edgecolor="black", lw=0.6, zorder=7))
    for i in range(segments + 1):
        ax.text(bx + i * deg / segments, by - h * 1.2, f"{int(i * km / segments)}", ha="center", va="top",
                fontsize=7, zorder=7)
    ax.text(bx + deg + deg * 0.05, by - h * 1.2, "km", ha="left", va="top", fontsize=7, zorder=7)


def _logo(fig, path, rect):
    if not Path(path).exists():
        return
    from PIL import Image
    ax = fig.add_axes(rect)
    im = Image.open(path)
    # Downscale to what the export needs (≤ 900 px ≈ 5 cm at 450 dpi): matplotlib resamples images as float
    # arrays, so a full-size 2800 px logo costs hundreds of MB of memory while drawing.
    im.thumbnail((900, 900), Image.LANCZOS)
    ax.imshow(im)
    ax.set_axis_off()


def render_matplotlib(areas, prov, meta, legend, outs):
    t = texts(meta)
    fig = plt.figure(figsize=(300 * MM, 300 * MM), dpi=100)
    W = H = 300.0

    def rect(x, y, w, h):  # mm from top-left → figure fraction
        return [x / W, 1 - (y + h) / H, w / W, h / H]

    ax = fig.add_axes(rect(9.8, 8.4, 187.6, 283.2))
    rep_layout = _draw_map(ax, areas, prov)
    _north_arrow(ax)
    _scale_bar(ax)
    ax.text(0.5, -0.005, "CRS: EPSG 4326 - WGS 84", transform=ax.transAxes, ha="center", va="top", fontsize=7)

    _logo(fig, config.LOGO_DIR / "Bagong_Pilipinas_logo.png", rect(215.6, 7.3, 36.1, 35.2))
    _logo(fig, config.LOGO_DIR / "DA CAR LOGO no background.png", rect(249.8, 3.5, 50.0, 42.6))
    _logo(fig, config.LOGO_DIR / "AMIA_Logo.png", rect(262, 271.7, 23.1, 24.5))

    def ftxt(x, y, s, **kw):
        fig.text(x / W, 1 - y / H, s, **kw)

    cx = 250
    ftxt(cx, 48, "Department of Agriculture", ha="center", va="top", fontsize=11, fontweight="bold")
    ftxt(cx, 56, "Cordillera Administrative Region\nAdaptation and Mitigation Initiative in Agriculture (AMIA) Program",
         ha="center", va="top", fontsize=8, linespacing=1.4)
    fig.add_artist(plt.Line2D([207 / W, 291 / W], [1 - 76 / H] * 2, color="black", lw=1))
    ftxt(cx, 86, "EL NIÑO\nVULNERABILITY INDEX\n– CAR", ha="center", va="top", fontsize=20, fontweight="bold",
         color="#0b532f", linespacing=1.15)
    ftxt(cx, 128, t["period"], ha="center", va="top", fontsize=11.5, fontweight="bold")
    ftxt(cx, 137, t["issued"], ha="center", va="top", fontsize=9)

    ftxt(213, 152, "LEGEND", ha="left", va="top", fontsize=11, fontweight="bold")
    ftxt(213, 160, "Vulnerability class (ENVI)", ha="left", va="top", fontsize=8.5)
    y = 168
    for it in legend:
        fig.add_artist(Rectangle(((213) / W, 1 - (y + 5) / H), 9 / W, 5 / H, transform=fig.transFigure,
                                 facecolor=it["color"], edgecolor="#555555", lw=0.5,
                                 hatch="////" if it["lo"] is None else None))
        ftxt(225, y + 2.5, it["label"], ha="left", va="center", fontsize=8.5)
        y += 8
    ftxt(207, 222, "\n".join(textwrap.wrap(t["note"], 62)), ha="left", va="top", fontsize=7.2, linespacing=1.35)
    fig.add_artist(plt.Line2D([207 / W, 291 / W], [1 - 253.7 / H] * 2, color="black", lw=1))
    ftxt(207, 257, "Disclaimer:\n" + "\n".join(textwrap.wrap(
        "DA RFO CAR is not liable to any loss or damages arising from utilizing this vulnerability index. "
        "The index is valid only for the outlook period and areas stated.", 62)),
        ha="left", va="top", fontsize=7.2, linespacing=1.35)
    ftxt(207, 280, "\n".join(textwrap.wrap(t["source"].replace("\n", " "), 44)), ha="left", va="top", fontsize=6.6,
         style="italic", linespacing=1.35)

    fig.savefig(outs["png"], dpi=300)
    fig.savefig(outs["pdf"])
    plt.close(fig)

    # transparent map-only image for the presentation
    minx, miny, maxx, maxy = prov.total_bounds
    aspect = (maxx - minx) * 1.24 * math.cos(math.radians(17.4)) / ((maxy - miny) * 1.02)
    fig = plt.figure(figsize=(8 * aspect, 8), dpi=300)
    ax = fig.add_axes([0, 0, 1, 1])
    rep_map = _draw_map(ax, areas, prov, label_size=5.5, prov_label_size=12, pad=0.12)
    fig.savefig(outs["map_only"], dpi=300, transparent=True)
    plt.close(fig)
    return {"layout": rep_layout, "map_only": rep_map}

