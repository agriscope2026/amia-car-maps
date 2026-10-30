"""Self-sufficiency level (SSL) of rice and corn per province, read from the activities workbook.

The El Niño action-plan workbook (the same file as the activities list) has a sheet "PROJECTED PDN LOSS AND SSL"
with one block per commodity ("RICE COMMODITY", "CORN COMMODITY"): per province the SSL of the base year, the
standing crop at risk (reproductive stage, ha), the estimated potential yield loss (MT), harvested and target
production, the estimated production, the adjusted and final SSL and the Effect to SSL (% reduction). The
action-plan map shows the **SELF SUFFICIENCY LEVEL (SSL) (%)** of the base year; the projected loss (final SSL, effect)
is shown beside it when the file could compute it. Nothing is at a fixed cell: the sheet and each block are found by their header texts, so rows
and columns may move. Formulas are read from the values Excel saved; when a cached value is missing the effect is
recomputed as SSL − final SSL. SSL cells formatted as % hold fractions (1.4349 = 143.49 %) and are returned in %.
"""
from __future__ import annotations

import io
import re
from datetime import datetime

from . import reference
from .envi.io_loader import REGION_NAMES, clean_name

SHEET_HINTS = ("SSL", "SELF SUFFICIENCY", "PDN LOSS")
CROPS = {"rice": "RICE", "corn": "CORN"}
# field → header fragments (upper case, single spaces), most specific first: each header cell belongs to the first
# field it matches ("Est. Production ((Annual Target − EPYL) + harvested)" is the production, not the harvest)
FIELDS = {
    "effect": ("EFFECT TO SSL", "% REDUCTION"),
    "final_ssl": ("FINAL SSL",),
    "adjusted_ssl": ("ADJUSTED SSL",),
    "production_mt": ("EST. PRODUCTION", "EST PRODUCTION", "ESTIMATED PRODUCTION"),
    "yield_loss_mt": ("POTENTIAL YIELD LOSS", "YIELD LOSS"),
    "standing_ha": ("REPRODUCTIVE", "STANDING CROP"),
    "harvested_mt": ("HARVESTED",),
    "target_mt": ("ANNUAL TARGET",),
    "ssl": ("SELF SUFFICIENCY LEVEL", "SSL (%) (20", "BASE SSL"),
}
PERCENT_FIELDS = ("ssl", "adjusted_ssl", "final_ssl", "effect")
ERROR_RE = re.compile(r"^#(DIV/0!|N/A|VALUE!|REF!|NAME\?|NUM!|NULL!)")


def _txt(v) -> str:
    return re.sub(r"\s+", " ", str(v)).strip().upper() if v is not None else ""


def _find_sheet(wb):
    for ws in wb.worksheets:
        if any(h in ws.title.upper() for h in SHEET_HINTS):
            return ws
    for ws in wb.worksheets:                 # any sheet with an "EFFECT TO SSL" header
        for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, 120)):
            if any("EFFECT TO SSL" in _txt(c.value) for c in row):
                return ws
    return None


def _blocks(ws) -> dict[str, int]:
    """{'rice': header row, 'corn': header row} – the row with 'RICE COMMODITY' / 'CORN COMMODITY'."""
    out = {}
    for row in ws.iter_rows(min_row=1, max_row=ws.max_row):
        for c in row:
            t = _txt(c.value)
            for crop, word in CROPS.items():
                if crop not in out and word in t and ("COMMODITY" in t or t == word):
                    out[crop] = c.row
    return out


def _columns(ws, top: int) -> tuple[dict[str, int], int | None, str]:
    """Columns of a block from its 3–4 header rows (merged headers repeat their text only in the first cell)."""
    cols: dict[str, int] = {}
    prov_col, as_of = None, ""
    for r in range(top, min(top + 4, ws.max_row) + 1):
        for c in ws[r]:
            t = _txt(c.value)
            if not t:
                continue
            if prov_col is None and t == "PROVINCE":
                prov_col = c.column
            m = re.search(r"AS OF ([A-Z]+ \d{1,2}(?:,? \d{4})?)", t)
            if m and not as_of:
                as_of = m.group(1).title()
            for field, frags in FIELDS.items():
                if any(f in t for f in frags):
                    # "Standing crop" spans two columns: its sub-header "Reproductive" names the area column
                    if field == "standing_ha" and "REPRODUCTIVE" not in t:
                        break
                    if field not in cols and c.column not in cols.values():
                        cols[field] = c.column
                    break
    if "standing_ha" not in cols:                       # no sub-header: use the "Standing crop" column itself
        for r in range(top, min(top + 4, ws.max_row) + 1):
            for c in ws[r]:
                if "STANDING CROP" in _txt(c.value):
                    cols["standing_ha"] = c.column
    return cols, prov_col or 1, as_of


