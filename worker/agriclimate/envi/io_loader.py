"""Loading, validation and name matching for the three ENVI input datasets.

Each loader returns a ``DatasetResult`` holding:
  * ``data``   – one row per matched GIS area (index = area_key) with the raw indicator
  * ``report`` – a JSON-serialisable validation report (errors, warnings, matches, unmatched rows)

Area keys are ``"PROVINCE|MUNICIPALITY"`` (municipal level) or ``"PROVINCE"`` (provincial level),
built from the CAR boundary layer in data/gis/.
"""
from __future__ import annotations

import difflib
import io
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import pandas as pd

from . import config

# ------------------------------------------------------------------ names ---

REGION_NAMES = {"CAR", "CORDILLERA", "CORDILLERA ADMINISTRATIVE REGION", "REGION", "TOTAL", "GRAND TOTAL"}

# PSGC province codes for Region 14 (CAR) – used only as a province hint.
PSGC_PROVINCE = {1: "ABRA", 11: "BENGUET", 27: "IFUGAO", 32: "KALINGA", 44: "MOUNTAIN PROVINCE", 81: "APAYAO"}

PROVINCE_DISPLAY = {
    "ABRA": "Abra", "APAYAO": "Apayao", "BENGUET": "Benguet", "IFUGAO": "Ifugao",
    "KALINGA": "Kalinga", "MOUNTAIN PROVINCE": "Mountain Province",
}


