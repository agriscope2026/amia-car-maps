"""Optional ENVI exposure inputs besides rice and corn: high-value crops (HVCDP) and livestock & poultry.

* ``hvc`` – the HVCDP *Regional Summary* (one row per planting: date planted, province, municipality, commodity,
  crop group, area planted in ha, target month of harvest). The standing area is computed here **as of the
  standing-crops date** of the issue (``crops_as_of``), so it lines up with the rice and corn inventory. The
  crop-stage columns of the HVCDP workbook are not used: they are formulas on ``TODAY()`` and change every time the
  file is opened. Tree and plantation crops (banana, coffee, cacao, mango, citrus …) count as standing from planting
  on. The area that will still be in the field in each outlook month is reported too (El Niño timing).
* ``livestock`` – the livestock & poultry inventory (number of heads per municipality, DA form or the portal
  template). Heads are converted to Tropical Livestock Units (TLU, FAO factors for Asia) so that a carabao and a
  chicken are not counted alike.

Hectares and heads are never added: the ENVI combines min–max normalized crop area (rice + corn + HVC, ha) and
min–max normalized livestock (TLU) – see ``index.compute_envi``.
"""
from __future__ import annotations

import gzip
import io
import re
from datetime import date
from pathlib import Path

import pandas as pd

from . import config
from .io_loader import (REGION_NAMES, DatasetResult, Gazetteer, _assign_rows, _finish, _new_result, _norm_col,
                        _to_num, clean_name)

# ------------------------------------------------------------------ common ---

EXCEL_EPOCH = pd.Timestamp("1899-12-30")


def to_dates(s: pd.Series) -> pd.Series:
    """Dates from datetimes, ISO / text dates or Excel serial numbers (the browser sends serials)."""
    if pd.api.types.is_datetime64_any_dtype(s):
        return pd.to_datetime(s, errors="coerce")
    num = pd.to_numeric(s, errors="coerce")
    serial = EXCEL_EPOCH + pd.to_timedelta(num.where(num.between(20000, 80000)), unit="D")
    text = pd.to_datetime(s.where(num.isna()).astype("string").str.strip(), errors="coerce", format="mixed")
    return serial.fillna(text).dt.normalize()


def _as_date(v) -> date | None:
    try:
        d = pd.Timestamp(str(v)[:10])
        return None if pd.isna(d) else d.date()
    except (ValueError, TypeError):
        return None


def _read_raw(src, filename: str, want: tuple[str, ...]) -> tuple[pd.DataFrame, str]:
    """Raw cells (no header) of the first sheet with a cell starting with one of ``want`` in its first 20 rows.
    CSV, gzip-compressed CSV (.csv.gz – what the upload page sends for large workbooks) and XLSX."""
    raw = bytes(src) if isinstance(src, (bytes, bytearray)) else Path(src).read_bytes()
    name = filename.lower()
    if name.endswith(".gz"):
        raw, name = gzip.decompress(raw), name[:-3]
    if name.endswith(".csv"):
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                return pd.read_csv(io.BytesIO(raw), header=None, dtype=str, keep_default_na=False, encoding=enc), ""
            except UnicodeDecodeError:
                continue
        raise ValueError("Could not decode the CSV file")
    if not name.endswith((".xlsx", ".xlsm", ".xls")):
        raise ValueError(f"Unsupported file type '{Path(filename).suffix}'. Use .xlsx or .csv")
    xls = pd.ExcelFile(io.BytesIO(raw))
    for sheet in xls.sheet_names:
        head = xls.parse(sheet, header=None, nrows=20)
        cells = {_norm_col(v) for v in head.values.ravel() if pd.notna(v)}
        if any(c.startswith(w) for c in cells for w in want):
            return xls.parse(sheet, header=None), sheet
    raise ValueError(f"No sheet has a '{want[0].title()}' column.")


def _header_row(raw: pd.DataFrame, want: str) -> int | None:
    for i in range(min(len(raw), 20)):
        if any(_norm_col(v).startswith(want) for v in raw.iloc[i].values if pd.notna(v)):
            return i
    return None


# --------------------------------------------------------------------- HVC ---

