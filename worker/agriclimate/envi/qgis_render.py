"""Headless PyQGIS renderer for the ENVI map.

Run with QGIS's python launcher (python-qgis*.bat), NOT the app's virtualenv:

    python-qgis-ltr.bat envi/qgis_render.py job.json

The job file (written by envi.mapping) contains the GeoPackage with ENVI results, the class
breaks/colours, texts and output paths. The script:
  1. opens gis template/drought_forecast.qgz (datasources re-pointed to the results GeoPackage),
  2. applies a graduated 5-class renderer on the ENVI field (+ a hatched "No data" layer),
  3. fills the print layout ("drougt_layout" from the .qgz, or the .qpt template) and
  4. exports PNG (300 dpi) + PDF + a transparent map-only PNG for the presentation.
"""
import glob
import json
import math
import os
import re
import sys
import tempfile
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# the offscreen platform has no font database on Windows unless pointed at a font folder
if os.name == "nt":
    os.environ.setdefault("QT_QPA_FONTDIR", os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))

from qgis.core import (  # noqa: E402
    QgsApplication, QgsFillSymbol, QgsGraduatedSymbolRenderer, QgsLayoutExporter,
    QgsLayoutItemLabel, QgsLayoutItemLegend, QgsLegendRenderer, QgsLayoutItemMap, QgsLayoutItemPicture, QgsLayoutItemScaleBar,
    QgsLayoutPoint, QgsLayoutSize, QgsLegendStyle, QgsMapRendererParallelJob, QgsMapSettings, QgsPrintLayout,
    QgsProject, QgsReadWriteContext, QgsRendererRange, QgsSingleSymbolRenderer, QgsUnitTypes, QgsVectorLayer,
    QgsTextFormat, QgsLayoutItemPage, Qgis, QgsPalLayerSettings, QgsProperty, QgsSimpleLineCallout, QgsLineSymbol,
    QgsLabelingEngineSettings, QgsRectangle, QgsGeometry, QgsLabelObstacleSettings, QgsPointXY,
)
from qgis.PyQt.QtCore import QSize, Qt  # noqa: E402
from qgis.PyQt.QtGui import QColor, QFont, QFontDatabase, QFontMetricsF  # noqa: E402
from qgis.PyQt.QtXml import QDomDocument  # noqa: E402


OBSTACLE_FACTOR = 0.3   # weight of municipal borders as label obstacles
FONT_FAMILY = "Montserrat"   # replaced from the job file; all map/layout text uses it


def register_fonts(font_dir):
    """Make the bundled TTFs available to Qt (the offscreen platform only sees what we add)."""
    global FONT_FAMILY
    families = set()
    for f in sorted(glob.glob(os.path.join(font_dir or "", "*.ttf"))):
        fid = QFontDatabase.addApplicationFont(f)
        families.update(QFontDatabase.applicationFontFamilies(fid))
    if FONT_FAMILY not in families and FONT_FAMILY not in QFontDatabase().families():
        log(f"font {FONT_FAMILY} not available - falling back to Arial")
        FONT_FAMILY = "Arial"


def set_family(fmt):
    """Return a copy of a QgsTextFormat using FONT_FAMILY (keeps size, weight, italics, buffer)."""
    f = QFont(fmt.font())
    f.setFamily(FONT_FAMILY)
    fmt.setFont(f)
    fmt.setNamedStyle("")
    return fmt


def apply_layout_fonts(layout):
    """Switch every text element of a print layout to FONT_FAMILY."""
    for it in layout.items():
        if isinstance(it, QgsLayoutItemLabel):
            it.setTextFormat(set_family(it.textFormat()))
        elif isinstance(it, QgsLayoutItemLegend):
            for st_id in (QgsLegendStyle.Title, QgsLegendStyle.Group, QgsLegendStyle.Subgroup,
                          QgsLegendStyle.SymbolLabel):
                st = it.style(st_id)
                st.setTextFormat(set_family(st.textFormat()))
                it.setStyle(st_id, st)
        elif isinstance(it, QgsLayoutItemScaleBar):
            it.setTextFormat(set_family(it.textFormat()))
        elif isinstance(it, QgsLayoutItemMap):
            for g in it.grids().asList():
                g.setAnnotationTextFormat(set_family(g.annotationTextFormat()))


def log(msg):
    print(f"[qgis_render] {msg}", flush=True)