def _strip_accents(s: str) -> str:
    # U+FFFD appears where an "Ñ" was mangled by a wrong code page (e.g. "PE�ARRUBIA").
    s = s.replace("�", "N")
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def clean_name(value) -> str:
    """Canonical comparison form of an area name.

    Trims, uppercases, removes accents and parenthetical suffixes, expands common
    abbreviations (Mt./Sto./Sta./Gen.) and drops "City of"/"City" so that
    "Baguio City", "City of Baguio" and "Baguio" all compare equal.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    s = _strip_accents(str(value)).upper().strip()
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"\bMT\b\.?", "MOUNTAIN ", s)
    s = re.sub(r"\bSTO\b\.?", "SANTO ", s)
    s = re.sub(r"\bSTA\b\.?", "SANTA ", s)
    s = re.sub(r"\bGEN\b\.?", "GENERAL ", s)
    s = re.sub(r"[^A-Z0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^CITY OF ", "", s)
    s = re.sub(r" CITY$", "", s)
    if s in ("MOUNTAIN", "MOUNTAIN PROV", "MP"):
        s = "MOUNTAIN PROVINCE"
    return s


# -------------------------------------------------------------- gazetteer ---

@dataclass
class Gazetteer:
    """GIS reference names, keyed by canonical area key."""
    muni: pd.DataFrame       # area_key, province, municipality, label, gis_name, clean
    prov: pd.DataFrame       # area_key, province, label, gis_name, clean, objectid

    def table(self, level: str) -> pd.DataFrame:
        return self.muni if level == "municipal" else self.prov

    def label(self, key: str) -> str:
        for t in (self.muni, self.prov):
            hit = t.loc[t.area_key == key, "label"]
            if len(hit):
                return hit.iloc[0]
        return key

    @property
    def province_cleans(self) -> set[str]:
        return set(self.prov.clean)


@lru_cache(maxsize=4)
def load_gazetteer(muni_path: str = str(config.MUNI_SHP), prov_path: str = str(config.PROV_SHP)) -> Gazetteer:
    import pyogrio

    m = pyogrio.read_dataframe(muni_path, read_geometry=False)
    p = pyogrio.read_dataframe(prov_path, read_geometry=False)
    muni = pd.DataFrame({
        "province": m["Pro_Name"].map(clean_name),
        "municipality": m["Mun_Name"].map(clean_name),
        "gis_name": m["Mun_Name"],
        "short_name": m["MunName2"],
    })
    muni["area_key"] = muni.province + "|" + muni.municipality
    muni["clean"] = muni.municipality
    muni["label"] = m["Mun_Name"].str.replace(r"\s*\(.*\)\s*$", "", regex=True).str.strip()
    prov = pd.DataFrame({
        "province": p["Pro_Name"].map(clean_name),
        "gis_name": p["Pro_Name"],
        "objectid": p["OBJECTID"],
    })
    prov["area_key"] = prov.province
    prov["clean"] = prov.province
    prov["label"] = prov.province.map(PROVINCE_DISPLAY).fillna(p["Pro_Name"])
    muni["province_label"] = muni.province.map(dict(zip(prov.province, prov.label)))
    dup = muni.area_key[muni.area_key.duplicated()]
    if len(dup):
        raise ValueError(f"Duplicate municipality keys in GIS layer: {sorted(set(dup))}")
    return Gazetteer(muni=muni.reset_index(drop=True), prov=prov.reset_index(drop=True))


# --------------------------------------------------------------- matching ---

def match_name(raw, province_hint: str | None, level: str, gaz: Gazetteer,
               manual: dict | None = None, dataset: str = "") -> dict:
    """Match one input name to a GIS area. Returns a match record."""
    manual = manual or {}
    table = gaz.table(level)
    c = clean_name(raw)
    rec = {"raw_name": "" if raw is None else str(raw), "clean": c, "province_hint": province_hint or "",
           "area_key": None, "area_label": None, "method": "unmatched", "score": 0.0, "suggestions": []}

    mkey = manual.get(f"{dataset}|{rec['raw_name']}")
    if mkey and (table.area_key == mkey).any():
        rec.update(area_key=mkey, method="manual", score=1.0)
    else:
        scoped = table[table.province == province_hint] if (province_hint and level == "municipal") else table
        hit = scoped[scoped.clean == c]
        if len(hit) == 1:
            rec.update(area_key=hit.area_key.iloc[0], method="exact", score=1.0)
        else:
            hit = table[table.clean == c]
            if len(hit) == 1:
                moved = level == "municipal" and province_hint and hit.province.iloc[0] != province_hint
                rec.update(area_key=hit.area_key.iloc[0], method="exact (other province)" if moved else "exact", score=1.0)
            elif len(hit) > 1:
                rec["method"] = "ambiguous"
            else:
                best = _fuzzy(c, scoped)
                if not best or best[1] < 0.85:
                    best = _fuzzy(c, table)
                if best and best[1] >= 0.85:
                    rec.update(area_key=best[0], method="fuzzy", score=round(best[1], 3))
    if rec["area_key"] is None:
        scored = sorted(((difflib.SequenceMatcher(None, c, x).ratio(), k) for k, x in zip(table.area_key, table.clean)),
                        reverse=True)[:3]
        rec["suggestions"] = [{"area_key": k, "label": gaz.label(k), "score": round(s, 3)} for s, k in scored]
    else:
        rec["area_label"] = gaz.label(rec["area_key"])
    return rec


def _fuzzy(c: str, table: pd.DataFrame):
    if not c or table.empty:
        return None
    best = max(((difflib.SequenceMatcher(None, c, x).ratio(), k) for k, x in zip(table.area_key, table.clean)))
    return best[1], best[0]


# ---------------------------------------------------------------- reading ---

@dataclass
class DatasetResult:
    dataset: str
    level: str = "municipal"
    data: pd.DataFrame = field(default_factory=pd.DataFrame)
    report: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.report.get("errors")


def read_any(path_or_bytes, filename: str) -> tuple[pd.DataFrame, str]:
    """Read CSV/XLSX into a raw DataFrame (header row = first row). Returns (df, sheet name)."""
    src = io.BytesIO(path_or_bytes) if isinstance(path_or_bytes, (bytes, bytearray)) else path_or_bytes
    ext = Path(filename).suffix.lower()
    if ext == ".csv":
        raw = path_or_bytes if isinstance(path_or_bytes, (bytes, bytearray)) else Path(path_or_bytes).read_bytes()
        for enc in ("utf-8-sig", "cp1252", "latin-1"):
            try:
                return pd.read_csv(io.BytesIO(raw), encoding=enc, dtype=str, keep_default_na=False), ""
            except UnicodeDecodeError:
                continue
        raise ValueError("Could not decode CSV file")
    if ext in (".xlsx", ".xlsm", ".xls"):
        xls = pd.ExcelFile(src)
        sheet = xls.sheet_names[0]
        return xls.parse(sheet, header=0), sheet
    raise ValueError(f"Unsupported file type '{ext}'. Use .csv or .xlsx")


_NAME_COLS = ["MUNICIPALITY_CLEAN", "MUNICIPALITY", "MUNICIPALITY/CITY", "CITY/MUNICIPALITY", "LGU",
              "MUN_NAME", "AREA", "NAME", "PROVINCE", "PRO_NAME"]
_PSGC_RE = re.compile(r"^(PH)?\d{9,10}$", re.I)


def _norm_col(c) -> str:
    return re.sub(r"\s+", " ", str(c)).strip().upper()


def _identify_columns(df: pd.DataFrame) -> tuple[str | None, str | None, str | None]:
    """Return (name column, province column, psgc column) by header, falling back to content."""
    cols = {_norm_col(c): c for c in df.columns}
    name_col = prov_col = psgc_col = None
    for cand in _NAME_COLS:
        if cand in cols and cand not in ("PROVINCE", "PRO_NAME"):
            name_col = cols[cand]
            break
    for cand in ("PROVINCE", "PRO_NAME"):
        if cand in cols:
            prov_col = cols[cand]
            break
    for k, c in cols.items():
        if k in ("PSGC", "PSGC CODE", "CODE", "GEOCODE"):
            psgc_col = c
    unnamed = [c for c in df.columns if str(c).startswith("Unnamed") or str(c).strip() == ""]
    for c in unnamed:
        vals = df[c].dropna().astype(str).str.strip()
        if len(vals) == 0:
            continue
        if psgc_col is None and vals.str.match(_PSGC_RE).mean() > 0.8:
            psgc_col = c
        elif name_col is None and pd.to_numeric(vals, errors="coerce").isna().mean() > 0.8:
            name_col = c
    return name_col, prov_col, psgc_col


def _psgc_province(code) -> str | None:
    if code is None or (isinstance(code, float) and pd.isna(code)):
        return None
    d = re.sub(r"\D", "", str(code))
    if len(d) == 9:      # old format RRPPMMBBB
        return PSGC_PROVINCE.get(int(d[2:4]))
    if len(d) == 10:     # new format RRPPPMMBBB
        return PSGC_PROVINCE.get(int(d[2:5]))
    return None


def _to_num(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.astype(str).str.replace(",", "").str.strip().replace({"": None, "-": None, "nan": None,
                                                                                    "None": None}), errors="coerce")


def _assign_rows(df, name_col, prov_col, psgc_col, gaz, manual, dataset, force_level=None):
    """Classify rows (data / province subtotal / region total) and match data rows to GIS areas."""
    provinces = gaz.province_cleans
    names = df[name_col]
    cleans = names.map(clean_name)
    n_prov_rows = int(cleans.isin(provinces).sum())
    non_region = ~cleans.isin(REGION_NAMES) & (cleans != "")
    # level: municipal if any non-province names exist, otherwise provincial
    level = force_level or ("municipal" if (non_region & ~cleans.isin(provinces)).any() else "provincial")

    rows, current_prov = [], None
    for i, (raw, c) in enumerate(zip(names, cleans)):
        rec_base = {"row": int(i) + 2}  # spreadsheet row number (1-based + header)
        if c == "":
            continue
        if c in REGION_NAMES:
            rows.append({**rec_base, "raw_name": str(raw), "role": "region total"})
            continue
        if level == "municipal" and c in provinces:
            current_prov = c
            rows.append({**rec_base, "raw_name": str(raw), "role": "province subtotal"})
            continue
        hint = None
        if prov_col is not None:
            hint = clean_name(df[prov_col].iloc[i]) or None
        if hint is None and psgc_col is not None:
            hint = _psgc_province(df[psgc_col].iloc[i])
        if hint is None:
            hint = current_prov
        if level == "provincial":
            hint = None
        m = match_name(raw, hint, level, gaz, manual, dataset)
        rows.append({**rec_base, **m, "role": "data", "_idx": i})
    return level, rows, n_prov_rows


def _finish(result: DatasetResult, df: pd.DataFrame, rows: list, value_cols: list[str], gaz: Gazetteer,
            agg: str = "sum", text_cols: list[str] | None = None) -> None:
    """Build result.data (indexed by area_key) from matched rows and fill the report."""
    rep = result.report
    data_rows = [r for r in rows if r["role"] == "data"]
    matched = [r for r in data_rows if r["area_key"]]
    unmatched = [r for r in data_rows if not r["area_key"]]
    keyed = df.iloc[[r["_idx"] for r in matched]].copy()
    keyed["area_key"] = [r["area_key"] for r in matched]
    dups = keyed.area_key[keyed.area_key.duplicated()].unique().tolist()
    if dups:
        rep["warnings"].append(
            f"{len(dups)} area(s) appear more than once and were combined ({agg}): "
            + ", ".join(gaz.label(k) for k in dups))
    num = keyed.groupby("area_key")[value_cols].agg(agg)
    if agg == "sum":  # keep NaN when every duplicate is NaN
        num = num.where(keyed.groupby("area_key")[value_cols].count() > 0)
    if text_cols:
        num = num.join(keyed.groupby("area_key")[text_cols].first())
    result.data = num
    table = gaz.table(result.level)
    missing = sorted(set(table.area_key) - set(num.index))
    for r in rows:
        r.pop("_idx", None)
    rep.update({
        "level": result.level,
        "n_rows": int(len(df)),
        "n_data_rows": len(data_rows),
        "n_matched": len(matched),
        "n_unmatched": len(unmatched),
        "n_subtotal_rows": sum(r["role"] != "data" for r in rows),
        "rows": rows,
        "unmatched": unmatched,
        "missing_areas": [{"area_key": k, "label": gaz.label(k)} for k in missing],
        "methods": pd.Series([r["method"] for r in data_rows]).value_counts().to_dict() if data_rows else {},
    })
    for r in data_rows:
        if r["method"] in ("fuzzy", "exact (other province)"):
            rep["warnings"].append(
                f"Row {r['row']}: '{r['raw_name']}' matched to {r['area_label']} ({r['method']}"
                + (f", score {r['score']}" if r["method"] == "fuzzy" else f", listed under {r['province_hint']}")
                + ") – please confirm.")
    if unmatched:
        rep["warnings"].append(f"{len(unmatched)} row(s) could not be matched to the GIS layer – fix them below.")


def _new_result(dataset: str, filename: str) -> DatasetResult:
    return DatasetResult(dataset=dataset, report={"dataset": dataset, "filename": filename, "errors": [],
                                                  "warnings": [], "columns": [], "sheet": ""})


# ---------------------------------------------------------------- drought ---

_MONTH_ALIASES = {m[:3].upper(): m for m in config.MONTHS}


def _month_of(col) -> str | None:
    k = _norm_col(col)
    for m in config.MONTHS:
        if k == m.upper() or k == m[:3].upper() or k.startswith(m.upper()):
            return m
    return None


def load_drought(src, filename: str, gaz: Gazetteer, settings: dict | None = None) -> DatasetResult:
    """Drought forecast: one row per area, one column per outlook month.

    Values may be categorical (not affected / dry condition / dry spell / drought) – converted with
    ``config.DROUGHT_CATEGORY_SCORES`` and summed over the months – or numeric. Numeric values are
    interpreted per ``settings['hazard_numeric_mode']``: ``rainfall_pct_normal`` (mean, inverted so
    that lower rainfall = higher vulnerability) or ``higher_worse`` (e.g. number of dry days; mean).
    """
    settings = settings or config.DEFAULT_SETTINGS
    res = _new_result("drought", filename)
    rep = res.report
    try:
        df, rep["sheet"] = read_any(src, filename)
    except Exception as e:  # noqa: BLE001
        rep["errors"].append(f"Could not read file: {e}")
        return res
    rep["columns"] = [str(c) for c in df.columns]
    name_col, prov_col, _ = _identify_columns(df)
    if name_col is None and prov_col is not None:
        name_col, prov_col = prov_col, None
    month_cols = [c for c in df.columns if _month_of(c)]
    if name_col is None:
        rep["errors"].append("Missing an area name column (expected PROVINCE or MUNICIPALITY).")
    if not month_cols:
        rep["errors"].append("Missing month columns (expected e.g. October, November, …, March).")
    if rep["errors"]:
        return res
    rep["months"] = [_month_of(c) for c in month_cols]

    vals = df[month_cols].astype(str).apply(lambda s: s.str.strip())
    numeric = vals.apply(_to_num)
    non_blank = vals.ne("") & vals.ne("nan")
    is_numeric = bool(numeric[non_blank].notna().all().all())
    out = df[[name_col] + ([prov_col] if prov_col else [])].copy()
    if is_numeric:
        mode = settings.get("hazard_numeric_mode", "rainfall_pct_normal")
        for c in month_cols:
            out[f"m_{_month_of(c)}"] = numeric[c]
        out["hazard_raw"] = numeric.mean(axis=1)
        rep["hazard_type"] = "numeric"
        rep["hazard_direction"] = "lower_worse" if mode == "rainfall_pct_normal" else "higher_worse"
        rep["hazard_note"] = ("Mean rainfall (% of normal) over the outlook months; inverted so lower rainfall = "
                              "higher vulnerability." if mode == "rainfall_pct_normal"
                              else "Mean of monthly values over the outlook months (higher = worse).")
    else:
        scores = config.DROUGHT_CATEGORY_SCORES
        bad = sorted({v for v in vals.values.ravel() if v and v.lower() != "nan" and v.lower() not in scores})
        if bad:
            rep["errors"].append(f"Unknown drought categories: {bad}. Allowed: {sorted(set(scores))}")
            return res
        for c in month_cols:
            out[f"m_{_month_of(c)}"] = vals[c].str.lower().map(scores)
            out[f"cat_{_month_of(c)}"] = vals[c]
        mcols = [f"m_{_month_of(c)}" for c in month_cols]
        out["hazard_raw"] = out[mcols].sum(axis=1, min_count=1)
        rep["hazard_type"] = "categorical"
        rep["hazard_direction"] = "higher_worse"
        rep["hazard_max"] = config.DROUGHT_MAX_SCORE * len(month_cols)
        rep["hazard_note"] = ("Monthly categories converted to an ordinal scale (not affected = 0, dry condition = 1, "
                              f"dry spell = 2, drought = 3) and summed over {len(month_cols)} months "
                              f"(range 0–{rep['hazard_max']}).")
        rep["category_mapping"] = {"not affected": 0, "dry condition": 1, "dry spell": 2, "drought": 3}
    if out["hazard_raw"].isna().any():
        rep["warnings"].append(f"{int(out.hazard_raw.isna().sum())} row(s) have no forecast values.")

    level, rows, _ = _assign_rows(df, name_col, prov_col, None, gaz, settings.get("manual_matches"), "drought")
    res.level = level
    value_cols = [c for c in out.columns if c.startswith("m_") or c == "hazard_raw"]
    cat_cols = [c for c in out.columns if c.startswith("cat_")]
    _finish(res, out, rows, value_cols, gaz, agg="max", text_cols=cat_cols)
    return res


# ----------------------------------------------------------------- damage ---

def load_damage(src, filename: str, gaz: Gazetteer, settings: dict | None = None) -> DatasetResult:
    """Historical El Niño/drought crop damage (ha) by municipality, one numeric column per crop-year.

    Indicator = mean over years of the total damaged area per year (columns sharing a year,
    e.g. RICE_DMG_2019 and CORN_DMG_2019, are summed first).
    """
    settings = settings or config.DEFAULT_SETTINGS
    res = _new_result("damage", filename)
    rep = res.report
    try:
        df, rep["sheet"] = read_any(src, filename)
    except Exception as e:  # noqa: BLE001
        rep["errors"].append(f"Could not read file: {e}")
        return res
    rep["columns"] = [str(c) for c in df.columns]
    name_col, prov_col, psgc_col = _identify_columns(df)
    if name_col is None and prov_col is not None:
        name_col, prov_col = prov_col, None
    skip = {name_col, prov_col, psgc_col}
    value_cols = [c for c in df.columns if c not in skip and _norm_col(c) not in ("ID", "OBJECTID", "NO", "#")
                  and _to_num(df[c]).notna().any()]
    if name_col is None:
        rep["errors"].append("Missing the area name column (expected MUNICIPALITY_CLEAN).")
    if not value_cols:
        rep["errors"].append("No numeric damage columns found (expected e.g. RICE_DMG_2019, RICE_DMG_2024).")
    if rep["errors"]:
        return res
    num = df[value_cols].apply(_to_num)
    blanks = int(num.isna().sum().sum())
    if blanks:
        rep["warnings"].append(f"{blanks} blank damage cell(s) treated as 0 ha.")
    num = num.fillna(0)
    years: dict[str, list] = {}
    for c in value_cols:
        y = re.search(r"(19|20)\d{2}", str(c))
        years.setdefault(y.group(0) if y else str(c), []).append(c)
    out = pd.DataFrame({f"dmg_{y}": num[cols].sum(axis=1) for y, cols in years.items()})
    out["damage_raw"] = out.mean(axis=1)
    rep["damage_years"] = list(years)
    rep["damage_columns"] = [str(c) for c in value_cols]
    rep["damage_note"] = (f"Mean annual damaged area (ha) over {len(years)} event year(s): {', '.join(years)} "
                          f"(columns: {', '.join(map(str, value_cols))}).")
    level, rows, _ = _assign_rows(df, name_col, prov_col, psgc_col, gaz, settings.get("manual_matches"), "damage")
    res.level = level
    _finish(res, out, rows, list(out.columns), gaz, agg="sum")
    # mean must be recomputed after summing duplicates
    ycols = [c for c in res.data.columns if c.startswith("dmg_")]
    res.data["damage_raw"] = res.data[ycols].mean(axis=1)
    return res


# ------------------------------------------------------------------ crops ---

def load_crops(src, filename: str, gaz: Gazetteer, settings: dict | None = None) -> DatasetResult:
    """Standing crop area (ha) by municipality – PSGC, name, one numeric column per crop.

    Indicator = total standing area across crop columns (e.g. Corn Total + Rice Total).
    """
    settings = settings or config.DEFAULT_SETTINGS
    res = _new_result("crops", filename)
    rep = res.report
    try:
        df, rep["sheet"] = read_any(src, filename)
    except Exception as e:  # noqa: BLE001
        rep["errors"].append(f"Could not read file: {e}")
        return res
    rep["columns"] = [str(c) for c in df.columns]
    name_col, prov_col, psgc_col = _identify_columns(df)
    if name_col is None and prov_col is not None:
        name_col, prov_col = prov_col, None
    skip = {name_col, prov_col, psgc_col}
    value_cols = [c for c in df.columns if c not in skip and _to_num(df[c]).notna().any()
                  and _norm_col(c) not in ("ID", "OBJECTID")]
    if name_col is None:
        rep["errors"].append("Missing the area name column (column B in the template).")
    if not value_cols:
        rep["errors"].append("No numeric crop area columns found (expected e.g. 'Corn Total', 'Rice Total').")
    if rep["errors"]:
        return res
    num = df[value_cols].apply(_to_num)
    blank_rows = df.loc[num.isna().any(axis=1), name_col].astype(str).tolist()
    if blank_rows:
        rep["warnings"].append(f"Blank crop area cells treated as 0 ha for: {', '.join(blank_rows)}.")
    num = num.fillna(0)
    out = pd.DataFrame({f"crop_{re.sub(r'[^a-z0-9]+', '_', str(c).lower()).strip('_')}": num[c] for c in value_cols})
    out["crops_raw"] = out.sum(axis=1)
    rep["crop_columns"] = [str(c) for c in value_cols]
    rep["crops_note"] = f"Total standing area (ha) = {' + '.join(map(str, value_cols))}."
    if psgc_col is not None:
        out["psgc"] = df[psgc_col].astype(str)
    level, rows, _ = _assign_rows(df, name_col, prov_col, psgc_col, gaz, settings.get("manual_matches"), "crops")
    res.level = level
    numeric_cols = [c for c in out.columns if c != "psgc"]
    _finish(res, out, rows, numeric_cols, gaz, agg="sum", text_cols=["psgc"] if "psgc" in out else None)
    return res


LOADERS = {"drought": load_drought, "damage": load_damage, "crops": load_crops}


def load_all(files: dict, gaz: Gazetteer | None = None, settings: dict | None = None) -> dict[str, DatasetResult]:
    """files: {dataset: (path_or_bytes, filename)}"""
    gaz = gaz or load_gazetteer()
    return {k: LOADERS[k](src, name, gaz, settings) for k, (src, name) in files.items()}


# -------------------------------------------------------------- templates ---

def write_templates(out_dir: Path, gaz: Gazetteer | None = None) -> list[Path]:
    """Write blank input templates (same layout as data/input/) pre-filled with GIS area names."""
    gaz = gaz or load_gazetteer()
    out_dir.mkdir(parents=True, exist_ok=True)
    prov = gaz.prov.sort_values("label")
    months = ["October", "November", "December", "January", "February", "March"]

    d = pd.DataFrame({"ID": prov.objectid.values, "PROVINCE": prov.label.values})
    for m in months:
        d[m] = ""
    p1 = out_dir / "drought forecast.csv"
    d.to_csv(p1, index=False)

    rows_dmg, rows_crop = [], []
    for _, pr in prov.iterrows():
        munis = gaz.muni[gaz.muni.province == pr.province].sort_values("label")
        rows_dmg.append({"MUNICIPALITY_CLEAN": pr.gis_name.upper()})
        rows_crop.append({"PSGC": "", "AREA": pr.label})
        for _, mu in munis.iterrows():
            rows_dmg.append({"MUNICIPALITY_CLEAN": mu.label.upper()})
            rows_crop.append({"PSGC": "", "AREA": mu.label})
    dmg = pd.DataFrame(rows_dmg)
    for c in ("RICE_DMG_2019", "RICE_DMG_2024", "RICE_DMG_2026"):
        dmg[c] = None
    p2 = out_dir / "historical damage.xlsx"
    with pd.ExcelWriter(p2, engine="openpyxl") as xw:
        dmg.to_excel(xw, sheet_name="Sheet1", index=False)
        pd.DataFrame({"Notes": [
            "One row per municipality (province rows are optional subtotals and are ignored).",
            "Add one numeric column per crop-year, e.g. RICE_DMG_2019, CORN_DMG_2019 – damaged area in hectares (ha).",
            "Indicator = mean over years of the total damaged area.",
        ]}).to_excel(xw, sheet_name="README", index=False)

    crop = pd.DataFrame(rows_crop)
    crop["Corn Total"] = None
    crop["Rice Total"] = None
    p3 = out_dir / "standing crops ao sept 15 2026.xlsx"
    with pd.ExcelWriter(p3, engine="openpyxl") as xw:
        crop.to_excel(xw, sheet_name="SEP15", index=False)
        pd.DataFrame({"Notes": [
            "Column A: PSGC code (optional). Column B: province / municipality name.",
            "Crop columns: standing area in hectares (ha), e.g. Corn Total, Rice Total.",
            "Province rows are optional subtotals and are ignored at municipal level.",
        ]}).to_excel(xw, sheet_name="README", index=False)
    return [p1, p2, p3]