HVC_COLUMNS = {   # key: header prefixes (normalized, upper case)
    "planted": ("DATE PLANTED",),
    "month": ("MONTH PLANTED",),
    "province": ("PROVINCE",),
    "municipality": ("MUNICIPALITY", "CITY/MUNICIPALITY", "MUNICIPALITY/CITY"),
    "commodity": ("NAME OF COMMODITY", "COMMODITY"),
    "group": ("CROP GROUP",),
    "area": ("CROPS AREA PLANTED", "AREA PLANTED", "AREA (HA)"),
    "harvest": ("TARGET MONTH OF HARVEST", "TARGET HARVEST", "TARGET DATE OF HARVEST"),
    "multi": ("MULTI HARVEST",),
}
# tree / plantation crops: standing from planting on (their "target harvest" is the first harvest, not the end)
PERENNIAL = re.compile(r"banana|coffee|cacao|cocoa|mango|rambutan|orange|lemon|calamansi|pomelo|ponkan|citrus|"
                       r"mandarin|dragon ?fruit|avocado|durian|lanzones|jackfruit|mangosteen|coconut|abaca|rubber",
                       re.I)
# groups for commodities the HVCDP file sometimes leaves blank (otherwise taken from other rows of the file)
GROUP_OF = {
    "zucchini": "Upland Vegetable", "mustard": "Upland Vegetable", "celery": "Upland Vegetable",
    "french beans": "Upland Vegetable", "spinach": "Lowland Vegetable", "watercress": "Lowland Vegetable",
    "wansoy": "Upland Vegetable", "lima bean": "Lowland Vegetable", "parsley": "Spices",
    "hot pepper (native)": "Spices", "ridge gourd (patola)": "Lowland Vegetable", "cow pea": "Lowland Vegetable",
    "rice beans": "Lowland Vegetable", "pole sitaw": "Lowland Vegetable", "fern/pako": "Upland Vegetable",
    "white beans": "Lowland Vegetable", "winged bean": "Lowland Vegetable", "lemon": "Plantation Crops",
    "chrysanthemum": "Cutflower", "sunflower (imported)": "Cutflower", "anthurium": "Cutflower",
    "gladiola": "Cutflower", "rose": "Cutflower", "aster": "Cutflower", "statice": "Cutflower",
    "alstromeria": "Cutflower", "baby's breath": "Cutflower",
}
MULTI_HARVEST_DAYS = 63      # multi-harvest crops (tomato, chayote …) keep being picked ~9 weeks after the target
DEFAULT_CYCLE_DAYS = 90      # target harvest missing/invalid and no other record of the commodity
LARGE_RECORD_HA = 200        # a single planting this large is flagged for checking


def _hvc_columns(raw: pd.DataFrame, hr: int) -> dict[str, int]:
    heads = [_norm_col(v) if pd.notna(v) else "" for v in raw.iloc[hr].values]
    cols: dict[str, int] = {}
    for key, prefixes in HVC_COLUMNS.items():
        for i, h in enumerate(heads):
            if h and any(h.startswith(p) for p in prefixes) and i not in cols.values():
                cols[key] = i
                break
    return cols


def _canonical(names: pd.Series) -> tuple[pd.Series, dict[str, list[str]]]:
    """Merge spellings of the same commodity ('Peanut' / 'peanut' / 'PEANUT') under the most used spelling."""
    s = names.astype("string").str.strip().str.replace(r"\s+", " ", regex=True)
    key = s.str.lower()
    best = s.groupby(key).agg(lambda x: x.value_counts().index[0])
    variants = {best[k]: sorted(set(g)) for k, g in s.groupby(key) if g.nunique() > 1}
    return key.map(best), variants


def _group_name(g) -> str:
    g = re.sub(r"\s+", " ", str(g)).strip()
    if not g or g.lower() in ("nan", "none", "#error!", "#ref!", "#n/a"):
        return ""
    g = g.title()
    return "Cutflower" if g in ("Cutflowers", "Cut Flower", "Cut Flowers") else g