def _value(cell) -> tuple[float | None, bool]:
    """(number, is an Excel error such as #DIV/0!)."""
    v = cell.value
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v), False
    if isinstance(v, str):
        if ERROR_RE.match(v.strip()):
            return None, True
        s = v.replace(",", "").replace("%", "").strip()
        try:
            return float(s) / (100 if v.strip().endswith("%") else 1), False
        except ValueError:
            return None, False
    return None, False


def _province(v, provs: set[str]) -> str | None:
    c = clean_name(v)
    if c in ("CAR",) or c in REGION_NAMES:
        return "CAR"
    return c if c in provs else None


def parse(src, filename: str) -> dict | None:
    """→ None when the workbook has no SSL sheet, else {ok, as_of_label, crops: {rice: {...}, corn: {...}}, warnings}."""
    if not filename.lower().endswith((".xlsx", ".xlsm")):
        return None
    import openpyxl
    try:
        raw = src if isinstance(src, (bytes, bytearray)) else open(src, "rb").read()
        values = openpyxl.load_workbook(io.BytesIO(raw), data_only=True)
    except Exception:  # noqa: BLE001 – not a readable workbook: the activities parser reports it
        return None
    ws = _find_sheet(values)
    if ws is None:
        return None
    warnings: list[str] = []
    provs = reference.gazetteer().province_cleans
    labels = dict(zip(reference.gazetteer().prov.province, reference.gazetteer().prov.label))
    blocks = _blocks(ws)
    out = {"type": "ssl", "sheet": ws.title, "file": filename, "crops": {}, "warnings": warnings,
           "parsed_at": datetime.now().isoformat(timespec="seconds")}
    for crop in CROPS:
        if crop not in blocks:
            warnings.append(f"{crop.title()}: no “{CROPS[crop]} COMMODITY” table found in sheet “{ws.title}”.")
            continue
        top = blocks[crop]
        cols, pcol, as_of = _columns(ws, top)
        if "ssl" not in cols:
            warnings.append(f"{crop.title()}: the “SELF SUFFICIENCY LEVEL (SSL) (%)” column was not found.")
            continue
        # SSL figures stored as fractions when their cells are formatted as % (1.4349 = 143.49 %)
        pct_fmt = {f: "%" in (ws.cell(top + 3, cols[f]).number_format or "") for f in PERCENT_FIELDS if f in cols}
        ssl_year = ""
        if "ssl" in cols:
            for r in range(top, top + 4):
                m = re.search(r"\((20\d\d)\)", _txt(ws.cell(r, cols["ssl"]).value))
                if m:
                    ssl_year = m.group(1)
        rows: dict[str, dict] = {}
        errors: list[str] = []      # provinces without the projected loss (final SSL / effect)
        no_ssl: list[str] = []      # provinces without an SSL: no data on the map
        r = top + 1
        started = False
        while r <= ws.max_row and r < top + 40:
            name = ws.cell(r, pcol).value
            key = _province(name, provs) if name is not None else None
            if key is None:
                if started:
                    break                                     # first row after the table that is not a province
                r += 1
                continue
            started = True
            rec: dict = {"label": "CAR" if key == "CAR" else labels.get(key, str(name).strip())}
            for field, col in cols.items():
                v, err = _value(ws.cell(r, col))
                if field in PERCENT_FIELDS and v is not None:
                    frac = pct_fmt.get(field) or abs(v) <= 10 and pct_fmt.get("ssl", False)
                    v = v * 100 if frac else v
                rec[field] = None if v is None else round(v, 4)
                if err and field == "effect":
                    rec["effect_error"] = str(ws.cell(r, col).value).strip()
            if rec.get("effect") is None and rec.get("ssl") is not None and rec.get("final_ssl") is not None:
                rec["effect"] = round(rec["ssl"] - rec["final_ssl"], 4)  # no cached value: recompute
            if key != "CAR" and rec.get("ssl") is None:
                no_ssl.append(rec["label"])
            elif key != "CAR" and rec.get("effect") is None:
                errors.append(rec["label"])
            rows[key] = rec
            if key == "CAR":
                break
            r += 1
        car = rows.pop("CAR", None)
        missing = sorted(labels[p] for p in provs if p not in rows)
        if missing:
            warnings.append(f"{crop.title()}: no row for {', '.join(missing)} – shown as “no data”.")
        if no_ssl:
            warnings.append(f"{crop.title()}: no SSL for {', '.join(no_ssl)} – shown as “no data” on the map.")
        if errors:
            why = next((v.get("effect_error") for v in rows.values() if v.get("effect_error")), "")
            warnings.append(f"{crop.title()}: the projected loss (final SSL, Effect to SSL) could not be read for "
                            f"{', '.join(errors)}"
                            + (f" (the file shows {why} – fill the HARVESTED and annual target columns and the "
                               f"{crop} Total Production Utilization by province that the formula divides by)"
                               if why else "") + ". The map still shows their SSL.")
        neg = [v["label"] for v in rows.values() if (v.get("final_ssl") or 0) < 0]
        if neg:
            warnings.append(f"{crop.title()}: the final SSL is below 0 % for {', '.join(neg)} – check the figures.")
        out["crops"][crop] = {"provinces": rows, "car": car, "standing_as_of": as_of, "ssl_year": ssl_year,
                              "ok": any(v.get("ssl") is not None for v in rows.values())}
    out["ok"] = any(c["ok"] for c in out["crops"].values())
    if not out["ok"]:
        warnings.append("No SSL values could be read – the SSL map is not updated.")
    return out


