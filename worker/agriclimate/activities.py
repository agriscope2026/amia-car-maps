"""Activities (interventions) from an Excel/CSV list → rows for the activities page.

One row per activity. MUNICIPALITY is matched to the gazetteer like the map inputs (PROVINCE helps). An activity can
take place in several municipalities ("Bangued; Tayum") or provinces ("All" + "Abra; Benguet"; "All" + "All" = CAR).
The import is lenient: a missing or unreadable detail (status, map, dates, numbers, beneficiary type, an unknown town
in a list) is reported as a warning with its spreadsheet row and left empty or set to its default, and the row is
still imported. Only a row without an activity or without any place it can be put on the map is skipped (also with a
warning). The file itself is refused only when it has no ACTIVITY column, no place column or no usable row.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import pandas as pd

from . import reference
from .envi.io_loader import _identify_columns, _norm_col, clean_name, match_name, read_any
from .products.reference_layers import _NAME_COLS, _with_header_row

STATUSES = {
    "to_conduct": ["TO CONDUCT", "TO BE CONDUCTED", "PLANNED", "PLAN", "PROPOSED", "PIPELINE", "NOT YET STARTED",
                   "UPCOMING", "FOR IMPLEMENTATION", "TARGET", "TO CONSTRUCT", "FOR CONSTRUCTION", "FOR DISTRIBUTION",
                   "FOR RELEASE", "FOR PROCUREMENT", "FOR DELIVERY", "TO BE DISTRIBUTED"],
    "ongoing": ["ONGOING", "ON GOING", "ON-GOING", "IN PROGRESS", "STARTED", "IMPLEMENTING", "ACTIVE"],
    "completed": ["COMPLETED", "COMPLETE", "DONE", "FINISHED", "CONDUCTED", "ACCOMPLISHED", "IMPLEMENTED"],
    "postponed": ["POSTPONED", "DEFERRED", "CANCELLED", "CANCELED", "ON HOLD", "SUSPENDED", "DROPPED"],
}
HAZARDS = {
    "general": ["", "GENERAL", "ALL", "ALL MAPS", "ANY", "MULTI HAZARD", "MULTIHAZARD", "CLIMATE"],
    "envi": ["ENVI", "EL NINO", "EL NINO VULNERABILITY", "EL NINO VULNERABILITY INDEX", "VULNERABILITY"],
    "drought": ["DROUGHT", "DROUGHT FORECAST", "DRY SPELL"],
    "rainfall_dekad": ["10 DAY", "10 DAY RAINFALL", "10 DAY RAINFALL FORECAST", "DEKAD", "DEKADAL", "RAINFALL 10 DAY"],
    "rainfall_seasonal": ["SEASONAL", "SEASONAL RAINFALL", "SEASONAL RAINFALL FORECAST", "LA NINA", "RAINFALL",
                          "HEAVY RAINFALL", "FLOOD"],
    "tc_advisory": ["TYPHOON", "SUPER TYPHOON", "TROPICAL CYCLONE", "TC", "STORM", "TROPICAL STORM", "BAGYO",
                    "WIND SIGNAL", "TCWS", "FARM WEATHER OUTLOOK"],
}
BENEFICIARY_TYPES = {
    "individual": ["INDIVIDUAL", "INDIVIDUALS", "INDIVIDUAL FARMER", "INDIVIDUAL FARMERS", "FARMER", "FARMERS",
                   "PERSON", "PERSONS", "HOUSEHOLD", "HOUSEHOLDS", "IND"],
    "fca": ["FCA", "FCAS", "GROUP", "GROUPS", "FARMER GROUP", "FARMERS GROUP", "FARMER GROUPS", "COOPERATIVE",
            "COOPERATIVES", "COOP", "ASSOCIATION", "ASSOCIATIONS", "FARMER ASSOCIATION", "FARMERS ASSOCIATION",
            "FARMER COOPERATIVE", "FARMERS COOPERATIVE", "FARMER COOPERATIVE AND ASSOCIATION",
            "FARMER COOPERATIVES AND ASSOCIATIONS", "FARMERS COOPERATIVES AND ASSOCIATIONS", "ORGANIZATION",
            "ORGANIZATIONS", "IA", "IRRIGATORS ASSOCIATION", "GROUP FCA", "GROUP (FCA)"],
}
COLUMNS = {   # field → accepted headers (normalized: upper case, single spaces, "_" as space)
    "title": ["ACTIVITY", "ACTIVITIES", "ACTIVITY NAME", "TITLE", "INTERVENTION", "INTERVENTIONS", "PROJECT",
              "PROGRAM ACTIVITY", "PROGRAM/ACTIVITY", "PROGRAMS/ACTIVITIES", "PPA", "PAP"],
    "category": ["CATEGORY", "TYPE", "ACTIVITY TYPE", "KIND", "COMPONENT"],
    "status": ["STATUS", "ACTIVITY STATUS", "REMARKS STATUS"],
    "hazard": ["MAP", "HAZARD", "FOR MAP", "RESPONDS TO", "RESPONSE TO", "RISK"],
    "start_date": ["START DATE", "START", "DATE START", "DATE STARTED", "FROM", "DATE", "TARGET DATE", "SCHEDULE"],
    "end_date": ["END DATE", "END", "DATE END", "DATE COMPLETED", "TO", "UNTIL"],
    "units": ["NO. OF UNITS", "NO OF UNITS", "NUMBER OF UNITS", "UNITS", "UNIT COUNT", "QUANTITY", "QTY",
              "NO. OF UNIT", "NO OF UNIT"],
    "beneficiary_type": ["BENEFICIARY TYPE", "TYPE OF BENEFICIARY", "TYPE OF BENEFICIARIES", "BENEFICIARIES TYPE",
                         "BENEFICIARY", "INDIVIDUAL OR GROUP", "INDIVIDUAL/GROUP", "INDIVIDUAL / GROUP"],
    "beneficiaries": ["BENEFICIARIES", "NO OF BENEFICIARIES", "NO. OF BENEFICIARIES", "FARMERS", "NO OF FARMERS",
                      "NO. OF FARMERS", "TARGET BENEFICIARIES", "FARMER BENEFICIARIES"],
    "budget": ["BUDGET", "BUDGET PHP", "BUDGET (PHP)", "AMOUNT", "COST", "FUND", "ALLOCATION", "BUDGET_PHP"],
    "office": ["OFFICE", "IMPLEMENTING OFFICE", "IMPLEMENTING UNIT", "RESPONSIBLE", "RESPONSIBLE OFFICE", "UNIT",
               "AGENCY", "IMPLEMENTER", "PROPONENT"],
    "remarks": ["REMARKS", "NOTES", "NOTE", "COMMENTS", "DESCRIPTION", "DETAILS"],
    # optional details kept with the activity (added to its remarks): what one unit is, the fund source, the barangay
    "unit_name": ["UNIT OF MEASURE", "UOM", "UNIT TYPE", "UNIT NAME", "UNIT OF MEASUREMENT"],
    "fund_source": ["FUND SOURCE", "FUNDING SOURCE", "SOURCE OF FUND", "SOURCE OF FUNDS", "FUNDING"],
    "barangay": ["BARANGAY", "BARANGAYS", "BRGY", "SITIO"],
}
EXTRA_LABELS = {"unit_name": "Unit", "fund_source": "Fund source", "barangay": "Barangay"}
TEMPLATE_COLUMNS = ["PROVINCE", "MUNICIPALITY", "ACTIVITY", "NO. OF UNITS", "CATEGORY", "STATUS", "START_DATE",
                    "END_DATE", "BENEFICIARY_TYPE", "BENEFICIARIES", "BUDGET_PHP", "OFFICE", "REMARKS"]
TEMPLATE_NOTES = [
    "Activities per municipality – one row per activity. Required: MUNICIPALITY, ACTIVITY and STATUS.",
    "MUNICIPALITY: the municipality or city; PROVINCE helps when two places have similar names. One activity in "
    "several municipalities stays one row: list them in one cell separated by ; (e.g. Bangued; Tayum).",
    "Province-wide: write All in MUNICIPALITY and the province in PROVINCE (several provinces: Abra; Benguet). "
    "Whole CAR: All in both.",
    "STATUS: To conduct, Ongoing, Completed or Postponed.",
    "NO. OF UNITS: how many units are delivered, e.g. 3 PISOS or 1 solar-powered irrigation system (numbers only).",
    "CATEGORY: free text, e.g. Training, Distribution of inputs, Infrastructure, Advisory, Insurance enrolment.",
    "START_DATE / END_DATE: dates (YYYY-MM-DD or an Excel date). A month (YYYY-MM) is read as its first day.",
    "BENEFICIARY_TYPE: Individual (farmers) or FCA (farmer group – farmer cooperative or association). "
    "BENEFICIARIES: how many – number of farmers, or number of FCAs.",
    "BUDGET_PHP: amount in Philippine pesos, in full (e.g. 2837423, not 2,837.423 thousand) – numbers only.",
    "Optional extra column MAP: the map the activity responds to – ENVI, Drought, 10-day rainfall, Seasonal rainfall, "
    "or General (blank = General, shown with every map).",
    "OFFICE: implementing office or unit (e.g. DA-RFO-CAR AMIA, PAO Benguet, MAO La Trinidad). REMARKS: free text.",
    "Title rows above the header are fine. Delete the example rows before uploading.",
    "Sheet “PROJECTED PDN LOSS AND SSL”: rice and corn self-sufficiency per province for the action plan's SSL map – fill "
    "the yellow cells (SSL of the base year, standing crop at the reproductive stage, harvested, annual target and the "
    "total production utilization); the Effect to SSL is computed. Leave it as it is if there is nothing new.",
]
EXAMPLES = [
    ["Abra", "Bangued", "Provision of PISOS", 2, "Distribution of inputs", "Completed", "2026-03-01", "2026-05-30",
     "Individual", 2, 160000, "DA-RFO-CAR HVCDP", "Example row – delete before uploading"],
    ["Kalinga", "Tabuk City", "Solar-powered irrigation system", 1, "Distribution of inputs", "To conduct",
     "2026-11-15", "", "FCA", 1, 2611813, "DA-RFO-CAR Corn", "Example row – delete before uploading"],
    ["Ifugao; Kalinga", "All", "PCIC crop insurance enrolment drive", "", "Insurance enrolment", "To conduct",
     "2026-12-01", "2027-01-31", "Individual", 1500, 600000, "PCIC with DA-RFO-CAR", "Example row – delete before uploading"],
]


def _key(c) -> str:
    return _norm_col(str(c).replace("_", " "))


def _find_columns(df: pd.DataFrame) -> dict[str, str]:
    cols = {_key(c): c for c in df.columns}
    out = {}
    for field, aliases in COLUMNS.items():
        for a in aliases:
            if _key(a) in cols and cols[_key(a)] not in out.values():
                out[field] = cols[_key(a)]
                break
    return out


ALL_WORDS = {"ALL", "ALL MUNICIPALITIES", "ALL PROVINCES", "WHOLE PROVINCE", "PROVINCE WIDE", "PROVINCEWIDE", "CAR",
             "WHOLE CAR", "REGION WIDE", "REGIONWIDE", "REGIONAL", "CORDILLERA"}


def _split(v) -> list[str]:
    """'Bangued; Tayum' (or one per line) → ['Bangued', 'Tayum']."""
    return [] if _blank(v) else [p.strip() for p in re.split(r"\s*[;\n]\s*", str(v)) if p.strip()]


def _blank(v) -> bool:
    # NaN and NaT: an empty cell of a numeric or date column
    return v is None or (not isinstance(v, str) and bool(pd.isna(v))) or (isinstance(v, str) and v.strip() in ("", "-", "nan"))


def _text(v, limit: int) -> str | None:
    if _blank(v):
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s[:limit] or None


def _choice(v, table: dict[str, list[str]]) -> str | None:
    s = "" if _blank(v) else re.sub(r"[^A-Z0-9]+", " ", clean_name(v)).strip()
    for k, names in table.items():
        if s in {re.sub(r"[^A-Z0-9]+", " ", clean_name(n)).strip() for n in names} or s == k.upper().replace("_", " "):
            return k
    return None


def _date(v) -> str | None:
    """Excel date, Excel serial number or text (2026-10-15, 10/15/2026, 2026-10, Oct 15, 2026) → YYYY-MM-DD."""
    if _blank(v):
        return None
    if isinstance(v, (datetime, pd.Timestamp)):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (int, float)) and 20000 < float(v) < 80000:      # Excel serial date
        return (date(1899, 12, 30) + timedelta(days=int(v))).isoformat()
    s = str(v).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y", "%m/%d/%y", "%d-%b-%Y", "%b %d, %Y", "%B %d, %Y",
                "%b %d %Y", "%B %d %Y", "%Y-%m", "%B %Y", "%b %Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"'{s}' is not a date (use YYYY-MM-DD)")


def _number(v, what: str) -> float | None:
    if _blank(v):
        return None
    if isinstance(v, (int, float)):
        n = float(v)
    else:
        s = re.sub(r"(?i)php|₱|p(?=\d)|,|\s", "", str(v))
        try:
            n = float(s)
        except ValueError:
            raise ValueError(f"'{v}' is not a number ({what})") from None
    if n < 0:
        raise ValueError(f"{what} {n:g} is negative")
    return n


def _remarks(r, cols: dict) -> str | None:
    """REMARKS plus the optional details (unit of measure, fund source, barangay), e.g. 'Unit: bags · Fund source: QRF'."""
    parts = [_text(r[cols["remarks"]], 800)] if "remarks" in cols else []
    parts += [f"{label}: {v}" for f, label in EXTRA_LABELS.items() if f in cols and (v := _text(r[cols[f]], 120))]
    return " · ".join(p for p in parts if p)[:1000] or None


def _title_rows(src, filename: str) -> int:
    """How many rows sit above the header (title rows), so warnings name the real spreadsheet row."""
    if not filename.lower().endswith((".xlsx", ".xlsm", ".xls")):
        return 0
    import io
    raw = src if isinstance(src, (bytes, bytearray)) else open(src, "rb").read()
    first = pd.read_excel(io.BytesIO(raw), header=None, nrows=15)
    for i, row in first.iterrows():
        if {str(v).strip().upper() for v in row.values if pd.notna(v)} & set(_NAME_COLS):
            return int(i)
    return 0


def parse(src, filename: str) -> dict:
    """→ {"ok", "rows": [{area_key, area_label, title, …, "row"}], "count", "report": {errors, warnings, …}}."""
    rep: dict = {"errors": [], "warnings": [], "file": filename}
    out = {"type": "activities", "ok": False, "rows": [], "count": 0, "report": rep}
    try:
        offset = _title_rows(src, filename)
        src, filename = _with_header_row(src, filename)
        df, _ = read_any(src, filename)
    except Exception as e:  # noqa: BLE001
        rep["errors"].append(f"Could not read the file: {e}")
        return out
    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(how="all")
    name_col, prov_col, psgc_col = _identify_columns(df)
    cols = _find_columns(df)
    if name_col is None or _key(name_col) in ("AREA", "NAME"):
        # "NAME"/"AREA" are municipality columns in the map inputs, but here they would be the activity name
        name_col = next((c for c in df.columns if _key(c) in ("MUNICIPALITY", "MUNICIPALITY/CITY", "CITY/MUNICIPALITY",
                                                                "LGU", "MUN NAME", "CITY", "TOWN")), None)
    missing = [label for label, ok in (("ACTIVITY", cols.get("title")),
                                       ("MUNICIPALITY or PROVINCE", name_col or prov_col)) if not ok]
    if missing:
        rep["errors"].append(f"Missing column(s): {', '.join(missing)}. Download the template to see the layout.")
        return out
    if "status" not in cols:
        rep["warnings"].append("No STATUS column: every activity is saved as To conduct.")
    rep["columns"] = {k: v for k, v in {**cols, "municipality": name_col, "province": prov_col}.items() if v}
    unknown = [c for c in df.columns if c not in rep["columns"].values() and c != psgc_col
               and not str(c).startswith("Unnamed")]
    if unknown:
        rep["warnings"].append(f"Column(s) not used: {', '.join(map(str, unknown))}.")

    gaz = reference.gazetteer()
    rows, skipped, dropped = [], 0, []
    cell = lambda r, f: r[cols[f]] if f in cols else None  # noqa: E731
    for idx, r in df.iterrows():
        n = int(idx) + 2 + offset              # spreadsheet row: header row + title rows above it
        warn = lambda m: rep["warnings"].append(f"Row {n}: {m}")  # noqa: E731
        title = _text(r[cols["title"]], 300)
        place = r[name_col] if name_col else None
        provs = _split(r[prov_col]) if prov_col else []
        if title is None and _blank(place) and not provs:
            skipped += 1
            continue
        if title is None:
            dropped.append(n)
            warn("the ACTIVITY is empty – row skipped.")
            continue
        raw = cell(r, "status")
        status = _choice(raw, STATUSES)
        if status is None:
            if "status" in cols:
                warn(f"STATUS {'is empty' if _blank(raw) else repr(str(raw).strip())} – saved as To conduct "
                     "(use To conduct, Ongoing, Completed or Postponed).")
            status = "to_conduct"
        hazard = "general"
        if "hazard" in cols and not _blank(cell(r, "hazard")):
            hazard = _choice(cell(r, "hazard"), HAZARDS) or "general"
            if _choice(cell(r, "hazard"), HAZARDS) is None:
                warn(f"MAP '{cell(r, 'hazard')}' not known – saved as General.")

        def read(field, fn, *args):
            if field not in cols:
                return None
            try:
                return fn(cell(r, field), *args)
            except ValueError as e:
                warn(f"{e} – left empty.")
                return None
        start = read("start_date", _date)
        end = read("end_date", _date)
        ben = read("beneficiaries", _number, "beneficiaries")
        units = read("units", _number, "no. of units")
        budget = read("budget", _number, "budget")
        ben_type = None
        if "beneficiary_type" in cols and not _blank(cell(r, "beneficiary_type")):
            ben_type = _choice(cell(r, "beneficiary_type"), BENEFICIARY_TYPES)
            if ben_type is None:
                warn(f"BENEFICIARY_TYPE '{cell(r, 'beneficiary_type')}' not known – left empty (use Individual or "
                     "FCA – farmer group).")
        if start and end and end < start:
            warn(f"the end date {end} is before the start date {start} – the end date is left empty.")
            end = None

        # places: municipalities (or All), else the province(s) given
        good_provs = [p for p in provs if clean_name(p) in gaz.province_cleans]
        bad_provs = [p for p in provs if clean_name(p) not in gaz.province_cleans and clean_name(p) not in ALL_WORDS]
        if bad_provs:
            warn(f"PROVINCE '{'; '.join(bad_provs)}' is not a CAR province – ignored.")
        whole_car = not good_provs and (not provs or any(clean_name(p) in ALL_WORDS for p in provs))
        keys, labels = [], []
        names = _split(place)
        if (not names and good_provs) or (len(names) == 1 and clean_name(names[0]) in ALL_WORDS):
            # "All" (or no municipality): every municipality of the province(s) – or of CAR when none is given
            if not names:
                warn(f"no MUNICIPALITY – the whole of {'; '.join(good_provs)} is used.")
            chosen = gaz.muni if whole_car else gaz.muni[gaz.muni.province.isin({clean_name(p) for p in good_provs})]
            keys, labels = list(chosen.area_key), list(chosen.label)
        else:
            hint = clean_name(good_provs[0]) if len(good_provs) == 1 else None
            for name in names:
                m = match_name(name, hint, "municipal", gaz, None, "activities")
                if m["area_key"] is None:
                    sug = ", ".join(s["label"] for s in m["suggestions"][:3])
                    warn(f"'{name}' is not a CAR municipality{f' (did you mean {sug}?)' if sug else ''} – left out.")
                    continue
                if m["method"] == "fuzzy":
                    warn(f"'{name}' read as {m['area_label']}.")
                elif m["method"] == "exact (other province)":
                    warn(f"{m['area_label']} is not in the province given ({r[prov_col]}).")
                if m["area_key"] not in keys:
                    keys.append(m["area_key"])
                    labels.append(m["area_label"])
            if not keys and good_provs:
                chosen = gaz.muni[gaz.muni.province.isin({clean_name(p) for p in good_provs})]
                keys, labels = list(chosen.area_key), list(chosen.label)
                warn(f"no known municipality – the whole of {'; '.join(good_provs)} is used.")
        if not keys:
            dropped.append(n)
            warn(f"no place it can be shown on ({title}) – row skipped. Give a MUNICIPALITY or PROVINCE.")
            continue
        rows.append({"title": title, "category": _text(cell(r, "category"), 100) if "category" in cols else None,
                     "status": status, "hazard": hazard, "start_date": start, "end_date": end, "units": units,
                     "beneficiary_type": ben_type,
                     "beneficiaries": None if ben is None else int(round(ben)), "budget": budget,
                     "office": _text(cell(r, "office"), 200) if "office" in cols else None,
                     "remarks": _remarks(r, cols), "row": n,
                     "area_keys": keys, "area_labels": labels})

    if dropped:
        rep["warnings"].insert(0, f"{len(dropped)} row(s) skipped (no activity or no place): row(s) "
                                  f"{', '.join(map(str, dropped[:20]))}{' …' if len(dropped) > 20 else ''}.")
    if skipped:
        rep["warnings"].append(f"{skipped} empty row(s) skipped.")
    if not rows and not rep["errors"]:
        rep["errors"].append("No activities found in the file.")
    if any(r["remarks"] and "example row" in r["remarks"].lower() for r in rows):
        rep["warnings"].append("The template's example rows are still in the file – delete them unless they are real.")
    out.update(ok=not rep["errors"], rows=rows, count=len(rows))
    rep["by_status"] = {s: sum(r["status"] == s for r in rows) for s in STATUSES}
    rep["municipalities"] = len({k for r in rows for k in r["area_keys"]})
    return out
