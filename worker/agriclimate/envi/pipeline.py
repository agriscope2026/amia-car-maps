"""End-to-end orchestration: inputs → validation → ENVI → map → presentation → outputs/<timestamp>/."""
from __future__ import annotations

import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

import pandas as pd

from . import config, index, io_loader, mapping, presentation, recommendations


def merged_settings(settings: dict | None) -> dict:
    s = json.loads(json.dumps(config.DEFAULT_SETTINGS))
    for k, v in (settings or {}).items():
        if v is not None:
            s[k] = v
    return s


def load_inputs(files: dict, settings: dict) -> tuple[dict, io_loader.Gazetteer]:
    """files: {dataset: (path_or_bytes, filename)}"""
    gaz = io_loader.load_gazetteer()
    return io_loader.load_all(files, gaz, settings), gaz


def default_files() -> dict:
    return {k: (p, p.name) for k, p in config.DEFAULT_FILES.items()}


def validation_ok(results: dict) -> bool:
    return all(r.ok for r in results.values())


# ------------------------------------------------------------------ export ---

def match_report(results: dict) -> pd.DataFrame:
    rows = []
    for ds, r in results.items():
        for m in r.report.get("rows", []):
            rows.append({"Dataset": ds, "Row": m.get("row"), "Input name": m.get("raw_name"), "Role": m.get("role"),
                         "Province hint": m.get("province_hint", ""), "Matched GIS area": m.get("area_label") or "",
                         "Area key": m.get("area_key") or "", "Method": m.get("method", ""),
                         "Score": m.get("score", "")})
    return pd.DataFrame(rows)


def methodology_rows(meta: dict, settings: dict, results: dict) -> list[tuple[str, str]]:
    w = meta["weights"]
    rows = [
        ("Title", config.APP_TITLE),
        ("Outlook period", meta["labels"]["period"]),
        ("Issued (as of)", meta["labels"]["issued"]),
        ("Standing crops as of", meta["labels"]["crops_as_of"]),
        ("Analysis level", meta["level"]),
        ("Areas", str(meta["n_areas"])),
        ("Areas with no data", str(meta["n_nodata"])),
        ("Normalization", "Min–max: x_norm = (x − min) / (max − min); 0 when max = min. Higher = more vulnerable."),
        ("Drought forecast", meta["hazard_note"] + f" Normalized with: {meta['hazard_method']}."),
        ("Historical damage", meta["damage_note"]),
        ("Standing crops", meta["crops_note"]),
        ("Weights", f"Drought forecast {w['hazard']:.4f}; Historical damage {w['damage']:.4f}; "
                    f"Standing crops {w['crops']:.4f}"),
        ("ENVI", "Σ weight × normalized indicator"),
        ("Classification", meta["classification"]),
        ("Class breaks", " | ".join(f"{b:.4f}" for b in meta["breaks"])),
        ("Missing-data policy", settings.get("missing_policy", "nodata")),
    ]
    cm = results["drought"].report.get("category_mapping")
    if cm:
        rows.append(("Drought category mapping", "; ".join(f"{k} = {v}" for k, v in cm.items())))
    for ds, r in results.items():
        rows.append((f"Input file ({ds})", r.report.get("filename", "")))
    return rows