# ------------------------------------------------------------------ template ---

TEMPLATE_PROVINCES = ["ABRA", "APAYAO", "BENGUET", "IFUGAO", "KALINGA", "MP"]
TEMPLATE_SHEET = "PROJECTED PDN LOSS AND SSL"


def add_template_sheet(wb) -> None:
    """Add the SSL sheet to the activities template: per crop a 'Total Production Utilization by province' table and
    the commodity block with the same formulas as the DA-RFO-CAR workbook (yield loss = standing ha × t/ha, production
    = (annual target − yield loss + harvested) × 65.4 % milling recovery, adjusted SSL = production ÷ utilization,
    final SSL = SSL − adjusted SSL, Effect to SSL = SSL − final SSL). Enter the yellow cells; Excel does the rest."""
    from openpyxl.styles import Alignment, Font, PatternFill
    ws = wb.create_sheet(TEMPLATE_SHEET)
    bold, wrap = Font(bold=True), Alignment(wrap_text=True, vertical="top")
    fill = PatternFill("solid", fgColor="FFF2CC")
    ws["A1"] = ("Self-sufficiency (SSL) for the action-plan map. Fill the yellow cells: SSL of the base year (as %), "
                "standing crop at the reproductive stage (ha), harvested and annual target (MT), and the total production "
                "utilization per province. The map shows the column “Effect to SSL in (% reduction)”.")
    ws["A1"].alignment = wrap
    ws.merge_cells("A1:F2")
    for crop, top, util_top, t_ha in (("RICE", 12, 4, 3.5), ("CORN", 32, 24, 5)):
        ws.cell(util_top - 1, 8, f"Total Production Utilization by province ({crop.lower()}, MT)").font = bold
        for i, p in enumerate(TEMPLATE_PROVINCES):
            ws.cell(util_top + i, 8, p.title() if p != "MP" else "MP")
            ws.cell(util_top + i, 9).fill = fill
        heads = [(1, "PROVINCE"), (2, f"{crop} COMMODITY"), (7, "Est.  Production (MT)\n ((Annual Target-EPYL)+harvested)"
                 "*65.4% milling recovery)"), (8, "Adjusted SSL (%) from PYL"), (10, "Effect to SSL in  (% reduction)")]
        for col, text in heads:
            ws.cell(top, col, text).font = bold
        sub = [(2, "SELF SUFFICIENCY LEVEL (SSL) (%) (2024)"), (3, "Standing Crop (ha.) (as of October 15)"),
               (5, "HARVESTED (MT) 1st Sem"), (6, "CY 2026 Annual Target (MT)")]
        for col, text in sub:
            ws.cell(top + 1, col, text).font = bold
        for col, text in ((3, "Reproductive (from newlyplanted to vegetative)"), (4, "Est Potential Yield Loss (MT)"),
                          (8, "(Total Production Utilization/EST Production"), (9, "Final SSL")):
            ws.cell(top + 2, col, text).font = bold
        for r in range(top, top + 3):
            for c in range(1, 11):
                ws.cell(r, c).alignment = wrap
        for i, p in enumerate(TEMPLATE_PROVINCES):
            r = top + 3 + i
            ws.cell(r, 1, p)
            for c in (2, 3, 5, 6):
                ws.cell(r, c).fill = fill
            ws.cell(r, 2).number_format = "0.00%"
            ws.cell(r, 4, f"=C{r}*{t_ha}")
            ws.cell(r, 7, f"=((F{r}-D{r})+E{r})*65.4%")
            ws.cell(r, 8, f'=IFERROR(G{r}/I{util_top + i},"")')
            ws.cell(r, 9, f'=IFERROR(B{r}-H{r},"")')
            ws.cell(r, 10, f'=IFERROR(B{r}-I{r},"")')
            for c in (8, 9, 10):
                ws.cell(r, c).number_format = "0.00%"
    for col, w in zip("ABCDEFGHIJ", (14, 16, 16, 14, 14, 14, 20, 18, 12, 16)):
        ws.column_dimensions[col].width = w
