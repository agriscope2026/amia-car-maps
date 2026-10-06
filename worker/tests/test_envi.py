import io
import math

import numpy as np
import pandas as pd
import pytest

from agriclimate.envi import config, index, io_loader
from agriclimate.envi.normalize import fixed_scale, minmax, normalize_hazard, ordinal_from_categories


# the reference results were computed with equal weights
EQUAL = {**config.DEFAULT_SETTINGS, "weights": {"hazard": 1 / 3, "damage": 1 / 3, "crops": 1 / 3}}


@pytest.fixture(scope="module")
def gaz():
    return io_loader.load_gazetteer()


@pytest.fixture(scope="module")
def sample(gaz):
    files = {k: (p, p.name) for k, p in config.DEFAULT_FILES.items()}
    return io_loader.load_all(files, gaz, config.DEFAULT_SETTINGS)


# ------------------------------------------------------------ normalization ---

def test_minmax_basic():
    out = minmax(pd.Series([10, 20, 30]))
    assert out.tolist() == [0.0, 0.5, 1.0]


def test_minmax_constant_is_zero():
    assert minmax(pd.Series([5, 5, 5])).tolist() == [0.0, 0.0, 0.0]


def test_minmax_keeps_nan():
    out = minmax(pd.Series([0, np.nan, 4]))
    assert out.iloc[0] == 0 and math.isnan(out.iloc[1]) and out.iloc[2] == 1


def test_minmax_inverted_for_rainfall():
    # lower rainfall (% of normal) = more vulnerable = higher value
    out = minmax(pd.Series([40, 70, 100]), invert=True)
    assert out.tolist() == [1.0, 0.5, 0.0]


def test_fixed_scale():
    assert fixed_scale(pd.Series([0, 9, 18]), 18).tolist() == [0.0, 0.5, 1.0]


def test_ordinal_mapping():
    out = ordinal_from_categories(["Drought", "dry spell ", "DRY CONDITION", "not affected", "??"],
                                  config.DROUGHT_CATEGORY_SCORES)
    assert out.iloc[:4].tolist() == [3, 2, 1, 0] and math.isnan(out.iloc[4])


def test_normalize_hazard_numeric_rainfall():
    rep = {"hazard_type": "numeric", "hazard_direction": "lower_worse"}
    out, desc = normalize_hazard(pd.Series([50.0, 100.0]), rep)
    assert out.tolist() == [1.0, 0.0] and "inverted" in desc


def test_normalize_hazard_fixed_scale():
    rep = {"hazard_type": "categorical", "hazard_direction": "higher_worse", "hazard_max": 18}
    out, _ = normalize_hazard(pd.Series([11, 14]), rep, scaling="fixed")
    assert out.round(4).tolist() == [round(11 / 18, 4), round(14 / 18, 4)]


# ----------------------------------------------------------------- weights ---

def test_weights_must_sum_to_one():
    with pytest.raises(ValueError):
        index.validate_weights({"hazard": 0.5, "damage": 0.5, "crops": 0.5})
    with pytest.raises(ValueError):
        index.validate_weights({"hazard": -0.2, "damage": 0.6, "crops": 0.6})
    w = index.validate_weights({"hazard": 1 / 3, "damage": 1 / 3, "crops": 1 / 3})
    assert abs(sum(w.values()) - 1) < 1e-9


def test_weighted_sum():
    norms = pd.DataFrame({"hazard_norm": [1.0, 0.0, 0.5], "damage_norm": [1.0, 0.0, np.nan],
                          "crops_norm": [1.0, 1.0, 0.5]})
    out = index.weighted_sum(norms, {"hazard": 0.5, "damage": 0.3, "crops": 0.2})
    assert out.iloc[0] == pytest.approx(1.0)
    assert out.iloc[1] == pytest.approx(0.2)
    assert math.isnan(out.iloc[2])  # any missing indicator → no ENVI


# ---------------------------------------------------------- classification ---