def hvc_frame(raw: pd.DataFrame, rep: dict) -> pd.DataFrame | None:
    """One clean row per planting: province, municipality, commodity, group, area, planted, harvest_end, perennial."""
    hr = _header_row(raw, "NAME OF COMMODITY")
    if hr is None:
        rep["errors"].append("This is not the HVCDP Regional Summary: no 'NAME OF COMMODITY' column found.")
        return None
    cols = _hvc_columns(raw, hr)
    rep["columns"] = [str(v) for v in raw.iloc[hr].values if pd.notna(v) and str(v).strip()]
    need = {"province": "PROVINCE", "municipality": "MUNICIPALITY", "commodity": "NAME OF COMMODITY",
            "area": "CROPS AREA PLANTED (hectares)"}
    for k, label in need.items():
        if k not in cols:
            rep["errors"].append(f"Missing the {label} column.")
    if "planted" not in cols and "month" not in cols:
        rep["errors"].append("Missing the DATE PLANTED (or MONTH PLANTED) column.")
    if rep["errors"]:
        return None
    body = raw.iloc[hr + 1:]
    col = lambda k: body.iloc[:, cols[k]] if k in cols else pd.Series(pd.NA, index=body.index)  # noqa: E731
    d = pd.DataFrame({
        "province": col("province").astype("string").str.strip(),
        "municipality": col("municipality").astype("string").str.strip(),
        "commodity": col("commodity"),
        "group": col("group").map(_group_name),
        "area": _to_num(col("area")),
        "planted": to_dates(col("planted")),
        "month": to_dates(col("month")),
        "harvest": to_dates(col("harvest")),
        "multi": col("multi").astype("string").str.strip().str.upper().eq("YES").fillna(False).astype(bool),
    })
    d["planted"] = d["planted"].fillna(d.pop("month"))
    empty = lambda c: c.isna() | c.astype("string").str.strip().fillna("").eq("")  # noqa: E731
    d = d[~empty(d.municipality) & ~empty(d.province)]
    no_name = empty(d.commodity)
    if no_name.any():
        rep["warnings"].append(f"{int(no_name.sum())} record(s) without a commodity name were skipped "
                               f"({d.area[no_name].sum():,.1f} ha).")
    d = d[~no_name]
    bad_area = d.area.isna() | (d.area <= 0)
    if bad_area.any():
        rep["warnings"].append(f"{int(bad_area.sum())} record(s) without a valid area planted were skipped.")
    no_date = d.planted.isna() & ~bad_area
    if no_date.any():
        rep["warnings"].append(f"{int(no_date.sum())} record(s) without a planting date were skipped.")
    d = d[~bad_area & d.planted.notna()].copy()
    if d.empty:
        rep["errors"].append("No planting records with an area and a planting date.")
        return None

    d["commodity"], variants = _canonical(d.commodity)
    if variants:
        rep["warnings"].append("Spellings merged as one commodity: " + "; ".join(
            f"{k} ({' / '.join(v)})" for k, v in list(variants.items())[:12]) + (" …" if len(variants) > 12 else "")
            + ". Ask HVCDP to use one spelling.")
    key = d.commodity.str.lower()
    known = d[d.group != ""].groupby(key[d.group != ""]).group.agg(lambda x: x.value_counts().index[0])
    missing = d.group == ""
    if missing.any():
        fill = key[missing].map(known).fillna(key[missing].map(GROUP_OF)).fillna("Other HVC")
        d.loc[missing, "group"] = fill
        top = d[missing].commodity.value_counts().head(8).index.tolist()
        rep["warnings"].append(f"{int(missing.sum())} record(s) had no CROP GROUP – filled from the commodity "
                               f"(e.g. {', '.join(top)}). Ask HVCDP to fill the crop group.")
    d["perennial"] = d.commodity.str.contains(PERENNIAL).fillna(False).astype(bool)
    big = d[d.area >= LARGE_RECORD_HA].sort_values("area", ascending=False)
    if len(big):
        rep["warnings"].append(
            f"{len(big)} single record(s) of {LARGE_RECORD_HA:g} ha or more – check that they are new plantings and "
            "not a municipal total or an existing plantation typed in as one planting: " + "; ".join(
                f"{r.commodity} {r.area:,.0f} ha ({str(r.municipality).title()}, {r.planted:%b %Y})"
                for r in big.head(6).itertuples()) + (" …" if len(big) > 6 else "") + ".")

    # harvest date: target month of harvest; estimated when missing or before planting
    days = (d.harvest - d.planted).dt.days
    valid = d.harvest.notna() & (days > 0)
    typical = days[valid].groupby(key[valid]).median()
    est = ~valid & ~d.perennial
    if est.any():
        n_before = int((est & d.harvest.notna()).sum())
        guess = key[est].map(typical).fillna(DEFAULT_CYCLE_DAYS)
        d.loc[est, "harvest"] = d.loc[est, "planted"] + pd.to_timedelta(guess, unit="D")
        rep["warnings"].append(
            f"{int(est.sum())} record(s) ({d.loc[est, 'area'].sum():,.1f} ha) have no target harvest or one before "
            f"the planting date{f' ({n_before} before planting)' if n_before else ''} – the usual crop duration of "
            "the commodity was used instead.")
    d["harvest_end"] = d.harvest + pd.to_timedelta(d.multi.map({True: MULTI_HARVEST_DAYS, False: 0}), unit="D")
    return d