def patched_project(job, tmp):
    """Extract the .qgs from the .qgz and point the boundary layers at the results GeoPackage."""
    with zipfile.ZipFile(job["qgz"]) as z:
        name = next(n for n in z.namelist() if n.endswith(".qgs"))
        xml = z.read(name).decode("utf-8")
    gpkg = job["gpkg"].replace("\\", "/")

    def repl(m):
        src = m.group(1)
        if "Regional_Map_Municipal_Boundary" in src:
            return f"<datasource>{gpkg}|layername=municipalities</datasource>"
        if "Regional_Map_Provincial_Boundary" in src:
            return f"<datasource>{gpkg}|layername=provinces</datasource>"
        return m.group(0)

    xml = re.sub(r"<datasource>(.*?)</datasource>", repl, xml)
    path = os.path.join(tmp, "envi_project.qgs")
    with open(path, "w", encoding="utf-8") as f:
        f.write(xml)
    return path


def make_fill(color, outline="147,147,147,255", width="0.26", style="solid"):
    return QgsFillSymbol.createSimple({"color": color, "outline_color": outline, "outline_width": width,
                                       "outline_width_unit": "MM", "style": style})


def graduated_renderer(job):
    ranges = []
    for it in job["legend"]:
        if it["lo"] is None:
            continue
        sym = make_fill(it["color"])
        ranges.append(QgsRendererRange(float(it["lo"]), float(it["hi"]), sym, it["label"]))
    r = QgsGraduatedSymbolRenderer("envi", ranges)
    r.setClassAttribute("envi")
    # Equal intervals in the app are lower-inclusive; make QGIS agree (value on a break → upper class)
    # by nudging inner upper bounds down a hair. Quantile/natural breaks are upper-inclusive (QGIS default).
    if job.get("classification") == "equal":
        for i in range(len(ranges) - 1):
            r.updateRangeUpperValue(i, ranges[i].upperValue() - 1e-9)
    return r


def setup_layers(project, job):
    layers = project.mapLayers().values()
    muni = prov_lab = prov_line = None
    for lyr in list(layers):
        src = lyr.source()
        if "layername=municipalities" in src:
            muni = lyr
        elif "layername=provinces" in src:
            if lyr.labelsEnabled():
                prov_lab = lyr
            else:
                prov_line = lyr
    # drop the forecast CSV tables, broken layers and (unless asked) the online basemap
    for lyr in list(project.mapLayers().values()):
        if lyr in (muni, prov_lab, prov_line):
            continue
        if lyr.providerType() == "wms" and job.get("basemap"):
            continue
        project.removeMapLayer(lyr.id())
    for lyr in (prov_lab, prov_line):
        if lyr is not None:
            for j in list(lyr.vectorJoins()):
                lyr.removeJoin(j.joinLayerId())
    if muni is None:
        raise RuntimeError("Municipal boundary layer not found in project")

    target = muni if job["level"] == "municipal" else prov_lab
    target.setRenderer(graduated_renderer(job))
    target.setName("ENVI class")
    if job["level"] == "provincial":
        project.layerTreeRoot().findLayer(muni.id()).setItemVisibilityChecked(False)

    if prov_lab is not None and job["level"] == "municipal":
        # keep the template's province labels, hide its old drought fill
        prov_lab.setRenderer(QgsSingleSymbolRenderer(make_fill("0,0,0,0", "0,0,0,0", "0")))

    configure_labels(project, muni, prov_lab)

    root = project.layerTreeRoot()
    nodata = None
    if job.get("has_nodata"):
        lname = "municipalities" if job["level"] == "municipal" else "provinces"
        nodata = QgsVectorLayer(f"{job['gpkg']}|layername={lname}", "No data", "ogr")
        nodata.setSubsetString('"envi" IS NULL')
        sym = make_fill("217,217,217,255")
        hatch = QgsFillSymbol.createSimple({"color": "120,120,120,255", "style": "b_diagonal", "outline_style": "no"})
        sym.appendSymbolLayer(hatch.symbolLayer(0).clone())
        nodata.setRenderer(QgsSingleSymbolRenderer(sym))
        project.addMapLayer(nodata, False)
        idx = root.children().index(root.findLayer(target.id()))
        root.insertLayer(idx + 1, nodata)

    # province outline must draw above the filled municipalities
    if prov_line is not None:
        node = root.findLayer(prov_line.id())
        clone = node.clone()
        root.insertChildNode(0, clone)
        node.parent().removeChildNode(node)
        prov_line.setRenderer(QgsSingleSymbolRenderer(make_fill("0,0,0,0", "35,35,35,255", "0.8")))
    return target, nodata


# ------------------------------------------------------------------ labels ---

PROV_WRAP = 10    # province names longer than this wrap onto two lines ("Mountain / Province")


