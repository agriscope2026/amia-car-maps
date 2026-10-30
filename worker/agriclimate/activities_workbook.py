"""The DATA, LISTS and README sheets of the El Niño action-plan workbook (the activities upload).

DATA has one row per activity with dropdowns for the coded columns. Their values come from the LISTS sheet (named
ranges, so new values can be added at the bottom of a list): provinces, the municipalities of the province chosen in
the same row (dependent dropdown), status, map, category, beneficiary type, unit of measure, fund source, office and
the usual activities. Free-text columns (municipality, activity, category, office …) warn on a value that is not in
the list but accept it after confirmation – several places in one cell ("Bangued; Tayum") stay possible; status, map
and beneficiary type only take listed values; numbers and dates are checked. Used by the template download and to
tidy an existing workbook (the PROJECTED PDN LOSS AND SSL sheet is left as it is).
"""
from __future__ import annotations

from datetime import date, datetime

from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.workbook.defined_name import DefinedName
from openpyxl.worksheet.datavalidation import DataValidation

from . import reference

# (header, width, help shown when a cell of the column is selected)
COLUMNS = [
    ("PROVINCE", 18, "Province of the activity. All = the whole CAR. Several provinces: Ifugao; Kalinga"),
    ("MUNICIPALITY", 22, "Municipality or city of the province chosen in column A. All = the whole province. "
                         "Several: Bangued; Tayum"),
    ("BARANGAY", 18, "Optional: barangay(s) or sitio"),
    ("ACTIVITY", 46, "What is done – choose a usual activity or type a new one"),
    ("CATEGORY", 32, "Type of activity – choose from the list or type a new one"),
    ("STATUS", 14, "To conduct, Ongoing, Completed or Postponed"),
    ("MAP", 16, "The map it responds to. Blank = General (shown with every map)"),
    ("NO_OF_UNITS", 12, "How many units are delivered (numbers only), e.g. 3"),
    ("UNIT_OF_MEASURE", 16, "What one unit is, e.g. unit, bag, kg, head, project"),
    ("START_DATE", 13, "Start date (YYYY-MM-DD)"),
    ("END_DATE", 13, "End date (YYYY-MM-DD), on or after the start"),
    ("BENEFICIARY_TYPE", 20, "Individual farmers, or Farmer group (FCA) = farmer cooperative or association"),
    ("BENEFICIARIES", 14, "How many: number of farmers, or number of farmer groups (FCAs)"),
    ("BUDGET_PHP", 16, "Budget in pesos, in full (e.g. 2837423, not 2,837.423 thousand)"),
    ("FUND_SOURCE", 18, "Where the funds come from, e.g. GAA, QRF, LGU"),
    ("OFFICE", 26, "Implementing office or unit"),
    ("REMARKS", 44, "Anything else"),
]
HEAD = {name: i + 1 for i, (name, _, _) in enumerate(COLUMNS)}

STATUSES = ["To conduct", "Ongoing", "Completed", "Postponed"]
MAPS = ["General", "ENVI", "Drought", "10-day rainfall", "Seasonal rainfall", "Typhoon"]
BENEFICIARY_TYPES = ["Individual farmers", "Farmer group (FCA)"]
CATEGORIES = ["Distribution of Small Scale Irrigation Project (SSIP)", "Distribution of inputs", "Infrastructure",
              "Water management", "Training", "Advisory", "Insurance enrolment", "Insurance pay out",
              "Livestock and poultry support", "Other"]
UNITS = ["unit", "set", "project", "bag", "sack", "kg", "liter", "head", "hectare", "meter", "piece", "farmer"]
FUND_SOURCES = ["GAA (regular)", "QRF (Quick Response Fund)", "LGU", "Special project", "Other"]
OFFICES = ["DA-RFO-CAR AMIA", "DA-RFO-CAR HVCDP", "DA-RFO-CAR Rice Program", "DA-RFO-CAR Corn Program",
           "DA-RFO-CAR Livestock Program", "DA-RFO-CAR OAP", "ATI-CAR", "BSWM", "NIA", "PCIC", "PAO", "MAO"]
ACTIVITIES = ["Provision of PISOS", "Cistern", "Solar powered irrigation system", "Spring Development Project (SDP)",
              "Distribution of hybrid rice seeds", "Distribution of hybrid yellow corn seeds",
              "Distribution of drought-tolerant rice seeds", "Indemnification of PCIC insured farmers for losses due to "
              "drought-related damages", "PCIC crop insurance enrolment drive", "Farm weather advisory briefing",
              "Submission of weekly localized weather data", "Construction of diversion dam"]