def hvc_standing(d: pd.DataFrame, as_of: pd.Timestamp) -> pd.Series:
    """Boolean: in the field on ``as_of`` (planted on/before it and not yet fully harvested; trees always)."""
    planted = d.planted <= as_of
    return planted & (d.perennial | (d.harvest_end > as_of))


def hvc_outlook(d: pd.DataFrame, months: list[str]) -> list[dict]:
    """HVC area in the field during each outlook month, from the given plantings (those up to the crops date)."""
    out = []
    for ym in months:
        p = pd.Period(ym, "M")
        s, e = p.start_time, p.end_time.normalize()
        short = ~d.perennial & (d.planted <= e) & (d.harvest_end >= s)
        tree = d.perennial & (d.planted <= e)
        due = ~d.perennial & (d.harvest.dt.to_period("M") == p)
        out.append({"month": ym, "label": p.strftime("%B %Y"), "short_cycle_ha": round(float(d.area[short].sum()), 1),
                    "perennial_ha": round(float(d.area[tree].sum()), 1),
                    "harvest_due_ha": round(float(d.area[due].sum()), 1)})
    return out


def load_hvc(src, filename: str, gaz: Gazetteer, settings: dict | None = None) -> DatasetResult:
    """HVCDP Regional Summary → HVC standing area (ha) per municipality as of the standing-crops date."""
    settings = settings or config.DEFAULT_SETTINGS
    res = _new_result("hvc", filename)
    rep = res.report
    as_of = _as_date(settings.get("crops_as_of"))
    if as_of is None:
        rep["errors"].append("Set the “standing crops as of” date: the HVC standing area is computed for that date.")
        return res
    try:
        raw, rep["sheet"] = _read_raw(src, filename, ("NAME OF COMMODITY",))
    except Exception as e:  # noqa: BLE001
        rep["errors"].append(f"Could not read file: {e}")
        return res
    d = hvc_frame(raw, rep)
    if d is None:
        return res
    cut = pd.Timestamp(as_of)
    first, last = d.planted.min(), d.planted.max()
    later = d.planted > cut
    if later.any():
        rep["warnings"].append(f"{int(later.sum())} record(s) planted after {config.date_label(as_of.isoformat())} "
                               f"({d.area[later].sum():,.1f} ha) are not counted – they come after the standing "
                               "crops date.")
    if last < cut - pd.Timedelta(days=45):
        rep["warnings"].append(f"The latest planting in the file is {last:%B %Y}, well before the standing crops "
                               f"date ({config.date_label(as_of.isoformat())}). Ask HVCDP for an updated summary.")
    on = hvc_standing(d, cut)
    d["short"] = d.area.where(on & ~d.perennial, 0.0)
    d["tree"] = d.area.where(on & d.perennial, 0.0)

    # province names that are not CAR provinces (e.g. "BAGUIO CITY") are matched by municipality name only
    provs = gaz.province_cleans
    d["prov_hint"] = d.province.map(lambda p: p if clean_name(p) in provs else "")
    d["muni_key"] = d.municipality.map(clean_name)
    per = d.groupby(["prov_hint", "muni_key"], sort=False).agg(
        municipality=("municipality", "first"), short=("short", "sum"), tree=("tree", "sum")).reset_index()
    per["hvc_ha"] = per.short + per.tree
    table = pd.DataFrame({"PROVINCE": per.prov_hint, "MUNICIPALITY": per.municipality})
    out = pd.DataFrame({"hvc_ha": per.hvc_ha, "hvc_short_ha": per.short, "hvc_perennial_ha": per.tree})
    level, rows, _ = _assign_rows(table, "MUNICIPALITY", "PROVINCE", None, gaz, settings.get("manual_matches"),
                                  "hvc", force_level="municipal")
    res.level = level
    _finish(res, out, rows, list(out.columns), gaz, agg="sum")

    # coverage: a province without any record is "no data", not "no HVC"
    reported = {clean_name(p) for p in d.province.unique()} | {k.split("|")[0] for k in res.data.index}
    absent = sorted(label for p, label in zip(gaz.prov.province, gaz.prov.label) if p not in reported)
    if absent:
        rep["warnings"].append(f"No HVC records at all for {', '.join(absent)} – counted as 0 ha of HVC. Ask "
                               "HVCDP for their data; until then their exposure is understated.")
    stood = d[on]
    months = _outlook_months(settings)
    rep["hvc_summary"] = {
        "as_of": as_of.isoformat(),
        "n_records": int(len(d)),
        "first_planting": first.date().isoformat(), "last_planting": last.date().isoformat(),
        "standing_ha": round(float(d.short.sum() + d.tree.sum()), 1),
        "short_cycle_ha": round(float(d.short.sum()), 1),
        "perennial_ha": round(float(d.tree.sum()), 1),
        "by_province": {p: round(float(v), 1) for p, v in
                        stood.groupby("province").area.sum().sort_values(ascending=False).items()},
        "by_group": {g: round(float(v), 1) for g, v in
                     stood.groupby("group").area.sum().sort_values(ascending=False).items()},
        "top_commodities": [{"commodity": c, "ha": round(float(v), 1)} for c, v in
                            stood.groupby("commodity").area.sum().sort_values(ascending=False).head(10).items()],
        "outlook": hvc_outlook(d[d.planted <= cut], months),
        "provinces_without_data": absent,
    }
    o = rep["hvc_summary"]["outlook"]
    if o and d.short.sum() > 0:
        rep["warnings"].append(
            f"El Niño timing: of the {d.short.sum():,.0f} ha of short-cycle HVC standing on "
            f"{config.date_label(as_of.isoformat())}, {o[0]['short_cycle_ha']:,.0f} ha is in the field in "
            f"{o[0]['label']} and {o[-1]['short_cycle_ha']:,.0f} ha in {o[-1]['label']} (see the table). Crops "
            "planted from now on are not in the file yet – ask HVCDP for the dry-season planting targets.")
    if d.tree.sum() > 0:
        rep["warnings"].append(
            f"Tree / plantation crops ({d.tree.sum():,.0f} ha: banana, coffee, cacao, mango, citrus …) count as "
            "standing all season. The file only lists plantings reported by HVCDP – older plantations that were "
            "never entered are not included.")
    rep["hvc_note"] = (f"HVC standing area as of {config.date_label(as_of.isoformat())}, computed from the HVCDP "
                       f"Regional Summary ({len(d):,} planting records, {first:%B %Y} – {last:%B %Y}): planted on or "
                       "before that date and not yet harvested (target month of harvest; multi-harvest crops "
                       f"+{MULTI_HARVEST_DAYS} days); tree / plantation crops always count.")
    return res