def configure_labels(project, muni, prov_lab, muni_size=None, pins=None, callouts=None, prov_scale=1.0):
    """Collision-free label placement.

    * Municipality names: any horizontal position inside the polygon; if a name does not fit it may be
      placed just outside with a thin leader line (callout). Higher ENVI -> higher priority.
    * Province names: placed after the municipalities, anywhere inside their (large) province.
    * Municipal borders are weighted obstacles, so names stay inside their own area when they fit;
      labels never overlap each other.
    * The PAL engine never draws overlapping labels; check_labels() verifies that none were dropped.
    """
    inside = Qgis.LabelPolygonPlacementFlag.AllowPlacementInsideOfPolygon
    outside = Qgis.LabelPolygonPlacementFlag.AllowPlacementOutsideOfPolygon
    for lyr in (muni, prov_lab):
        if lyr is None or not lyr.labelsEnabled():
            continue
        labeling = lyr.labeling().clone()
        pal = labeling.settings()
        fmt = pal.format()
        fmt = set_family(fmt)
        f = QFont(fmt.font())
        f.setBold(lyr is muni)
        fmt.setFont(f)
        if lyr is muni and muni_size:
            fmt.setSize(muni_size)
        if lyr is prov_lab:
            if not hasattr(prov_lab, "_envi_base_size"):
                prov_lab._envi_base_size = fmt.size()
            fmt.setSize(prov_lab._envi_base_size * prov_scale)
            pal.autoWrapLength = PROV_WRAP
        pal.setFormat(fmt)
        pal.displayAll = False            # never overlap another label
        pal.labelPerPart = False
        pal.placement = Qgis.LabelPlacement.Horizontal
        props = pal.dataDefinedProperties()
        if lyr is muni:
            pal.setPolygonPlacementFlags(Qgis.LabelPolygonPlacementFlags(inside | outside))
            pal.fitInPolygonOnly = False
            props.setProperty(QgsPalLayerSettings.Priority,
                              QgsProperty.fromExpression('5 + 5 * coalesce("envi", 0)'))
            if callouts is not None:   # only labels that ended up outside their polygon get a leader line
                fld = pal.fieldName.replace('"', '""')
                names = ", ".join(_q(n) for n in callouts) or "''"
                props.setProperty(QgsPalLayerSettings.CalloutDraw, QgsProperty.fromExpression(f'"{fld}" IN ({names})'))
            callout = QgsSimpleLineCallout()
            callout.setEnabled(True)
            callout.setLineSymbol(QgsLineSymbol.createSimple({"color": "70,70,70,255", "width": "0.2"}))
            pal.setCallout(callout)
        else:
            pal.setPolygonPlacementFlags(Qgis.LabelPolygonPlacementFlags(inside))
            pal.priority = 3
        _apply_pins(pal, props, (pins or {}).get(lyr.id()))
        pal.setDataDefinedProperties(props)
        obstacle = pal.obstacleSettings()
        if lyr is muni:   # discourage labels from crossing municipal borders (keeps names in their own area)
            obstacle.setIsObstacle(True)
            obstacle.setType(QgsLabelObstacleSettings.PolygonBoundary)
            obstacle.setFactor(float(os.environ.get("ENVI_OBSTACLE_FACTOR", OBSTACLE_FACTOR)))
        else:
            obstacle.setIsObstacle(False)
        labeling.setSettings(pal)
        lyr.setLabeling(labeling)

    eng = project.labelingEngineSettings()
    eng.setMaximumPolygonCandidatesPerCmSquared(25.0)
    eng.setFlag(QgsLabelingEngineSettings.UsePartialCandidates, False)
    eng.setFlag(QgsLabelingEngineSettings.CollectUnplacedLabels, True)
    eng.setFlag(QgsLabelingEngineSettings.DrawUnplacedLabels, False)
    project.setLabelingEngineSettings(eng)


def extract_labels(results):
    """Copy label positions out of a QgsLabelingResults (it is owned by the exporter/renderer)."""
    if results is None:
        return None
    return [{"layer": l.layerID, "text": l.labelText, "rect": QgsRectangle(l.labelRect)}
            for l in results.allLabels() if not l.isDiagram and not l.isUnplaced]


def _q(t):
    return "'" + str(t).replace("'", "''") + "'"