def export_excel(df: pd.DataFrame, meta: dict, results: dict, settings: dict, path: Path) -> Path:
    table = index.display_table(df)
    with pd.ExcelWriter(path, engine="xlsxwriter") as xw:
        wb = xw.book
        F = config.FONT_FAMILY
        wb.formats[0].set_font_name(F)        # workbook default font
        hdr = wb.add_format({"bold": True, "bg_color": "#0b6237", "font_color": "white", "border": 1,
                             "text_wrap": True, "valign": "vcenter", "font_name": F})
        n3 = wb.add_format({"num_format": "0.000", "font_name": F})
        n2 = wb.add_format({"num_format": "#,##0.00", "font_name": F})
        table.to_excel(xw, sheet_name="ENVI Results", index=False)
        ws = xw.sheets["ENVI Results"]
        for i, c in enumerate(table.columns):
            ws.write(0, i, c, hdr)
            fmt = n3 if "norm" in c or c == "ENVI" else (n2 if "(ha" in c or c.startswith(("crop_", "dmg_")) else None)
            ws.set_column(i, i, 22 if c in ("Area", "Province", "Missing indicators") else 14, fmt)
        ws.set_row(0, 34)
        ws.freeze_panes(1, 3)
        ws.autofilter(0, 0, len(table), len(table.columns) - 1)
        ci = list(table.columns).index("Class")
        for name, color in {**config.CLASS_COLORS, config.NO_DATA_LABEL: config.NO_DATA_COLOR}.items():
            ws.conditional_format(1, ci, len(table), ci, {"type": "cell", "criteria": "==", "value": f'"{name}"',
                                                          "format": wb.add_format({"bg_color": color, "font_name": F})})

        s = meta["summary"]
        summ = pd.DataFrame([{"Class": it["class"], "Range": it["range"], "Areas": it["count"]} for it in s["legend"]])
        summ.to_excel(xw, sheet_name="Summary", index=False)
        ws2 = xw.sheets["Summary"]
        for i, c in enumerate(summ.columns):
            ws2.write(0, i, c, hdr)
        ws2.set_column(0, 0, 18)
        ws2.set_column(1, 2, 16)
        r0 = len(summ) + 2
        ws2.write(r0, 0, "Standing crop area at risk (High + Very High), ha", wb.add_format({"bold": True, "font_name": F}))
        ws2.write(r0, 2, s["crop_at_risk_ha"], n2)
        for j, (k, v) in enumerate(s["crop_at_risk_by_crop"].items()):
            ws2.write(r0 + 1 + j, 0, f"  {k}")
            ws2.write(r0 + 1 + j, 2, v, n2)
        r1 = r0 + 2 + len(s["crop_at_risk_by_crop"]) + 1
        top = pd.DataFrame(s["top10"])[["rank", "area", "province", "envi", "class", "crops_ha"]]
        top.columns = ["Rank", "Area", "Province", "ENVI", "Class", "Standing crops (ha)"]
        ws2.write(r1, 0, "Top 10 most vulnerable areas", wb.add_format({"bold": True, "font_name": F}))
        top.to_excel(xw, sheet_name="Summary", index=False, startrow=r1 + 1)
        for i, c in enumerate(top.columns):
            ws2.write(r1 + 1, i, c, hdr)
        ws2.set_column(3, 5, 16)

        meth = pd.DataFrame(methodology_rows(meta, settings, results), columns=["Item", "Value"])
        meth.to_excel(xw, sheet_name="Methodology", index=False)
        ws3 = xw.sheets["Methodology"]
        ws3.set_column(0, 0, 28)
        ws3.set_column(1, 1, 110, wb.add_format({"text_wrap": True, "valign": "top", "font_name": F}))
        for i, c in enumerate(meth.columns):
            ws3.write(0, i, c, hdr)

        mr = match_report(results)
        mr.to_excel(xw, sheet_name="Name Matching", index=False)
        ws4 = xw.sheets["Name Matching"]
        for i, c in enumerate(mr.columns):
            ws4.write(0, i, c, hdr)
        ws4.set_column(0, 8, 18)

        write_recommendations_sheet(xw.book, settings.get("recommendations", ""), hdr)
    return path


def write_recommendations_sheet(wb, text: str, hdr=None) -> None:
    """Add a 'Recommendations' sheet (xlsxwriter workbook)."""
    if not (text or "").strip():
        return
    ws = wb.add_worksheet("Recommendations")
    ws.set_column(0, 0, 140, wb.add_format({"text_wrap": True, "valign": "top", "font_name": config.FONT_FAMILY}))
    ws.write(0, 0, "Agricultural recommendations", hdr or wb.add_format({"bold": True, "font_name": config.FONT_FAMILY}))
    for i, line in enumerate(text.splitlines(), start=1):
        ws.write(i, 0, line)


def _replace_recommendations_xlsx(path: Path, text: str) -> None:
    """Rewrite the Recommendations sheet of an existing results workbook (openpyxl)."""
    from openpyxl import load_workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = load_workbook(path)
    if "Recommendations" in wb.sheetnames:
        del wb["Recommendations"]
    if text.strip():
        ws = wb.create_sheet("Recommendations")
        ws.column_dimensions["A"].width = 140
        ws["A1"] = "Agricultural recommendations"
        ws["A1"].font = Font(name=config.FONT_FAMILY, bold=True, color="FFFFFF")
        ws["A1"].fill = PatternFill("solid", fgColor="0B6237")
        for i, line in enumerate(text.splitlines(), start=2):
            c = ws.cell(i, 1, line)
            c.alignment = Alignment(wrap_text=True, vertical="top")
            c.font = Font(name=config.FONT_FAMILY)
    wb.save(path)


def _zip_run(out: Path) -> Path:
    zpath = out / f"ENVI_outputs_{out.name}.zip"
    zpath.unlink(missing_ok=True)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(out.rglob("*")):
            if p.is_file() and p != zpath:
                z.write(p, p.relative_to(out))
    return zpath


# --------------------------------------------------------------------- run ---

def new_run_dir() -> Path:
    base = config.OUTPUTS / datetime.now().strftime("%Y-%m-%d_%H%M")
    path, n = base, 2
    while path.exists():
        path = base.with_name(f"{base.name}_{n}")
        n += 1
    path.mkdir(parents=True)
    return path