NOTES = [
    "El Niño action plan – one row per activity in sheet DATA. Required: PROVINCE or MUNICIPALITY, ACTIVITY and STATUS.",
    "Use the dropdowns: they come from sheet LISTS. To add a value (a new office, activity or category), type it at "
    "the bottom of its list in LISTS – it then appears in the dropdown. A value typed directly in DATA that is not in "
    "the list is accepted after a warning.",
    "MUNICIPALITY lists the towns of the province chosen in column A. All = the whole province (or the whole CAR when "
    "PROVINCE is All too). Several places in one activity stay one row: separate them with ; (Bangued; Tayum).",
    "STATUS: To conduct (planned, for construction, for distribution, for release …), Ongoing, Completed or Postponed.",
    "MAP: the map the activity responds to – ENVI, Drought, 10-day rainfall, Seasonal rainfall or Typhoon. Blank = "
    "General (shown with every map).",
    "NO_OF_UNITS and UNIT_OF_MEASURE: how many of what, e.g. 3 unit (PISOS) or 1 295 bag (seeds).",
    "BENEFICIARY_TYPE: Individual farmers or Farmer group (FCA – farmer cooperative or association); BENEFICIARIES: "
    "how many farmers, or how many FCAs.",
    "BUDGET_PHP: in full pesos (2837423, not 2,837.423 thousand). FUND_SOURCE, BARANGAY and REMARKS are optional.",
    "Dates: YYYY-MM-DD (or pick an Excel date). The end date cannot be before the start date.",
    "Red cells in DATA: something required is missing in a row that has an activity.",
    "The sheet PROJECTED PDN LOSS AND SSL (rice and corn self-sufficiency per province) is read from the same file for "
    "the SSL map of the action plan.",
]

GREEN = "0B6237"
THIN = Side(style="thin", color="D5DBD7")


def _name(label: str) -> str:
    """Excel name of a province's municipality list: 'Mountain Province' → 'Mountain_Province'."""
    return label.replace(" ", "_").replace(".", "")


def _add_name(wb, name: str, ref: str) -> None:
    dn = DefinedName(name, attr_text=ref)
    try:
        wb.defined_names[name] = dn              # openpyxl ≥ 3.1
    except TypeError:
        wb.defined_names.append(dn)


def _lists_sheet(wb, extra: dict[str, list[str]]) -> None:
    """LISTS: one column per dropdown, each a named range of 300 rows (new values can be added at the bottom)."""
    ws = wb.create_sheet("LISTS")
    g = reference.gazetteer_table()
    provinces = sorted(g.province_label.unique())
    columns: list[tuple[str, str, list[str]]] = [
        ("PROVINCES", "PROVINCE", ["All"] + provinces),
        ("STATUS_LIST", "STATUS", STATUSES),
        ("MAP_LIST", "MAP", MAPS),
        ("BENEFICIARY_LIST", "BENEFICIARY_TYPE", BENEFICIARY_TYPES),
        ("CATEGORY_LIST", "CATEGORY", _merge(CATEGORIES, extra.get("CATEGORY"))),
        ("ACTIVITY_LIST", "ACTIVITY", _merge(ACTIVITIES, extra.get("ACTIVITY"))),
        ("UNIT_LIST", "UNIT_OF_MEASURE", UNITS),
        ("FUND_LIST", "FUND_SOURCE", FUND_SOURCES),
        ("OFFICE_LIST", "OFFICE", _merge(OFFICES, extra.get("OFFICE"))),
        ("All", "MUNICIPALITY (all CAR)", ["All"] + sorted(g.label)),
    ]
    for p in provinces:
        columns.append((_name(p), f"MUNICIPALITY – {p}", ["All"] + sorted(g.label[g.province_label == p])))
    ws["A1"] = "Values of the dropdowns in sheet DATA. Add a new value at the bottom of its column."
    ws["A1"].font = Font(italic=True, color="555555")
    for c, (name, title, values) in enumerate(columns, start=1):
        head = ws.cell(2, c, title)
        head.font = Font(bold=True, color="FFFFFF")
        head.fill = PatternFill("solid", fgColor=GREEN)
        head.alignment = Alignment(wrap_text=True, vertical="top")
        for r, v in enumerate(values, start=3):
            ws.cell(r, c, v)
        col = get_column_letter(c)
        _add_name(wb, name, f"LISTS!${col}$3:${col}$302")
        ws.column_dimensions[col].width = max(16, min(48, max(len(str(v)) for v in values + [title]) + 2))
    ws.row_dimensions[2].height = 32
    ws.freeze_panes = "A3"


def _merge(base: list[str], more: list[str] | None) -> list[str]:
    out = list(base)
    seen = {x.lower() for x in out}
    for v in more or []:
        if v and v.lower() not in seen:
            out.append(v)
            seen.add(v.lower())
    return out