def _apply_pins(pal, props, pins):
    """Fix label positions (map units, label centre) with data-defined properties; None clears them."""
    keys = (QgsPalLayerSettings.PositionX, QgsPalLayerSettings.PositionY, QgsPalLayerSettings.Hali,
            QgsPalLayerSettings.Vali, QgsPalLayerSettings.AlwaysShow)
    for key in keys:
        props.setProperty(key, QgsProperty())
    if not pins:
        return
    fld = pal.fieldName.replace('"', '""')
    case = lambda i: "CASE " + " ".join(  # noqa: E731
        f'WHEN "{fld}" = {_q(n)} THEN {xy[i]!r}' for n, xy in pins.items()) + " END"
    names = ", ".join(_q(n) for n in pins)
    props.setProperty(QgsPalLayerSettings.PositionX, QgsProperty.fromExpression(case(0)))
    props.setProperty(QgsPalLayerSettings.PositionY, QgsProperty.fromExpression(case(1)))
    props.setProperty(QgsPalLayerSettings.Hali, QgsProperty.fromExpression(f"CASE WHEN \"{fld}\" IN ({names}) THEN 'Center' END"))
    props.setProperty(QgsPalLayerSettings.Vali, QgsProperty.fromExpression(f"CASE WHEN \"{fld}\" IN ({names}) THEN 'Half' END"))
    props.setProperty(QgsPalLayerSettings.AlwaysShow, QgsProperty.fromExpression(f'"{fld}" IN ({names})'))


def check_labels(placed, layers):
    """Return {placed, missing, overlaps, ok} for the labels of ``layers`` (dict layer -> expected names)."""
    if placed is None:
        return {"placed": 0, "missing": [], "overlaps": [], "ok": True}
    missing = []
    for lyr, names in layers.items():
        got = {l["text"] for l in placed if l["layer"] == lyr.id()}
        missing += sorted(set(names) - got)
    overlaps = []
    rects = [(l["text"], l["rect"]) for l in placed]
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            a, b = rects[i][1], rects[j][1]
            inter = a.intersect(b)
            if not inter.isEmpty() and inter.area() > 0.02 * min(a.area(), b.area()):
                overlaps.append(f"{rects[i][0]} / {rects[j][0]}")
    return {"placed": len(placed), "missing": missing, "overlaps": overlaps, "ok": not missing and not overlaps}


def expected_labels(project):
    out = {}
    for lyr in project.mapLayers().values():
        if not isinstance(lyr, QgsVectorLayer) or not lyr.labelsEnabled() or lyr.subsetString():
            continue
        node = project.layerTreeRoot().findLayer(lyr.id())
        if node is None or not node.isVisible():
            continue
        field = lyr.labeling().settings().fieldName
        out[lyr] = [str(f[field]) for f in lyr.getFeatures() if f[field] not in (None, "")]
    return out


def _wrap(text, n):
    if not n or len(text) <= n:
        return [text]
    lines, cur = [], ""
    for w in text.split():
        if cur and len(cur) + 1 + len(w) > n:
            lines.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    return lines + [cur] if cur else lines


def label_box_mm(layer, text):
    """Approximate label box (width, height) in mm, including the text buffer and line wrapping."""
    pal = layer.labeling().settings()
    fmt = pal.format()
    font = QFont(fmt.font())
    font.setPointSizeF(fmt.size())
    fm = QFontMetricsF(font)                       # pixels at 96 dpi
    buf = fmt.buffer().size() if fmt.buffer().enabled() else 0
    lines = _wrap(text, pal.autoWrapLength)
    width = max(fm.horizontalAdvance(t) for t in lines)
    return width * 25.4 / 96 + 2 * buf + 0.6, fm.height() * len(lines) * 25.4 / 96 + 2 * buf + 0.4