def test_equal_interval_classes_lower_inclusive():
    v = pd.Series([0.0, 0.19, 0.2, 0.4, 0.59, 0.6, 0.8, 1.0, np.nan])
    b = index.class_breaks(v, "equal")
    assert b == [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    got = index.classify(v, b, "equal").tolist()
    assert got == ["Very Low", "Very Low", "Low", "Moderate", "Moderate", "High", "Very High", "Very High",
                   config.NO_DATA_LABEL]


def test_quantile_classes_balanced():
    v = pd.Series(np.linspace(0, 1, 100))
    b = index.class_breaks(v, "quantile")
    counts = index.classify(v, b, "quantile").value_counts()
    assert set(counts.index) == set(config.CLASS_NAMES)
    assert counts.max() - counts.min() <= 1


def test_jenks_finds_natural_groups():
    v = [0.01, 0.02, 0.03, 0.30, 0.31, 0.50, 0.52, 0.75, 0.76, 0.99, 1.0]
    b = index.jenks_breaks(v, 5)
    assert b[0] == 0.01 and b[-1] == 1.0
    assert b[1:5] == [0.03, 0.31, 0.52, 0.76]
    classes = index.classify(pd.Series(v), b, "jenks").tolist()
    assert classes == ["Very Low"] * 3 + ["Low"] * 2 + ["Moderate"] * 2 + ["High"] * 2 + ["Very High"] * 2


# ------------------------------------------------------------ name matching ---

@pytest.mark.parametrize("a,b", [
    ("Baguio City", "City of Baguio"),
    ("Baguio", "BAGUIO CITY"),
    ("Mt. Province", "Mountain Province"),
    ("MT PROVINCE", "Mountain Province"),
    ("Sto. Tomas", "Santo Tomas"),
    ("Sta. Marcela", "Santa Marcela"),
    ("  peñarrubia ", "PENARRUBIA"),
    ("PE�ARRUBIA", "Peñarrubia"),
    ("Licuan-Baay", "LICUAN BAAY"),
    ("Tabuk City (Kalinga)", "City of Tabuk"),
])
def test_clean_name_variants(a, b):
    assert io_loader.clean_name(a) == io_loader.clean_name(b)


def test_match_to_gis(gaz):
    m = io_loader.match_name("City of Baguio", "BENGUET", "municipal", gaz)
    assert m["area_key"] == "BENGUET|BAGUIO" and m["method"] == "exact"
    m = io_loader.match_name("Sta. Marcela", None, "municipal", gaz)
    assert m["area_key"] == "APAYAO|SANTA MARCELA"
    m = io_loader.match_name("Mt. Province", None, "provincial", gaz)
    assert m["area_key"] == "MOUNTAIN PROVINCE"


def test_fuzzy_and_unmatched(gaz):
    m = io_loader.match_name("Kabugaoo", "APAYAO", "municipal", gaz)
    assert m["method"] == "fuzzy" and m["area_key"] == "APAYAO|KABUGAO"
    m = io_loader.match_name("Atlantis", None, "municipal", gaz)
    assert m["area_key"] is None and m["method"] == "unmatched" and len(m["suggestions"]) == 3


def test_manual_match_overrides(gaz):
    m = io_loader.match_name("Atlantis", None, "municipal", gaz, {"damage|Atlantis": "ABRA|TUBO"}, "damage")
    assert m["area_key"] == "ABRA|TUBO" and m["method"] == "manual"


def test_cross_province_match_is_flagged(gaz):
    # Paracelis is listed under the Kalinga block in the damage file but belongs to Mountain Province
    m = io_loader.match_name("PARACELIS", "KALINGA", "municipal", gaz)
    assert m["area_key"] == "MOUNTAIN PROVINCE|PARACELIS" and m["method"] == "exact (other province)"


# -------------------------------------------------------------- sample data ---

def test_sample_inputs_fully_matched(sample, gaz):
    assert all(r.ok for r in sample.values())
    assert sample["drought"].level == "provincial" and len(sample["drought"].data) == 6
    for ds in ("damage", "crops"):
        rep = sample[ds].report
        assert rep["n_unmatched"] == 0 and not rep["missing_areas"]
        assert len(sample[ds].data) == len(gaz.muni) == 77
        assert rep["n_subtotal_rows"] == 7  # CAR + 6 provinces


def test_sample_values(sample):
    d = sample["drought"].data
    assert d.loc["ABRA", "hazard_raw"] == 1 + 2 + 2 + 3 + 3 + 3
    assert d.loc["BENGUET", "hazard_raw"] == 0 + 1 + 2 + 2 + 3 + 3
    c = sample["crops"].data
    assert c.loc["KALINGA|TABUK", "crops_raw"] == pytest.approx(1336 + 7740.4)
    assert c.loc["BENGUET|BAGUIO", "crops_raw"] == 0  # blank rice cell → 0
    dm = sample["damage"].data
    assert dm.loc["APAYAO|FLORA", "damage_raw"] == pytest.approx(1992.39 / 3)


def test_envi_end_to_end(sample, gaz):
    df, meta = index.compute_envi(sample, gaz, EQUAL)
    assert len(df) == 77 and df.envi.notna().all()
    assert df.envi.between(0, 1).all()
    for k in ("hazard", "damage", "crops"):
        assert df[f"{k}_norm"].min() == 0 and df[f"{k}_norm"].max() == 1
    # ENVI = mean of the three normalized indicators with equal weights
    row = df.iloc[0]
    assert row.envi == pytest.approx((row.hazard_norm + row.damage_norm + row.crops_norm) / 3)
    assert df["rank"].iloc[0] == 1 and df.envi.is_monotonic_decreasing
    assert sum(meta["summary"]["class_counts"].values()) == 77


def test_missing_area_flagged_as_nodata(gaz):
    csv = b"ID,PROVINCE,October,November\n65,Abra,drought,drought\n66,Benguet,dry spell,drought\n"
    crops = io.BytesIO()
    pd.DataFrame({"PSGC": ["PH140101000"], "AREA": ["Bangued"], "Rice Total": [10.0]}).to_excel(crops, index=False)
    dmg = io.BytesIO()
    pd.DataFrame({"MUNICIPALITY_CLEAN": ["BANGUED", "TUBA"], "RICE_DMG_2019": [5.0, 1.0]}).to_excel(dmg, index=False)
    res = io_loader.load_all({"drought": (csv, "d.csv"), "damage": (dmg.getvalue(), "h.xlsx"),
                              "crops": (crops.getvalue(), "c.xlsx")}, gaz)
    df, meta = index.compute_envi(res, gaz, EQUAL)
    assert len(df) == 77
    assert df.loc[df.area == "Bangued", "envi_class"].iloc[0] != config.NO_DATA_LABEL
    assert meta["n_nodata"] == 76
    df0, meta0 = index.compute_envi(res, gaz, {**EQUAL, "missing_policy": "zero"})
    assert meta0["n_nodata"] == 0


def test_unknown_drought_category_is_an_error(gaz):
    res = io_loader.load_drought(b"PROVINCE,October\nAbra,very dry\n", "d.csv", gaz)
    assert not res.ok and "Unknown drought categories" in res.report["errors"][0]


def test_numeric_rainfall_forecast(gaz):
    csv = b"PROVINCE,October,November\nAbra,40,60\nBenguet,100,120\nApayao,70,70\n"
    res = io_loader.load_drought(csv, "d.csv", gaz, {**config.DEFAULT_SETTINGS})
    assert res.ok and res.report["hazard_direction"] == "lower_worse"
    norm, _ = normalize_hazard(res.data.hazard_raw, res.report)
    assert norm["ABRA"] == 1.0 and norm["BENGUET"] == 0.0


def test_templates_roundtrip(tmp_path, gaz):
    paths = io_loader.write_templates(tmp_path, gaz)
    assert [p.name for p in paths] == ["drought forecast.csv", "historical damage.xlsx",
                                       "standing crops ao sept 15 2026.xlsx"]
    blank = io_loader.load_crops(paths[2].read_bytes(), paths[2].name, gaz)
    assert not blank.ok  # no values yet
    filled = pd.read_excel(paths[2])
    filled["Rice Total"] = 1.0
    buf = io.BytesIO()
    filled.to_excel(buf, index=False)
    res = io_loader.load_crops(buf.getvalue(), "c.xlsx", gaz)
    assert res.ok and res.report["n_unmatched"] == 0 and not res.report["missing_areas"]