def _outlook_months(settings: dict) -> list[str]:
    try:
        return pd.period_range(str(settings["period_start"])[:7], str(settings["period_end"])[:7],
                               freq="M").strftime("%Y-%m").tolist()
    except (KeyError, ValueError):
        return []


# --------------------------------------------------------------- livestock ---

# Tropical Livestock Units per head (FAO, Asia: cattle 0.65, buffalo 0.7, pig 0.25, sheep/goat 0.1, chicken 0.01;
# the minor species are approximations). Bee colonies are counted but not converted.
TLU = {"CATTLE": 0.65, "CARABAO": 0.7, "HORSE": 0.65, "SWINE_HIBREED": 0.25, "SWINE_NATIVE": 0.25, "SWINE": 0.25,
       "GOAT": 0.1, "SHEEP": 0.1, "RABBIT": 0.01, "CHICKEN_COMMERCIAL": 0.01, "CHICKEN_NATIVE": 0.01, "CHICKEN": 0.01,
       "DUCK": 0.01, "GOOSE": 0.02, "TURKEY": 0.02, "QUAIL": 0.001, "BEES": 0.0}
SPECIES_LABELS = {"CATTLE": "Cattle", "CARABAO": "Carabao", "HORSE": "Horse", "SWINE_HIBREED": "Swine (hi-breed)",
                  "SWINE_NATIVE": "Swine (native)", "SWINE": "Swine", "GOAT": "Goat", "SHEEP": "Sheep",
                  "RABBIT": "Rabbit", "CHICKEN_COMMERCIAL": "Chicken (commercial)",
                  "CHICKEN_NATIVE": "Chicken (native)", "CHICKEN": "Chicken", "DUCK": "Duck", "GOOSE": "Goose",
                  "TURKEY": "Turkey", "QUAIL": "Quail", "BEES": "Bees (colonies)"}