def _validations(ws, last: int) -> None:
    def add(col: str, dv: DataValidation, prompt: str):
        dv.promptTitle = col.replace("_", " ").title()[:32]
        dv.prompt = prompt[:255]
        dv.showInputMessage = True
        dv.showErrorMessage = True
        ws.add_data_validation(dv)
        letter = get_column_letter(HEAD[col])
        dv.add(f"{letter}2:{letter}{last}")

    help_ = {name: h for name, _, h in COLUMNS}

    def lst(col, source, strict, **kw):
        dv = DataValidation(type="list", formula1=source, allow_blank=True,
                            errorStyle="stop" if strict else "warning", **kw)
        dv.errorTitle = "Not in the list"
        dv.error = ("Choose a value from the list." if strict else
                    "This value is not in the list (sheet LISTS). Keep it anyway?")
        add(col, dv, help_[col])

    lst("PROVINCE", "PROVINCES", False)
    a = get_column_letter(HEAD["PROVINCE"])
    lst("MUNICIPALITY", f'INDIRECT(IF(OR(${a}2="",${a}2="All"),"All",SUBSTITUTE(SUBSTITUTE(${a}2," ","_"),".","")))',
        False)
    lst("ACTIVITY", "ACTIVITY_LIST", False)
    lst("CATEGORY", "CATEGORY_LIST", False)
    lst("STATUS", "STATUS_LIST", True)
    lst("MAP", "MAP_LIST", True)
    lst("UNIT_OF_MEASURE", "UNIT_LIST", False)
    lst("BENEFICIARY_TYPE", "BENEFICIARY_LIST", True)
    lst("FUND_SOURCE", "FUND_LIST", False)
    lst("OFFICE", "OFFICE_LIST", False)
    for col, kind in (("NO_OF_UNITS", "decimal"), ("BENEFICIARIES", "whole"), ("BUDGET_PHP", "decimal")):
        dv = DataValidation(type=kind, operator="greaterThanOrEqual", formula1="0", allow_blank=True)
        dv.errorTitle, dv.error = "Numbers only", "Enter a number of 0 or more (no text, no commas)."
        add(col, dv, help_[col])
    s = get_column_letter(HEAD["START_DATE"])
    for col in ("START_DATE", "END_DATE"):
        dv = DataValidation(type="date", operator="between", formula1="DATE(2020,1,1)", formula2="DATE(2035,12,31)",
                            allow_blank=True)
        dv.errorTitle, dv.error = "Date", "Enter a date (YYYY-MM-DD) between 2020 and 2035."
        if col == "END_DATE":   # end on or after the start
            e = get_column_letter(HEAD["END_DATE"])
            dv = DataValidation(type="custom", formula1=f'OR({e}2="",{s}2="",{e}2>={s}2)', allow_blank=True)
            dv.errorTitle, dv.error = "End date", "The end date cannot be before the start date (or is not a date)."
        add(col, dv, help_[col])


def _required_marks(ws, last: int) -> None:
    """Red cells: a row with an activity but no status, or no province and no municipality."""
    red = PatternFill("solid", fgColor="F8D0CC")
    act, st = get_column_letter(HEAD["ACTIVITY"]), get_column_letter(HEAD["STATUS"])
    pv, mu = get_column_letter(HEAD["PROVINCE"]), get_column_letter(HEAD["MUNICIPALITY"])
    ws.conditional_formatting.add(f"{st}2:{st}{last}", FormulaRule(formula=[f'AND(${act}2<>"",${st}2="")'], fill=red))
    ws.conditional_formatting.add(f"{pv}2:{mu}{last}",
                                  FormulaRule(formula=[f'AND(${act}2<>"",${pv}2="",${mu}2="")'], fill=red))


def build(wb, rows: list[dict], last: int = 1000, extra_lists: dict[str, list[str]] | None = None) -> None:
    """Add DATA (first sheet), LISTS and README to ``wb`` with ``rows`` ({header: value}) filled in."""
    ws = wb.create_sheet("DATA", 0)
    for name, width, _ in COLUMNS:
        c = ws.cell(1, HEAD[name], name)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=GREEN)
        c.alignment = Alignment(vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(HEAD[name])].width = width
    ws.row_dimensions[1].height = 30
    for r, row in enumerate(rows, start=2):
        for name, v in row.items():
            if name not in HEAD or v is None or v == "":
                continue
            cell = ws.cell(r, HEAD[name], v)
            if isinstance(v, (date, datetime)):
                cell.number_format = "yyyy-mm-dd"
            elif name == "BUDGET_PHP":
                cell.number_format = "#,##0.00"
            elif name in ("NO_OF_UNITS", "BENEFICIARIES"):
                cell.number_format = "#,##0.##"
        for name in row.get("_flags") or []:        # cells changed while tidying a workbook: to be checked
            if name in HEAD:
                ws.cell(r, HEAD[name]).fill = PatternFill("solid", fgColor="FFF2CC")
    for r in range(2, last + 1):          # dates entered later show as YYYY-MM-DD too
        for name in ("START_DATE", "END_DATE"):
            ws.cell(r, HEAD[name]).number_format = "yyyy-mm-dd"
        for name in COLUMNS:
            ws.cell(r, HEAD[name[0]]).border = Border(bottom=THIN)
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{max(2, len(rows) + 1)}"
    _validations(ws, last)
    _required_marks(ws, last)
    _lists_sheet(wb, extra_lists or {})
    rd = wb.create_sheet("README", 2)
    rd["A1"] = "README"
    rd["A1"].font = Font(bold=True, size=13)
    for i, n in enumerate(NOTES, start=2):
        rd.cell(i, 1, n).alignment = Alignment(wrap_text=True, vertical="top")
    rd.column_dimensions["A"].width = 120
