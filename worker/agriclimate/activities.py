"""Activities (interventions) from an Excel/CSV list → rows for the activities page.

One row per activity. MUNICIPALITY is matched to the gazetteer like the map inputs (PROVINCE helps). An activity can
take place in several municipalities ("Bangued; Tayum") or provinces ("All" + "Abra; Benguet"; "All" + "All" = CAR). Rows that cannot be read are reported with
their spreadsheet row number and the whole file is refused, so a list is never saved half.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import pandas as pd

from . import reference
from .envi.io_loader import _identify_columns, _norm_col, clean_name, match_name, read_any
from .products.reference_layers import _with_header_row

STATUSES = {
    "to_conduct": ["TO CONDUCT", "TO BE CONDUCTED", "PLANNED", "PLAN", "PROPOSED", "PIPELINE", "NOT YET STARTED",
                   "UPCOMING", "FOR IMPLEMENTATION", "TARGET"],
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
COLUMNS = {   # field → accepted headers (normalized: upper case, single spaces, "_" as space)
    "title": ["ACTIVITY", "ACTIVITIES", "ACTIVITY NAME", "TITLE", "INTERVENTION", "INTERVENTIONS", "PROJECT",
              "PROGRAM ACTIVITY", "PROGRAM/ACTIVITY", "PROGRAMS/ACTIVITIES", "PPA", "PAP"],
    "category": ["CATEGORY", "TYPE", "ACTIVITY TYPE", "KIND", "COMPONENT"],
    "status": ["STATUS", "ACTIVITY STATUS", "REMARKS STATUS"],
    "hazard": ["MAP", "HAZARD", "FOR MAP", "RESPONDS TO", "RESPONSE TO", "RISK"],
    "start_date": ["START DATE", "START", "DATE START", "DATE STARTED", "FROM", "DATE", "TARGET DATE", "SCHEDULE"],
    "end_date": ["END DATE", "END", "DATE END", "DATE COMPLETED", "TO", "UNTIL"],
    "beneficiaries": ["BENEFICIARIES", "NO OF BENEFICIARIES", "NO. OF BENEFICIARIES", "FARMERS", "NO OF FARMERS",
                      "NO. OF FARMERS", "TARGET BENEFICIARIES", "FARMER BENEFICIARIES"],
    "budget": ["BUDGET", "BUDGET PHP", "BUDGET (PHP)", "AMOUNT", "COST", "FUND", "ALLOCATION", "BUDGET_PHP"],
    "office": ["OFFICE", "IMPLEMENTING OFFICE", "IMPLEMENTING UNIT", "RESPONSIBLE", "RESPONSIBLE OFFICE", "UNIT",
               "AGENCY", "IMPLEMENTER", "PROPONENT"],
    "remarks": ["REMARKS", "NOTES", "NOTE", "COMMENTS", "DESCRIPTION", "DETAILS"],
}
TEMPLATE_COLUMNS = ["PROVINCE", "MUNICIPALITY", "ACTIVITY", "CATEGORY", "STATUS", "MAP", "START_DATE", "END_DATE",
                    "BENEFICIARIES", "BUDGET_PHP", "OFFICE", "REMARKS"]
TEMPLATE_NOTES = [
    "Activities per municipality – one row per activity. Required: MUNICIPALITY, ACTIVITY and STATUS.",
    "MUNICIPALITY: the municipality or city; PROVINCE helps when two places have similar names. One activity in "
    "several municipalities stays one row: list them in one cell separated by ; (e.g. Bangued; Tayum).",
    "Province-wide: write All in MUNICIPALITY and the province in PROVINCE (several provinces: Abra; Benguet). "
    "Whole CAR: All in both.",
    "STATUS: To conduct, Ongoing, Completed or Postponed.",
    "MAP: the map the activity responds to – ENVI, Drought, 10-day rainfall, Seasonal rainfall, or General (blank = "
    "General, shown with every map).",
    "CATEGORY: free text, e.g. Training, Distribution of inputs, Infrastructure, Advisory, Insurance enrolment.",
    "START_DATE / END_DATE: dates (YYYY-MM-DD or an Excel date). A month (YYYY-MM) is read as its first day.",
    "BENEFICIARIES: number of farmers reached. BUDGET_PHP: amount in Philippine pesos (numbers only).",
    "OFFICE: implementing office or unit (e.g. DA-RFO-CAR AMIA, PAO Benguet, MAO La Trinidad). REMARKS: free text.",
    "Title rows above the header are fine. Delete the example rows before uploading.",
]
EXAMPLES = [
    ["Abra", "Bangued", "Distribution of drought-tolerant rice seeds", "Distribution of inputs", "Ongoing", "ENVI",
     "2026-10-15", "2026-11-30", 250, 375000, "DA-RFO-CAR AMIA", "Example row – delete before uploading"],
    ["Benguet", "La Trinidad; Tublay", "Farm weather advisory briefing", "Advisory", "To conduct", "General",
     "2026-11-05", "", 80, "", "PAO Benguet", "Example row – delete before uploading"],
    ["Ifugao; Kalinga", "All", "PCIC crop insurance enrolment drive", "Insurance enrolment", "To conduct", "ENVI",
     "2026-12-01", "2027-01-31", 1500, 600000, "PCIC with DA-RFO-CAR", "Example row – delete before uploading"],
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
    return v is None or (isinstance(v, float) and pd.isna(v)) or (isinstance(v, str) and v.strip() in ("", "-", "nan"))


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


def parse(src, filename: str) -> dict:
    """→ {"ok", "rows": [{area_key, area_label, title, …, "row"}], "count", "report": {errors, warnings, …}}."""
    rep: dict = {"errors": [], "warnings": [], "file": filename}
    out = {"type": "activities", "ok": False, "rows": [], "count": 0, "report": rep}
    try:
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
    missing = [label for label, ok in (("MUNICIPALITY", name_col), ("ACTIVITY", cols.get("title")),
                                       ("STATUS", cols.get("status"))) if not ok]
    if missing:
        rep["errors"].append(f"Missing column(s): {', '.join(missing)}. Download the template to see the layout.")
        return out
    rep["columns"] = {k: v for k, v in {**cols, "municipality": name_col, "province": prov_col}.items() if v}
    unknown = [c for c in df.columns if c not in rep["columns"].values() and c != psgc_col
               and not str(c).startswith("Unnamed")]
    if unknown:
        rep["warnings"].append(f"Column(s) not used: {', '.join(map(str, unknown))}.")

    gaz = reference.gazetteer()
    rows, skipped = [], 0
    for i, (_, r) in enumerate(df.iterrows()):
        n = i + 2                              # spreadsheet row (header is row 1)
        title = _text(r[cols["title"]], 300)
        place = r[name_col]
        if title is None and _blank(place):
            skipped += 1
            continue
        if title is None:
            rep["errors"].append(f"Row {n}: the ACTIVITY is empty.")
            continue
        if _blank(place):
            rep["errors"].append(f"Row {n}: the MUNICIPALITY is empty ({title}).")
            continue
        status = _choice(r[cols["status"]], STATUSES)
        if status is None:
            rep["errors"].append(f"Row {n}: STATUS '{'' if _blank(r[cols['status']]) else r[cols['status']]}' – use "
                                 "To conduct, Ongoing, Completed or Postponed.")
            continue
        hazard = "general"
        if "hazard" in cols:
            hazard = _choice(r[cols["hazard"]], HAZARDS)
            if hazard is None:
                rep["errors"].append(f"Row {n}: MAP '{r[cols['hazard']]}' – use ENVI, Drought, 10-day rainfall, "
                                     "Seasonal rainfall or General.")
                continue
        try:
            start = _date(r[cols["start_date"]]) if "start_date" in cols else None
            end = _date(r[cols["end_date"]]) if "end_date" in cols else None
            ben = _number(r[cols["beneficiaries"]], "beneficiaries") if "beneficiaries" in cols else None
            budget = _number(r[cols["budget"]], "budget") if "budget" in cols else None
        except ValueError as e:
            rep["errors"].append(f"Row {n}: {e}.")
            continue
        if start and end and end < start:
            rep["errors"].append(f"Row {n}: the end date {end} is before the start date {start}.")
            continue
        provs = _split(r[prov_col]) if prov_col else []
        keys, labels, bad = [], [], False
        names = _split(place)
        if len(names) == 1 and clean_name(names[0]) in ALL_WORDS:
            # "All": every municipality of the province(s) given – or of CAR when the province is blank or "All" too
            if not provs or any(clean_name(p) in ALL_WORDS for p in provs):
                chosen = gaz.muni
            else:
                unknown = [p for p in provs if clean_name(p) not in gaz.province_cleans]
                if unknown:
                    rep["errors"].append(f"Row {n}: PROVINCE '{'; '.join(unknown)}' is not a CAR province.")
                    continue
                chosen = gaz.muni[gaz.muni.province.isin({clean_name(p) for p in provs})]
            keys, labels = list(chosen.area_key), list(chosen.label)
        else:
            hint = clean_name(provs[0]) if len(provs) == 1 else None
            for name in names:
                m = match_name(name, hint, "municipal", gaz, None, "activities")
                if m["area_key"] is None:
                    sug = ", ".join(s["label"] for s in m["suggestions"][:3])
                    rep["errors"].append(f"Row {n}: '{name}' is not a CAR municipality{f' – did you mean {sug}?' if sug else ''}")
                    bad = True
                    continue
                if m["method"] == "fuzzy":
                    rep["warnings"].append(f"Row {n}: '{name}' read as {m['area_label']}.")
                elif m["method"] == "exact (other province)":
                    rep["warnings"].append(f"Row {n}: {m['area_label']} is not in the province given ({r[prov_col]}).")
                if m["area_key"] not in keys:
                    keys.append(m["area_key"])
                    labels.append(m["area_label"])
        if bad or not keys:
            continue
        rows.append({"title": title, "category": _text(r[cols["category"]], 100) if "category" in cols else None,
                     "status": status, "hazard": hazard, "start_date": start, "end_date": end,
                     "beneficiaries": None if ben is None else int(round(ben)), "budget": budget,
                     "office": _text(r[cols["office"]], 200) if "office" in cols else None,
                     "remarks": _text(r[cols["remarks"]], 1000) if "remarks" in cols else None, "row": n,
                     "area_keys": keys, "area_labels": labels})

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