def species_of(header) -> str | None:
    h = re.sub(r"[^A-Z ]+", " ", _norm_col(header).replace("_", " "))
    h = re.sub(r"\s+", " ", h).strip()
    if not h:
        return None
    if h.startswith("SWINE") or h.startswith(("HOG", "PIG")):
        return "SWINE_NATIVE" if "NATIVE" in h else "SWINE_HIBREED" if re.search(r"HI ?BREED|COMMERCIAL|HIBREED",
                                                                               h) else "SWINE"
    if h.startswith("CHICKEN"):
        return "CHICKEN_NATIVE" if "NATIVE" in h else "CHICKEN_COMMERCIAL" if re.search(
            r"COMMERCIAL|BROILER|LAYER", h) else "CHICKEN"
    for k in ("CATTLE", "CARABAO", "SHEEP", "GOAT", "HORSE", "RABBIT", "DUCK", "GOOSE", "TURKEY", "QUAIL"):
        if h.startswith(k):
            return k
    if h.startswith(("BUFFALO", "WATER BUFFALO")):
        return "CARABAO"
    if h.startswith(("BEE", "APIARY")):
        return "BEES"
    return None


def _title_as_of(raw: pd.DataFrame, hr: int) -> str:
    for v in raw.iloc[:hr].values.ravel():
        if pd.notna(v) and re.search(r"\bas of\b", str(v), re.I):
            return re.sub(r"\s+", " ", str(v)).strip()
    return ""