def find_pins(layer, placed, missing, units_per_mm, pins, inside_only=False):
    """Find a free spot for each missing label of ``layer``: rings of candidate positions around the polygon's
    pole of inaccessibility, nearest first, avoiding every placed label box. ``inside_only`` keeps the label
    centre inside the polygon (used for province names). Returns {name: (x, y)}."""
    field = layer.labeling().settings().fieldName
    taken = [l["rect"] for l in placed if l["text"] not in missing]
    out = dict(pins)
    for f in layer.getFeatures():
        name = str(f[field])
        if name not in missing or name in out:
            continue
        geom = f.geometry()
        anchor = geom.poleOfInaccessibility(units_per_mm * 0.5)[0].asPoint()
        w_mm, h_mm = label_box_mm(layer, name)
        w, h = w_mm * units_per_mm, h_mm * units_per_mm
        best = None
        for ring in range(0, 40 if inside_only else 14):
            r = ring * h * (0.5 if inside_only else 0.9)
            for k in range(1 if ring == 0 else 24):
                ang = math.radians(k * 15)
                cx = anchor.x() + r * math.cos(ang) * (w / h if ring else 1) * 0.5
                cy = anchor.y() + r * math.sin(ang)
                if inside_only and not geom.contains(QgsGeometry.fromPointXY(QgsPointXY(cx, cy))):
                    continue
                box = QgsRectangle(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
                if all(not box.intersects(t) for t in taken):
                    best = (cx, cy, box)
                    break
            if best:
                break
        if best:
            out[name] = (round(best[0], 7), round(best[1], 7))
            taken.append(best[2])
    return out


def with_label_retries(project, muni, prov_lab, render, what, base_size, units_per_mm):
    """Make every label visible without overlaps.

    1. Let PAL place the labels; shrink municipality labels in 0.5 pt steps (down to 6 pt) while names are dropped.
    2. Pin any name PAL still drops to the nearest free spot (with a leader line) and verify again.
    """
    report = None
    size = base_size
    steps = int(max(0, (base_size or 6) - 6) / 0.5) + 1
    for step in range(steps):
        size = base_size - 0.5 * step if base_size else None
        configure_labels(project, muni, prov_lab, size)
        placed = render()
        report = check_labels(placed, expected_labels(project))
        log(f"{what} @ {size} pt: {report['placed']} placed, missing={report['missing']}, overlaps={report['overlaps']}")
        if report["ok"] or not base_size:
            break
    pins = {}
    prov_scale = 1.0
    prov_names = set(expected_labels(project).get(prov_lab, [])) if prov_lab is not None else set()
    for attempt in range(4):
        if report["ok"] or muni is None:
            break
        missing = set(report["missing"])
        if attempt and missing & prov_names:
            prov_scale *= 0.85      # a province name that still has no room gets a little smaller
            configure_labels(project, muni, prov_lab, size, pins, prov_scale=prov_scale)
            pins.pop(prov_lab.id(), None)
        for lyr in (muni, prov_lab):
            if lyr is not None:
                pins[lyr.id()] = find_pins(lyr, placed, missing, units_per_mm(), pins.get(lyr.id(), {}),
                                           inside_only=lyr is not muni)
        configure_labels(project, muni, prov_lab, size, pins, prov_scale=prov_scale)
        placed = render()
        report = check_labels(placed, expected_labels(project))
        log(f"{what} pinned {sorted(n for d in pins.values() for n in d)}: {report['placed']} placed, "
            f"missing={report['missing']}, overlaps={report['overlaps']}")
    report.update({"municipal_label_size_pt": size, "province_label_scale": round(prov_scale, 3),
                   "fallback_pinned": sorted(n for d in pins.values() for n in d)})
    return report, size, placed, prov_scale


def freeze_labels(project, muni, prov_lab, size, placed, prov_scale=1.0):
    """Pin every label at its verified position; leader lines only for labels outside their polygon."""
    pins, callouts = {}, []
    geoms = {}
    if muni is not None:
        field = muni.labeling().settings().fieldName
        geoms = {str(f[field]): f.geometry() for f in muni.getFeatures()}
    for l in placed or []:
        c = l["rect"].center()
        pins.setdefault(l["layer"], {})[l["text"]] = (round(c.x(), 7), round(c.y(), 7))
        if muni is not None and l["layer"] == muni.id():
            g = geoms.get(l["text"])
            if g is not None and not g.contains(QgsGeometry.fromPointXY(c)):
                callouts.append(l["text"])
    configure_labels(project, muni, prov_lab, size, pins, callouts, prov_scale)
    return pins, callouts


def final_export(project, muni, prov_lab, size, placed, render, units_per_mm, what, prov_scale=1.0):
    """Freeze labels, render the final output and, if font metrics at full resolution make two labels touch,
    move one of them to the nearest free spot and render again (max 3 times)."""
    pins, callouts = freeze_labels(project, muni, prov_lab, size, placed, prov_scale)
    final = None
    for attempt in range(4):
        final_placed = render()
        final = check_labels(final_placed, expected_labels(project))
        log(f"{what} final: {final['placed']} labels, missing={final['missing']}, overlaps={final['overlaps']}")
        if final["ok"] or muni is None or attempt == 3:
            break
        movers = {pair.split(" / ")[1] for pair in final["overlaps"]} | set(final["missing"])
        if not movers:
            break
        keep = [l for l in final_placed if l["text"] not in movers]
        for lyr in (muni, prov_lab):
            if lyr is None:
                continue
            mine = movers & {str(n) for n in pins.get(lyr.id(), {})} | (movers & set(final["missing"]))
            new = find_pins(lyr, keep, mine, units_per_mm(), {}, inside_only=lyr is not muni)
            pins.setdefault(lyr.id(), {}).update(new)
            if lyr is muni:
                callouts.extend(n for n in new if n not in callouts)
        configure_labels(project, muni, prov_lab, size, pins, callouts, prov_scale)
    final["leader_lines"] = sorted(callouts)
    return final


# ------------------------------------------------------------------ layout ---

def fill_qgz_layout(project, job, target, nodata):
    mgr = project.layoutManager()
    layout = mgr.layoutByName("drougt_layout") or next(
        (l for l in mgr.printLayouts() if "droug" in l.name().lower()), None)
    if layout is None:
        return None
    apply_layout_fonts(layout)
    t = job["texts"]
    labels = [i for i in layout.items() if isinstance(i, QgsLayoutItemLabel)]
    for lab in labels:
        txt = lab.text().strip()
        if txt.upper().startswith("DROUGHT MONITORING"):
            fit_label_box(lab, "EL NIÑO\nVULNERABILITY\nINDEX – CAR")
        elif txt == "March 2027" or re.fullmatch(r"[A-Za-z]+ 20\d\d", txt):
            fit_label(lab, t["period"])
        elif txt.startswith("(for "):
            lab.setText(t["issued"])
        elif txt.startswith("Note:"):
            lab.setText(t["note"])
        elif txt.startswith("Maps from"):
            lab.setText(t["source_short"])
        elif txt.startswith("Disclaimer"):
            lab.setText(t["disclaimer"])
    for pic in [i for i in layout.items() if isinstance(i, QgsLayoutItemPicture)]:
        if pic.linkedMap() is not None or pic.picturePath().lower().endswith(".svg"):
            continue  # north arrow (SVG from QGIS library)
        base = os.path.basename(pic.picturePath().replace("\\", "/"))
        local = os.path.join(job["logo_dir"], base)
        if os.path.exists(local):
            pic.setPicturePath(local)
        else:
            pic.setVisibility(False)
    for leg in [i for i in layout.items() if isinstance(i, QgsLayoutItemLegend)]:
        configure_legend(leg, target, nodata, job, label_size=10)
    for m in [i for i in layout.items() if isinstance(i, QgsLayoutItemMap)]:
        m.setLayers([])
        m.setKeepLayerSet(False)
    return layout


def fit_label(lab, text):
    """Set text and shrink the label's font until a single line fits the item width."""
    fmt = lab.textFormat()
    width_mm = lab.sizeWithUnits().width()
    size = fmt.size()
    font = fmt.font()
    while size > 6:
        font.setPointSizeF(size)
        width_px = QFontMetricsF(font).horizontalAdvance(text)  # pixels at the screen's logical dpi (96)
        if width_px * 25.4 / 96.0 <= width_mm * 0.95:
            break
        size -= 0.5
    fmt.setSize(size)
    lab.setTextFormat(fmt)
    lab.setText(text)


def fit_label_box(lab, text):
    """Set a multi-line text and shrink the font until every line fits the width and all lines the height."""
    fmt = lab.textFormat()
    w_mm, h_mm = lab.sizeWithUnits().width(), lab.sizeWithUnits().height()
    size = fmt.size()
    font = QFont(fmt.font())
    lines = text.split("\n")
    while size > 8:
        font.setPointSizeF(size)
        fm = QFontMetricsF(font)
        width = max(fm.horizontalAdvance(t) for t in lines) * 25.4 / 96
        height = fm.lineSpacing() * len(lines) * 25.4 / 96
        if width <= w_mm * 0.92 and height <= h_mm * 0.95:
            break
        size -= 0.5
    fmt.setSize(size)
    lab.setTextFormat(fmt)
    lab.setText(text)


def configure_legend(leg, target, nodata, job, label_size=None):
    leg.setAutoUpdateModel(False)
    # edit the model's own root group: a Python-owned QgsLayerTree would be garbage-collected
    root = leg.model().rootGroup()
    root.removeAllChildren()
    root.addLayer(target)
    if nodata is not None:
        root.addLayer(nodata)
    leg.setTitle(job["texts"].get("legend_title", "LEGEND"))
    for lyr_node in root.findLayers():
        if lyr_node.layer() is target:
            lyr_node.setName("Vulnerability class (ENVI)")
        else:
            QgsLegendRenderer.setNodeLegendStyle(lyr_node, QgsLegendStyle.Hidden)
    if label_size:
        for style in (QgsLegendStyle.SymbolLabel, QgsLegendStyle.Subgroup):
            st = leg.style(style)
            fmt = st.textFormat()
            fmt.setSize(label_size if style == QgsLegendStyle.SymbolLabel else label_size + 1)
            st.setTextFormat(fmt)
            leg.setStyle(style, st)
        leg.setSymbolHeight(5.5)
        leg.setSymbolWidth(9)
    leg.updateLegend()
    leg.adjustBoxSize()


def add_label(layout, text, x, y, w, h, size, bold=False, color="30,30,30", align=Qt.AlignLeft, italic=False):
    lab = QgsLayoutItemLabel(layout)
    lab.setText(text)
    fmt = QgsTextFormat()
    f = QFont(FONT_FAMILY)
    f.setBold(bold)
    f.setItalic(italic)
    fmt.setFont(f)
    fmt.setSize(size)
    fmt.setColor(QColor(*[int(c) for c in color.split(",")]))
    lab.setTextFormat(fmt)
    lab.setHAlign(align)
    lab.attemptMove(QgsLayoutPoint(x, y, QgsUnitTypes.LayoutMillimeters))
    lab.attemptResize(QgsLayoutSize(w, h, QgsUnitTypes.LayoutMillimeters))
    layout.addLayoutItem(lab)
    return lab


def build_qpt_layout(project, job, target, nodata):
    """Compact layout from the .qpt (map + north arrow + scale bar) extended with title, legend, notes."""
    layout = QgsPrintLayout(project)
    layout.initializeDefaults()
    doc = QDomDocument()
    with open(job["qpt"], encoding="utf-8") as f:
        doc.setContent(f.read())
    layout.loadFromTemplate(doc, QgsReadWriteContext(), True)
    layout.setName("ENVI compact")
    apply_layout_fonts(layout)
    top, bottom = 24.0, 50.0
    page = layout.pageCollection().page(0)
    w = page.pageSize().width()
    h = page.pageSize().height()
    page.setPageSize(QgsLayoutSize(w, h + top + bottom, QgsUnitTypes.LayoutMillimeters))
    for it in list(layout.items()):
        if it is page or isinstance(it, QgsLayoutItemPage) or not hasattr(it, "positionWithUnits"):
            continue
        p = it.positionWithUnits()
        it.attemptMove(QgsLayoutPoint(p.x(), p.y() + top, QgsUnitTypes.LayoutMillimeters))
    t = job["texts"]
    add_label(layout, t["title"], 8, 5, w - 16, 9, 15, bold=True, color="11,83,47")
    add_label(layout, t["subtitle"], 8, 14, w - 16, 7, 9, color="60,60,60")
    leg = QgsLayoutItemLegend(layout)
    layout.addLayoutItem(leg)
    for m in [i for i in layout.items() if isinstance(i, QgsLayoutItemMap)]:
        leg.setLinkedMap(m)
    leg.attemptMove(QgsLayoutPoint(8, h + top + 1, QgsUnitTypes.LayoutMillimeters))
    leg.setColumnCount(2)
    leg.setSplitLayer(True)
    leg.setEqualColumnWidth(False)
    configure_legend(leg, target, nodata, job, label_size=7.5)
    st = leg.style(QgsLegendStyle.Title)
    fmt = st.textFormat()
    fmt.setSize(10)
    st.setTextFormat(fmt)
    leg.setStyle(QgsLegendStyle.Title, st)
    leg.setSymbolHeight(4)
    leg.setSymbolWidth(7)
    leg.updateLegend()
    QgsLayoutExporter(layout).renderPageToImage(0, QSize(300, 500))  # legend sizes itself on first paint
    leg.adjustBoxSize()
    log(f"legend size {leg.sizeWithUnits().width():.1f}x{leg.sizeWithUnits().height():.1f} mm")
    y = h + top + 2 + leg.sizeWithUnits().height() + 2
    add_label(layout, t["note"], 8, y, w - 16, 9, 6.5, color="50,50,50")
    add_label(layout, t["source"].replace("\n", " · "), 8, y + 9, w - 16, 9, 6.5, italic=True, color="80,80,80")
    page.setPageSize(QgsLayoutSize(w, y + 20, QgsUnitTypes.LayoutMillimeters))
    for sb in [i for i in layout.items() if isinstance(i, QgsLayoutItemScaleBar)]:
        sb.update()
    return layout


def export_layout(layout, job, png_only=False, trial=False):
    """Export PNG (+ PDF). Returns the label positions of the main map item.

    ``trial=True`` renders a quick low-resolution PNG to a temporary file (label placement is resolution
    independent: label sizes are in points/mm of the page)."""
    ex = QgsLayoutExporter(layout)
    img = QgsLayoutExporter.ImageExportSettings()
    img.dpi = 150 if trial else job.get("dpi", 300)
    target = job["out_png"] + ".trial.png" if trial else job["out_png"]
    r1 = ex.exportToImage(target, img)
    if trial and os.path.exists(target):
        os.remove(target)
    lr = ex.labelingResults()
    results = extract_labels(next(iter(lr.values()), None)) if lr else None
    if png_only:
        if r1 != QgsLayoutExporter.Success:
            raise RuntimeError(f"Layout export failed (png={r1})")
        return results
    pdf = QgsLayoutExporter.PdfExportSettings()
    pdf.dpi = job.get("dpi", 300)
    pdf.rasterizeWholeImage = False
    r2 = ex.exportToPdf(job["out_pdf"], pdf)
    if r1 != QgsLayoutExporter.Success or r2 != QgsLayoutExporter.Success:
        raise RuntimeError(f"Layout export failed (png={r1}, pdf={r2})")
    return results


def map_only_settings(job, prov_layer_extent):
    ext = QgsRectangle(prov_layer_extent)
    # leave room for labels that spill past the region outline
    dx, dy = ext.width() * 0.16, ext.height() * 0.015
    ext.set(ext.xMinimum() - dx, ext.yMinimum() - dy, ext.xMaximum() + dx, ext.yMaximum() + dy)
    hpx = job.get("map_only_height", 2400)
    dpi = job.get("map_only_dpi", 225)
    wpx = int(hpx * ext.width() / ext.height())
    return ext, wpx, hpx, dpi, ext.width() / (wpx / dpi * 25.4)


def export_map_only(project, job, prov_layer_extent, trial=False):
    root = project.layerTreeRoot()
    layers = [n.layer() for n in root.findLayers() if n.isVisible() and n.layer() is not None]
    ms = QgsMapSettings()
    ms.setLayers(layers)
    ms.setDestinationCrs(project.crs())
    ext, wpx, hpx, dpi, _ = map_only_settings(job, prov_layer_extent)
    if trial:   # same label/map size ratio at 40 % of the pixels
        wpx, hpx, dpi = int(wpx * 0.4), int(hpx * 0.4), dpi * 0.4
    ms.setOutputSize(QSize(wpx, hpx))
    ms.setOutputDpi(dpi)
    ms.setExtent(ext)
    ms.setBackgroundColor(QColor(255, 255, 255, 0))
    ms.setFlag(QgsMapSettings.Antialiasing, True)
    ms.setFlag(QgsMapSettings.DrawLabeling, True)
    job_r = QgsMapRendererParallelJob(ms)
    job_r.start()
    job_r.waitForFinished()
    if not trial:
        job_r.renderedImage().save(job["out_map_only"], "PNG")
    return extract_labels(job_r.takeLabelingResults())


def main(job_path):
    with open(job_path, encoding="utf-8") as f:
        job = json.load(f)
    app = QgsApplication([], False)
    app.initQgis()
    global FONT_FAMILY
    FONT_FAMILY = job.get("font_family", FONT_FAMILY)
    register_fonts(job.get("font_dir"))
    try:
        tmp = tempfile.mkdtemp(prefix="envi_qgis_")
        project = QgsProject.instance()
        if not project.read(patched_project(job, tmp)):
            raise RuntimeError("Could not read QGIS project")
        log(f"project loaded: {len(project.mapLayers())} layers")
        target, nodata = setup_layers(project, job)
        if job.get("layout") == "qpt":
            layout = build_qpt_layout(project, job, target, nodata)
        else:
            layout = fill_qgz_layout(project, job, target, nodata) or build_qpt_layout(project, job, target, nodata)
        muni = next((l for l in project.mapLayers().values() if "layername=municipalities" in l.source()
                     and not l.subsetString()), None)
        prov_lab = next((l for l in project.mapLayers().values() if "layername=provinces" in l.source()
                         and l.labelsEnabled()), None)
        base_size = muni.labeling().settings().format().size() if muni is not None and muni.labelsEnabled() else None
        map_item = next(i for i in layout.items() if isinstance(i, QgsLayoutItemMap))
        layout_upm = lambda: map_item.extent().width() / map_item.rect().width()  # noqa: E731  map units per mm
        rep_layout, size, placed, pscale = with_label_retries(
            project, muni, prov_lab, lambda: export_layout(layout, job, png_only=True, trial=True),
            "layout", base_size, layout_upm)
        rep_layout["final_300dpi"] = final_export(project, muni, prov_lab, size, placed,
                                                  lambda: export_layout(layout, job), layout_upm, "layout", pscale)
        prov = next((l for l in project.mapLayers().values() if "layername=provinces" in l.source()), target)
        configure_labels(project, muni, prov_lab)   # back to the template sizes for the map-only image
        rep_map, size, placed, pscale = with_label_retries(
            project, muni, prov_lab, lambda: export_map_only(project, job, prov.extent(), trial=True),
            "map-only", base_size, lambda: map_only_settings(job, prov.extent())[4])
        rep_map["final"] = final_export(project, muni, prov_lab, size, placed,
                                        lambda: export_map_only(project, job, prov.extent()),
                                        lambda: map_only_settings(job, prov.extent())[4], "map-only", pscale)
        if job.get("out_label_report"):
            with open(job["out_label_report"], "w", encoding="utf-8") as f:
                json.dump({"layout": rep_layout, "map_only": rep_map}, f, indent=1)
    finally:
        app.exitQgis()


if __name__ == "__main__":
    main(sys.argv[1])
