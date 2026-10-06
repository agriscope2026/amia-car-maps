"""Reference data: the CAR gazetteer (77 municipalities / 6 provinces) and boundary loaders.

The boundary shapefiles carry no PSGC field, so the gazetteer joins them to PSGC codes kept in
``data/reference/gazetteer.csv`` (built by ``scripts/build_reference.py``). The canonical key of a
municipality is ``PROVINCE|MUNICIPALITY`` (cleaned names, see ``envi.io_loader.clean_name``).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

from .envi import config
from .envi.io_loader import PROVINCE_DISPLAY, Gazetteer, clean_name, load_gazetteer

REFERENCE_DIR = config.ROOT / "data" / "reference"
GAZETTEER_CSV = REFERENCE_DIR / "gazetteer.csv"

N_MUNICIPALITIES = 77
N_PROVINCES = 6
CITIES = {"BENGUET|BAGUIO", "KALINGA|TABUK"}


@lru_cache(maxsize=1)
def gazetteer() -> Gazetteer:
    """Gazetteer built from the boundary layer (same object the ENVI loaders use)."""
    return load_gazetteer()


@lru_cache(maxsize=1)
def gazetteer_table() -> pd.DataFrame:
    """One row per municipality: area_key, names, province and PSGC codes."""
    gaz = gazetteer()
    t = gaz.muni[["area_key", "province", "province_label", "municipality", "label", "gis_name",
                  "short_name"]].copy()
    if GAZETTEER_CSV.exists():
        codes = pd.read_csv(GAZETTEER_CSV, dtype=str)[["area_key", "psgc"]]
        t = t.merge(codes, on="area_key", how="left")
    else:
        t["psgc"] = None
    t["is_city"] = t.area_key.isin(CITIES)
    return t.sort_values(["province_label", "label"]).reset_index(drop=True)


def province_table() -> pd.DataFrame:
    gaz = gazetteer()
    return gaz.prov[["area_key", "province", "label", "gis_name", "objectid"]].sort_values("label")


def area_label(area_key: str) -> str:
    return gazetteer().label(area_key)


def province_of(area_key: str) -> str:
    return area_key.split("|", 1)[0]


def province_display(province: str) -> str:
    return PROVINCE_DISPLAY.get(clean_name(province), province)


def boundaries():
    """(municipalities, provinces) GeoDataFrames in EPSG:4326 with ``area_key``."""
    from .envi.mapping import load_boundaries
    return load_boundaries()


def gazetteer_records() -> list[dict]:
    t = gazetteer_table()
    return [{k: (None if pd.isna(v) else v) for k, v in r.items()} for r in t.to_dict("records")]


def write_gazetteer_csv(psgc_by_key: dict[str, str], path: Path = GAZETTEER_CSV) -> Path:
    t = gazetteer().muni[["area_key", "province_label", "label", "gis_name"]].copy()
    t["psgc"] = t.area_key.map(psgc_by_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    t.sort_values(["province_label", "label"]).to_csv(path, index=False)
    gazetteer_table.cache_clear()
    return path
