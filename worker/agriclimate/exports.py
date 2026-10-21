"""Export products for one product version: the map images (and, for the rainfall and drought maps, PDFs).

Rainfall and drought: every map (day, month, % of normal) gets a print-ready PNG (400 dpi) in the DA-RFO-CAR
layout (PNG images only, no PDFs). ENVI: the season outlook and each month get a landscape
presentation (5760×3240) and a portrait A4 poster (450 dpi) as PNG images only, in the prototype layout (sample
data/envi_sample.png), with the map drawn in the same style as the other maps; its computation workbook
(normalization, weights and index as live Excel formulas) goes in the ZIP. Everything also comes in one ZIP. A sharp
JPG preview of each image is made for the dashboard's photo mode (not listed as a download).

Optional: ``settings["crop_overlay"]`` draws standing crops as proportional circles on the maps;
``settings["hydro_overlay"]`` draws rivers and water bodies (OpenStreetMap).
"""
from __future__ import annotations

import gc
import json
import math
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import mapinfo, render

MANILA = ZoneInfo("Asia/Manila")
PREVIEW_WIDTH = 3000          # photo-mode previews: sharp enough to zoom in
PREVIEW_QUALITY = 92
NO_EXPORT_LAYERS = {"total", "season_total", "pct_normal"}   # older total layers; % of normal: dashboard only


def now_manila() -> str:
    return datetime.now(MANILA).isoformat(timespec="seconds")


def layer_tag(layer_id: str) -> str:
    """'m_2026-10' → '2026-10', 'd_2026-10-05' → '2026-10-05', 'total' → 'total'."""
    return layer_id.removeprefix("m_").removeprefix("d_")


def _preview_jpg(png: Path, path: Path, width: int = PREVIEW_WIDTH) -> Path:
    from PIL import Image
    with Image.open(png) as im:
        im.thumbnail((width, width), Image.LANCZOS, reducing_gap=3.0)   # shrink first, then convert (less memory)
        im.convert("RGB").save(path, "JPEG", quality=PREVIEW_QUALITY, optimize=True, progressive=True, subsampling=0)
    gc.collect()
    return path


def _map_only(payload: dict, layer: dict, path: Path) -> Path:
    """The map alone (transparent, 300 dpi) – used inside the ENVI presentation and poster."""
    import matplotlib.pyplot as plt
    muni, prov = render._areas_for(layer)
    minx, miny, maxx, maxy = prov.total_bounds
    aspect = (maxx - minx) * 1.24 * math.cos(math.radians(17.4)) / ((maxy - miny) * 1.02)
    fig = plt.figure(figsize=(8 * aspect, 8), dpi=450)
    ax = fig.add_axes([0, 0, 1, 1])
    style = render.STYLES.get(payload["type"], render.DEFAULT_STYLE)
    render._draw(ax, muni, prov, label_size=5.5, prov_label_size=12, pad=0.12, style=style,
                 label_style=render.DARK_LABELS)
    hydro = bool(payload.get("hydro_overlay")) and mapinfo.draw_hydro(ax, scale=1.4)
    if payload.get("crop_overlay"):
        mapinfo.draw_crop_circles(ax, payload["crop_overlay"])
    # crops and rivers share one legend box, so the two keys never land on top of each other
    mapinfo.draw_overlay_legend_in_map(ax, payload.get("crop_overlay"), hydro)
    fig.savefig(path, dpi=450, transparent=True)
    plt.close(fig)
    gc.collect()
    return path


def _envi_images(meta: dict, payload: dict, layer: dict, recs: str, out_dir: Path, tag: str) -> dict:
    """Presentation (5760×3240, landscape) + A4 poster (450 dpi, portrait) of one ENVI map – the season outlook or
    one month – each as PNG and a web preview, with that map drawn in the common style."""
    from .envi import presentation
    base = "envi" if tag == "envi" else f"envi_{tag}"
    mo = _map_only(payload, layer, out_dir / f"{base}_map_only.png")
    # one image at a time (each is ~75 MB in memory), so the worker fits a small (512 MB) instance
    out = {"presentation": presentation.build_slide(meta, mo, out_dir / f"{base}_presentation_5760x3240.png",
                                                    scale=3.0, recommendations=recs)}
    gc.collect()
    out["presentation_web"] = _preview_jpg(out["presentation"], out_dir / f"{base}_presentation_web.jpg", 3840)
    out["poster"] = presentation.build_poster(meta, mo, out_dir / f"{base}_poster_A4.png", recommendations=recs,
                                              scale=3.0)
    gc.collect()
    out["poster_web"] = _preview_jpg(out["poster"], out_dir / f"{base}_poster_A4_web.jpg", 2480)
    mo.unlink(missing_ok=True)
    return out


def _envi_presentation(payload: dict, files: dict, settings: dict, out_dir: Path, progress) -> tuple[dict, Path]:
    """Presentation + A4 poster for the season outlook and for each month's ENVI (that month's classes, top 10,
    crops at risk and recommendations), plus the results workbook. Returns ({layer id: files}, workbook)."""
    from .envi import index, pipeline, recommendations
    from .products.envi_product import compute, month_keys
    results, df, meta, s = compute(files, settings)
    recs = payload.get("texts", {}).get("recommendations", "")
    xlsx = pipeline.export_excel(df, meta, results, {**s, "recommendations": recs}, out_dir / "envi_results.xlsx")
    layers = {lyr["id"]: lyr for lyr in payload["layers"]}
    progress("presentation", "running", "Building the season outlook presentation and poster")
    out = {"envi": _envi_images(meta, payload, layers["envi"], recs, out_dir, "envi")}
    months = index.monthly_envi(df, meta, s, results["drought"].report)
    yms = month_keys(list(months), s["period_start"], s["period_end"])
    for name, f in months.items():
        lid = f"m_{yms.get(name)}"
        if lid not in layers:
            continue
        progress("presentation", "running", f"Building the {layers[lid]['label']} presentation and poster")
        d, m = index.month_view(df, meta, name, f, layers[lid]["label"])
        out[lid] = _envi_images(m, payload, layers[lid], recommendations.generate(d, m, results, s), out_dir,
                                yms[name])
    return out, xlsx