def run(files: dict, settings: dict | None = None, progress=None, out_dir: Path | None = None) -> dict:
    """Full pipeline. ``progress(step, state, message)`` is called for UI updates.

    Returns a manifest with the run folder and produced files.
    """
    progress = progress or (lambda *a: None)
    settings = merged_settings(settings)
    out = out_dir or new_run_dir()

    progress("validate", "running", "Validating inputs")
    results, gaz = load_inputs(files, settings)
    if not validation_ok(results):
        errs = {k: r.report["errors"] for k, r in results.items() if r.report["errors"]}
        progress("validate", "error", json.dumps(errs))
        raise ValueError(f"Input validation failed: {errs}")
    inp = out / "inputs"
    inp.mkdir(exist_ok=True)
    for ds, (src, name) in files.items():
        target = inp / name
        if isinstance(src, (bytes, bytearray)):
            target.write_bytes(src)
        else:
            shutil.copy2(src, target)
    progress("validate", "done", "Inputs validated and saved")

    progress("compute", "running", "Normalizing and computing ENVI")
    df, meta = index.compute_envi(results, gaz, settings)
    if not (settings.get("recommendations") or "").strip():
        settings["recommendations"] = recommendations.generate(df, meta, results, settings)
        settings["recommendations_source"] = "auto"
    xlsx = export_excel(df, meta, results, settings, out / "envi_results.xlsx")
    index.display_table(df).to_csv(out / "envi_results.csv", index=False, encoding="utf-8-sig")
    match_report(results).to_csv(out / "match_report.csv", index=False, encoding="utf-8-sig")
    progress("compute", "done", f"ENVI computed for {meta['n_areas']} areas")

    progress("map", "running", "Rendering map")
    maps = mapping.render(df, meta, out, settings, log=lambda m: progress("map", "running", m))
    areas, prov = maps.pop("areas"), maps.pop("prov")
    (out / "envi_results.geojson").write_text(json.dumps(mapping.to_geojson(areas, prov, 0)["areas"]),
                                              encoding="utf-8")
    progress("map", "done", f"Map rendered ({maps['renderer']})")

    progress("presentation", "running", "Building presentation images")
    pres = presentation.build_all(meta, maps["map_only"], out, settings.get("recommendations", ""))
    progress("presentation", "done", "Presentation images ready")

    progress("package", "running", "Saving settings and ZIP")
    settings_out = {**settings, "renderer_used": maps["renderer"], "run_folder": out.name,
                    "created": datetime.now().isoformat(timespec="seconds"),
                    "input_files": {k: v[1] for k, v in files.items()},
                    "class_breaks": meta["breaks"], "analysis_level": meta["level"],
                    "methodology": dict(methodology_rows(meta, settings, results))}
    (out / "settings.json").write_text(json.dumps(settings_out, indent=2, ensure_ascii=False), encoding="utf-8")
    (out / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    zpath = _zip_run(out)
    progress("package", "done", "All outputs saved")

    return {
        "run_id": out.name, "folder": str(out), "renderer": maps["renderer"],
        "files": {
            "excel": xlsx.name, "csv": "envi_results.csv", "map_png": maps["png"].name, "map_pdf": maps["pdf"].name,
            "map_only": maps["map_only"].name, "slide": pres["slide"].name, "poster": pres["poster"].name,
            "zip": zpath.name, "settings": "settings.json", "geojson": "envi_results.geojson",
            "gpkg": maps["gpkg"].name, "match_report": "match_report.csv",
        },
        "summary": meta["summary"],
        "recommendations": settings.get("recommendations", ""),
    }


def rebuild_presentation(run_id: str, text: str) -> dict:
    """Re-draw the presentation of an existing run with edited recommendations (no map re-render)."""
    out = config.OUTPUTS / run_id
    meta = json.loads((out / "meta.json").read_text(encoding="utf-8"))
    pres = presentation.build_all(meta, out / "envi_map_only.png", out, text)
    sp = out / "settings.json"
    st = json.loads(sp.read_text(encoding="utf-8"))
    st["recommendations"] = text
    st["recommendations_source"] = "edited"
    sp.write_text(json.dumps(st, indent=2, ensure_ascii=False), encoding="utf-8")
    if (out / "envi_results.xlsx").exists():
        _replace_recommendations_xlsx(out / "envi_results.xlsx", text)
    _zip_run(out)
    return {k: v.name for k, v in pres.items()}


def list_runs() -> list[dict]:
    if not config.OUTPUTS.exists():
        return []
    runs = []
    for d in sorted(config.OUTPUTS.iterdir(), reverse=True):
        if d.is_dir() and not d.name.startswith("_") and (d / "settings.json").exists():
            runs.append({"run_id": d.name, "files": sorted(p.name for p in d.iterdir() if p.is_file())})
    return runs