def load_livestock(src, filename: str, gaz: Gazetteer, settings: dict | None = None) -> DatasetResult:
    """Livestock & poultry inventory (heads per municipality) → heads per species and TLU per area."""
    settings = settings or config.DEFAULT_SETTINGS
    res = _new_result("livestock", filename)
    rep = res.report
    as_of = _as_date(settings.get("livestock_as_of"))
    if as_of is None:
        rep["errors"].append("Set the “livestock inventory as of” date (e.g. the last day of the quarter).")
    try:
        raw, rep["sheet"] = _read_raw(src, filename, ("CATTLE", "CARABAO", "SWINE", "CHICKEN"))
    except Exception as e:  # noqa: BLE001
        rep["errors"].append(f"Could not read file: {e}")
        return res
    hr = next((i for i in range(min(len(raw), 20)) if sum(species_of(v) is not None for v in raw.iloc[i].values
                                                          if pd.notna(v)) >= 3), None)
    if hr is None:
        rep["errors"].append("No animal columns found (expected e.g. CATTLE, CARABAO, GOAT, SWINE, CHICKEN).")
        return res
    species = {}
    for i, v in enumerate(raw.iloc[hr].values):
        sp = species_of(v) if pd.notna(v) else None
        if sp and sp not in species.values():
            species[i] = sp
    # name columns: PROVINCE / MUNICIPALITY in the header row or the rows just above it (merged header cells)
    prov_col = muni_col = None
    for r in range(max(0, hr - 2), hr + 1):
        for i, v in enumerate(raw.iloc[r].values):
            h = _norm_col(v) if pd.notna(v) else ""
            if prov_col is None and h == "PROVINCE":
                prov_col = i
            if muni_col is None and h in ("MUNICIPALITY", "CITY/MUNICIPALITY", "MUNICIPALITY/CITY", "LGU", "AREA"):
                muni_col = i
    if muni_col is None:
        rep["errors"].append("Missing the MUNICIPALITY column.")
    rep["columns"] = [SPECIES_LABELS[s] for s in species.values()]
    rep["title"] = _title_as_of(raw, hr)
    if rep["errors"]:
        return res

    body = raw.iloc[hr + 1:].reset_index(drop=True)
    text = lambda c: body.iloc[:, c].astype("string").str.strip().fillna("") if c is not None else \
        pd.Series("", index=body.index)  # noqa: E731
    prov_cell, muni = text(prov_col), text(muni_col)
    heads = pd.DataFrame({sp: _to_num(body.iloc[:, i]) for i, sp in species.items()})
    is_total = muni.str.upper().str.contains("TOTAL") | prov_cell.str.upper().str.contains("TOTAL") | \
        muni.map(clean_name).isin(REGION_NAMES)
    is_prov_row = (muni == "") & (prov_cell != "") & ~is_total
    province = prov_cell.where(prov_cell != "").ffill().fillna("")
    data = (muni != "") & ~is_total & ~muni.map(clean_name).isin(gaz.province_cleans)
    if heads[data].isna().all(axis=1).any():
        empty = muni[data & heads.isna().all(axis=1)].tolist()
        rep["warnings"].append(f"No livestock figures for {', '.join(empty)} – counted as 0 heads.")
    negative = (heads[data] < 0).any(axis=1)
    if negative.any():
        rep["errors"].append(f"Negative head counts for {', '.join(muni[data][negative])}.")

    # provincial subtotal rows: compare with the sum of their municipalities (typing errors show up here)
    for i in is_prov_row[is_prov_row].index:
        p = prov_cell[i]
        own = heads.loc[data & (province == p)].sum()
        diff = [f"{SPECIES_LABELS[s]} {heads.at[i, s]:,.0f} vs {own[s]:,.0f}" for s in species.values()
                if pd.notna(heads.at[i, s]) and abs(heads.at[i, s] - own[s]) > max(10, 0.01 * own[s])]
        if diff:
            rep["warnings"].append(f"{p.title()}: the province total row differs from the sum of its "
                                   f"municipalities ({'; '.join(diff[:4])}{' …' if len(diff) > 4 else ''}). The "
                                   "municipal figures are used.")
        # two species columns with the same figures in every municipality – usually a copy-paste error
        g = heads.loc[data & (province == p)]
        cols = list(species.values())
        for a in range(len(cols)):
            for b in range(a + 1, len(cols)):
                x, y = g[cols[a]], g[cols[b]]
                if (x.notna() & (x > 0)).sum() >= 3 and x.fillna(-1).equals(y.fillna(-1)):
                    rep["warnings"].append(f"{p.title()}: {SPECIES_LABELS[cols[a]]} and {SPECIES_LABELS[cols[b]]} "
                                           "have the same figures in every municipality – check for a copy-paste "
                                           "error.")
    tlu = settings.get("tlu_factors") or TLU
    table = pd.DataFrame({"PROVINCE": province[data].values, "MUNICIPALITY": muni[data].values})
    h = heads[data].reset_index(drop=True)
    out = h.add_prefix("lv_")
    out["livestock_heads"] = h.drop(columns=["BEES"], errors="ignore").sum(axis=1, min_count=1)
    out["livestock_raw"] = sum(h[s].fillna(0) * float(tlu.get(s, 0)) for s in h.columns)
    level, rows, _ = _assign_rows(table, "MUNICIPALITY", "PROVINCE", None, gaz, settings.get("manual_matches"),
                                  "livestock", force_level="municipal")
    res.level = level
    _finish(res, out, rows, list(out.columns), gaz, agg="sum")
    if rep["missing_areas"]:
        rep["warnings"].append(f"{len(rep['missing_areas'])} municipalities are not in the file and count as 0 "
                               f"heads: {', '.join(m['label'] for m in rep['missing_areas'][:15])}"
                               f"{' …' if len(rep['missing_areas']) > 15 else ''}.")
    title, given = rep["title"], as_of
    m = re.search(r"as of\s*([A-Za-z]+)[ ,]*(\d{4})", title, re.I)
    if m and given:
        try:
            t = pd.Timestamp(f"{m.group(1)} 1, {m.group(2)}")
            if (t.year, t.month) != (given.year, given.month):
                sheet = f" (sheet “{rep['sheet']}”)" if rep["sheet"] else ""
                rep["warnings"].append(f"The file title says “{title}”{sheet} but you entered "
                                       f"{config.date_label(given.isoformat())} – check which date is right.")
        except ValueError:
            pass
    totals = res.data[[f"lv_{s}" for s in species.values()]].sum()
    rep["livestock_summary"] = {
        "as_of": given.isoformat() if given else None,
        "heads": {SPECIES_LABELS[c[3:]]: int(v) for c, v in totals.items()},
        "tlu_total": round(float(res.data.livestock_raw.sum()), 1),
        "tlu_factors": {SPECIES_LABELS[s]: tlu.get(s, 0) for s in species.values()},
    }
    rep["livestock_note"] = ("Livestock & poultry in Tropical Livestock Units (TLU = heads × FAO factor: "
                             + ", ".join(f"{SPECIES_LABELS[s].lower()} {tlu.get(s, 0)}" for s in species.values()
                                         if tlu.get(s, 0)) + ")"
                             + (f", inventory as of {config.date_label(given.isoformat())}." if given else "."))
    return res
