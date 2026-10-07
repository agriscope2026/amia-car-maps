"""Export products for one product version: the map images and PDFs.

Every map (day, month, season total, % of normal, ENVI …) gets a print-ready PNG (400 dpi) and a vector PDF in the
DA-RFO-CAR layout; all of them also come in one ZIP. ENVI additionally gets its presentation (5760×3240) and A4
poster (450 dpi), each as PNG and PDF, in the prototype layout (sample data/envi_sample.png), with the map drawn in the same style as the
other maps. A sharp JPG preview of each image is made for the dashboard's photo mode (not listed as a download).

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
    if payload.get("hydro_overlay") and mapinfo.draw_hydro(ax, scale=1.4):
        mapinfo.draw_hydro_legend_in_map(ax)
    if payload.get("crop_overlay"):
        mapinfo.draw_crop_circles(ax, payload["crop_overlay"])
        mapinfo.draw_crop_legend_in_map(ax, payload["crop_overlay"])
    fig.savefig(path, dpi=450, transparent=True)
    plt.close(fig)
    gc.collect()
    return path


def _pdf(png: Path, path: Path, dpi: float) -> Path:
    """High-resolution PDF of an image (full resolution kept)."""
    from PIL import Image
    with Image.open(png) as im:
        im.convert("RGB").save(path, "PDF", resolution=dpi)
    gc.collect()
    return path


def _envi_presentation(payload: dict, files: dict, settings: dict, map_only: Path, out_dir: Path) -> dict:
    """ENVI presentation (5760×3240) + A4 poster (450 dpi) in the prototype layout, with the common map style,
    each as PNG and PDF (full resolution)."""
    from .envi import presentation
    from .products.envi_product import compute
    _, _, meta, _ = compute(files, settings)
    recs = payload.get("texts", {}).get("recommendations", "")
    # one image at a time (each is ~75 MB in memory), so the worker fits a small (512 MB) instance
    out = {"presentation": presentation.build_slide(meta, map_only, out_dir / "envi_presentation_5760x3240.png",
                                                    scale=3.0, recommendations=recs)}
    gc.collect()
    out["presentation_pdf"] = _pdf(out["presentation"], out_dir / "envi_presentation.pdf", 288)
    out["presentation_web"] = _preview_jpg(out["presentation"], out_dir / "envi_presentation_web.jpg", 3840)
    out["poster"] = presentation.build_poster(meta, map_only, out_dir / "envi_poster_A4.png", recommendations=recs,
                                              scale=3.0)
    gc.collect()
    out["poster_pdf"] = _pdf(out["poster"], out_dir / "envi_poster_A4.pdf", 450)
    out["poster_web"] = _preview_jpg(out["poster"], out_dir / "envi_poster_A4_web.jpg", 2480)
    return out


def export_product(payload: dict, out_dir: Path, settings: dict | None = None, files: dict | None = None,
                   progress=None) -> dict:
    """Render every map (PNG 300 dpi + PDF) and, for ENVI, the presentation and poster. Returns the manifest."""
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
    n = len(payload["layers"])
    for i, lyr in enumerate(payload["layers"]):
        progress("map", "running", f"Rendering map {i + 1}/{n}: {lyr['label']}")
        name = f"{stem}_map_{lyr['id']}"
        r = render.render_layer(payload, lyr, out_dir, name, preview=out_dir / f"{name}_preview.jpg")
        reports[lyr["id"]] = r["label_report"]
        manifest["maps"].append({"layer": lyr["id"], "label": lyr["label"], "alt": r["alt"], "png": r["png"].name,
                                 "pdf": r["pdf"].name,
                                 "jpg": r["preview"].name})
    progress("map", "done", "Maps ready")

    if stem == "envi" and files:
        progress("presentation", "running", "Building the ENVI presentation and poster")
        mo = _map_only(payload, payload["layers"][0], out_dir / "envi_map_only.png")
        from .products.envi_product import _envi_settings
        pres = _envi_presentation(payload, files, _envi_settings(settings), mo, out_dir)
        mo.unlink(missing_ok=True)
        manifest["maps"][0].update({k: p.name for k, p in pres.items()})
        progress("presentation", "done", "Presentation and poster ready")

    # one ZIP with every image and PDF (previews excluded)
    zpath = out_dir / f"{stem}_{payload['period']['start']}_maps.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_STORED) as z:
        for m in manifest["maps"]:
            for k in ("png", "pdf", "presentation", "presentation_pdf", "poster", "poster_pdf"):
                if m.get(k):
                    z.write(out_dir / m[k], f"CAR_{stem}_{layer_tag(m['layer'])}_{k}{Path(m[k]).suffix}")
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