def export_product(payload: dict, out_dir: Path, settings: dict | None = None, files: dict | None = None,
                   progress=None) -> dict:
    """Render every map (PNG 400 dpi) or, for ENVI, the presentation and poster of the season and each month.
    Returns the manifest."""
    progress = progress or (lambda *a: None)
    settings = settings or {}
    out_dir.mkdir(parents=True, exist_ok=True)
    ov = settings.get("crop_overlay")
    if ov and ov.get("crops"):
        payload = {**payload, "crop_overlay": ov}            # standing crops as proportional circles on the maps
    if settings.get("hydro_overlay"):
        payload = {**payload, "hydro_overlay": True}         # rivers & water bodies
    stem = payload["type"]
    manifest: dict = {"type": stem, "created": now_manila(), "files": {}, "maps": []}

    reports = {}
    xlsx = None
    # the 10-day and season totals stay on the dashboard but get no map image / PDF
    layers = [lyr for lyr in payload["layers"] if lyr["id"] not in NO_EXPORT_LAYERS]
    n = len(layers)
    envi_images = stem == "envi" and bool(files)   # ENVI: presentation + A4 poster instead of the square print map
    tc = stem == "tc_advisory"                      # tropical cyclone: one A4 page (PDF) + the Facebook posts
    for i, lyr in enumerate([] if envi_images or tc else layers):
        progress("map", "running", f"Rendering map {i + 1}/{n}: {lyr['label']}")
        name = f"{stem}_map_{lyr['id']}"
        r = render.render_layer(payload, lyr, out_dir, name, preview=out_dir / f"{name}_preview.jpg")
        reports[lyr["id"]] = r["label_report"]
        manifest["maps"].append({"layer": lyr["id"], "label": lyr["label"], "alt": r["alt"], "png": r["png"].name,
                                 "jpg": r["preview"].name})
    progress("map", "done", "Maps ready")

    if tc:
        from . import tc_pages
        manifest["maps"] = tc_pages.export(payload, out_dir, progress)
        progress("pages", "done", "A4 page and Facebook posts ready")

    if not envi_images and not tc and manifest["maps"]:
        # rainfall / drought: a title page first, a summary page and a recommendations page last
        from . import pages
        progress("pages", "running", "Making the title, summary and recommendations pages")
        cover = pages.title_page(payload, out_dir)
        extra = [*pages.summary_pages(payload, out_dir), *pages.recommendations_pages(payload, out_dir)]
        as_entry = lambda p: {"layer": p["layer"], "label": p["label"], "alt": p["alt"],  # noqa: E731
                              "png": p["png"].name, "jpg": p["jpg"].name}
        manifest["maps"] = [as_entry(cover), *manifest["maps"], *(as_entry(p) for p in extra)]
        progress("pages", "done", "Title, summary and recommendations pages ready")

    if envi_images:
        from .products.envi_product import _envi_settings
        pres, xlsx = _envi_presentation(payload, files, _envi_settings(settings), out_dir, progress)
        for lyr in layers:
            if lyr["id"] in pres:
                label = "Season outlook" if lyr["id"] == "envi" else lyr["label"]
                manifest["maps"].append({"layer": lyr["id"], "label": lyr["label"],
                                         "alt": f"El Niño Vulnerability Index – {label}: presentation and A4 poster",
                                         **{k: p.name for k, p in pres[lyr["id"]].items()}})
        progress("presentation", "done", f"{len(pres)} presentations and posters ready")
        # title page first, summary and recommendations last – landscape and portrait like the images
        from . import pages
        progress("pages", "running", "Making the title, summary and recommendations pages")
        cover, extra = pages.envi_pages(payload, out_dir)
        manifest["maps"] = [cover, *manifest["maps"], *extra]
        progress("pages", "done", "Title, summary and recommendations pages ready")

    # one ZIP with every image (previews excluded) and, for ENVI, the computation workbook
    zpath = out_dir / f"{stem}_{payload['period']['start']}_maps.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_STORED) as z:
        for m in manifest["maps"]:
            for k in ("png", "pdf", "presentation", "poster", "social"):
                if m.get(k):
                    z.write(out_dir / m[k], f"CAR_{stem}_{layer_tag(m['layer'])}_{k}{Path(m[k]).suffix}")
        if xlsx:
            z.write(xlsx, f"CAR_{stem}_{payload['period']['start']}_computation.xlsx", zipfile.ZIP_DEFLATED)
    manifest["files"] = {"zip": zpath.name}
    manifest["labels_ok"] = all(r["ok"] for r in reports.values())
    # kept with the job for reference (not offered as downloads)
    render.write_label_reports(reports, out_dir / "label_report.json")
    (out_dir / "payload.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")
    return manifest


def clean_dir(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


__all__ = ["export_product", "layer_tag", "now_manila"]
