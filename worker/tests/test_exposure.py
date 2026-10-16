"""HVC (HVCDP Regional Summary) and livestock inputs of the ENVI exposure indicator."""
import gzip
import io

import pandas as pd
import pytest

from agriclimate import templates
from agriclimate.envi import config, exposure, index, io_loader

AS_OF = {**config.DEFAULT_SETTINGS, "crops_as_of": "2026-09-30", "period_start": "2026-10", "period_end": "2027-03",
         "livestock_as_of": "2026-06-30"}


@pytest.fixture(scope="module")
def gaz():
    return io_loader.load_gazetteer()


def summary_csv(rows: list[tuple]) -> bytes:
    """A miniature HVCDP Regional Summary (same headers, a title-less first row like the real sheet)."""
    head = ["MONTH PLANTED", "PROVINCE", "MUNICIPALITY", "BARANGAY", "NAME OF COMMODITY", "CROP GROUP",
            "CROPS AREA PLANTED (hectares)", "TARGET MONTH OF HARVEST", "DATE PLANTED", "NEWLY PLANTED ",
            "MULTI HARVEST"]
    out = []
    for prov, muni, com, grp, ha, planted, harvest, multi in rows:
        out.append([planted[:8] + "01", prov, muni, "", com, grp, ha, harvest, planted, 0, multi])
    return pd.DataFrame(out, columns=head).to_csv(index=False).encode()


ROWS = [
    # province, municipality, commodity, group, ha, date planted, target harvest, multi harvest
    ("BENGUET", "Atok", "Cabbage", "Upland Vegetable", 10.0, "2026-08-15", "2026-11-10", ""),   # standing
    ("BENGUET", "Atok", "cabbage", "Upland Vegetable", 5.0, "2026-05-15", "2026-08-10", ""),    # harvested
    ("BENGUET", "Atok", "Tomato", "Lowland Vegetable", 2.0, "2026-05-15", "2026-09-10", "YES"),  # still picked
    ("BENGUET", "Buguias", "Celery", "", 3.0, "2026-09-15", "", ""),                            # no group / date
    ("BENGUET", "Buguias", "Potato", "Upland Vegetable", 4.0, "2026-10-15", "2027-01-20", ""),  # after cutoff
    ("IFUGAO", "Kiangan", "Coffee Arabica/Robusta", "Plantation Crops", 6.0, "2026-02-15", "2026-06-01", ""),
    ("BAGUIO CITY", "Baguio City", "Lettuce", "Upland Vegetable", 1.0, "2026-09-15", "2026-11-15", ""),
]


def test_hvc_standing_area_as_of_the_crops_date(gaz):
    res = exposure.load_hvc(summary_csv(ROWS), "summary.csv", gaz, AS_OF)
    assert res.ok, res.report["errors"]
    d = res.data
    assert d.at["BENGUET|ATOK", "hvc_short_ha"] == pytest.approx(12.0)      # 10 standing + 2 multi-harvest tomato
    assert d.at["BENGUET|BUGUIAS", "hvc_short_ha"] == pytest.approx(3.0)    # celery, duration estimated
    assert d.at["IFUGAO|KIANGAN", "hvc_perennial_ha"] == pytest.approx(6.0)  # coffee: standing after "harvest"
    assert d.at["BENGUET|BAGUIO", "hvc_ha"] == pytest.approx(1.0)           # "BAGUIO CITY" province → Benguet
    s = res.report["hvc_summary"]
    assert s["standing_ha"] == pytest.approx(22.0) and s["perennial_ha"] == pytest.approx(6.0)
    assert s["provinces_without_data"] == ["Abra", "Apayao", "Kalinga", "Mountain Province"]
    oct_, mar = s["outlook"][0], s["outlook"][-1]
    assert oct_["month"] == "2026-10" and oct_["short_cycle_ha"] == pytest.approx(16.0)  # all short-cycle standing
    assert mar["short_cycle_ha"] == 0 and mar["perennial_ha"] == pytest.approx(6.0)
    w = " ".join(res.report["warnings"])
    assert "Cabbage (Cabbage / cabbage)" in w            # spellings merged
    assert "no CROP GROUP" in w and "planted after September 30, 2026" in w and "No HVC records at all" in w


def test_hvc_needs_the_crops_date_and_the_summary_columns(gaz):
    res = exposure.load_hvc(summary_csv(ROWS), "s.csv", gaz, {**AS_OF, "crops_as_of": None})
    assert not res.ok and "standing crops as of" in res.report["errors"][0]
    bad = pd.DataFrame({"PROVINCE": ["Benguet"], "AREA": [1]}).to_csv(index=False).encode()
    assert not exposure.load_hvc(bad, "b.csv", gaz, AS_OF).ok


def test_hvc_compressed_csv_and_excel_serial_dates(gaz):
    df = pd.read_csv(io.BytesIO(summary_csv(ROWS)), dtype=str, keep_default_na=False)
    for c in ("MONTH PLANTED", "DATE PLANTED", "TARGET MONTH OF HARVEST"):   # what the upload page sends
        dt = pd.to_datetime(df[c], errors="coerce")
        df[c] = ((dt - exposure.EXCEL_EPOCH).dt.days).astype("Int64").astype(str).replace("<NA>", "")
    gz = gzip.compress(df.to_csv(index=False).encode())
    a = exposure.load_hvc(summary_csv(ROWS), "s.csv", gaz, AS_OF)
    b = exposure.load_hvc(gz, "s.csv.gz", gaz, AS_OF)
    assert b.ok and a.report["hvc_summary"] == b.report["hvc_summary"]


def da_form() -> bytes:
    """The DA inventory layout: title, two header rows, CAR total, province subtotal rows."""
    rows = [
        [None, None, "ANIMAL POPULATION INVENTORY 2026 (As of March, 2026)", None, None, None],
        ["PROVINCE", "MUNICIPALITY", "LIVESTOCK COMMODITIES (no. of heads)", None, "POULTRY", None],
        [None, None, "CATTLE", "CARABAO", "SWINE \n(Hi-breed)", "CHICKEN \n(Commercial)"],
        [None, "CAR TOTAL", 300, 30, 500, 10000],
        ["BENGUET", None, 999, 20, 400, 10000],
        [None, "ATOK", 100, 10, 200, 10000],
        [None, "BUGUIAS", 200, 10, 200, None],
        ["IFUGAO", None, 0, 10, 100, 0],
        [None, "KIANGAN", 0, 10, 100, 0],
    ]
    buf = io.BytesIO()
    pd.DataFrame(rows).to_excel(buf, header=False, index=False)
    return buf.getvalue()


def test_livestock_da_form_to_tlu(gaz):
    res = exposure.load_livestock(da_form(), "livestock.xlsx", gaz, AS_OF)
    assert res.ok, res.report["errors"]
    d = res.data
    assert d.at["BENGUET|ATOK", "livestock_raw"] == pytest.approx(100 * .65 + 10 * .7 + 200 * .25 + 10000 * .01)
    assert d.at["BENGUET|ATOK", "livestock_heads"] == 10310
    assert res.report["n_matched"] == 3
    w = " ".join(res.report["warnings"])
    assert "Benguet: the province total row differs" in w and "Cattle 999 vs 300" in w
    assert "As of March, 2026" in w                              # title date ≠ the date entered
    assert "municipalities are not in the file" in w


def test_livestock_template_roundtrip(gaz):
    _, data = templates.template("livestock")
    df = pd.read_excel(io.BytesIO(data), sheet_name="DATA")
    df["CATTLE"], df["CHICKEN_NATIVE"], df["BEES"] = 10, 100, 5
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    res = exposure.load_livestock(buf.getvalue(), "t.xlsx", gaz, AS_OF)
    assert res.ok and res.report["n_matched"] == 77 and not res.report["missing_areas"]
    assert res.data.livestock_raw.round(4).eq(10 * .65 + 100 * .01).all()   # bee colonies are not converted
    assert res.report["livestock_summary"]["heads"]["Bees (colonies)"] == 5 * 77


def test_livestock_needs_its_date(gaz):
    res = exposure.load_livestock(da_form(), "l.xlsx", gaz, {**AS_OF, "livestock_as_of": None})
    assert not res.ok and "livestock inventory as of" in res.report["errors"][0]


# ------------------------------------------------------------------ ENVI ---

@pytest.fixture(scope="module")
def core(gaz):
    files = {k: (p, p.name) for k, p in config.DEFAULT_FILES.items()}
    return io_loader.load_all(files, gaz, AS_OF)


def test_envi_adds_hvc_hectares_and_blends_livestock(core, gaz):
    base, _ = index.compute_envi(core, gaz, AS_OF)
    hvc = exposure.load_hvc(summary_csv(ROWS), "s.csv", gaz, AS_OF)
    lv = exposure.load_livestock(da_form(), "l.xlsx", gaz, AS_OF)
    df, meta = index.compute_envi({**core, "hvc": hvc, "livestock": lv}, gaz, {**AS_OF, "livestock_share": 0.4})
    b, t = base.set_index("area_key"), df.set_index("area_key")
    atok = "BENGUET|ATOK"
    assert t.at[atok, "crops_raw"] == pytest.approx(b.at[atok, "crops_raw"] + 12.0)     # hectares + hectares
    assert t.at[atok, "crop_hvc"] == pytest.approx(12.0)
    expected = 0.6 * index.minmax(t.crops_raw) + 0.4 * index.minmax(t.livestock_raw)  # heads never added to ha
    assert (t.crops_norm - expected).abs().max() < 1e-12
    assert meta["crops_label"] == config.EXPOSURE_LABEL and meta["exposure"]["livestock_share"] == 0.4
    assert "HVC" in meta["summary"]["crop_at_risk_by_crop"] and "livestock_total_tlu" in meta["summary"]
    heads = meta["summary"]["livestock_at_risk_heads"]       # species in the High / Very High areas, by TLU
    risk = t[t.envi_class.isin(["High", "Very High"])]
    assert heads.get("Cattle", 0) == int(risk.lv_CATTLE.sum()) and "Bees (colonies)" not in heads
    assert "never added" in meta["crops_note"]


def test_envi_without_exposure_inputs_is_unchanged(core, gaz):
    df, meta = index.compute_envi(core, gaz, AS_OF)
    assert "livestock_raw" not in df and "crop_hvc" not in df
    assert (df.crops_norm - index.minmax(df.crops_raw)).abs().max() == 0
    assert meta["crops_label"] == "Standing crops" and not meta["exposure"]["livestock"]


def test_crops_file_cannot_hold_heads_or_a_second_hvc(gaz):
    crops = pd.DataFrame({"PSGC": [""], "AREA": ["Atok"], "Rice Total": [5], "HVC": [3], "Livestock": [900]})
    buf = io.BytesIO()
    crops.to_excel(buf, index=False)
    files = {"crops": (buf.getvalue(), "crops.xlsx"), "hvc": (summary_csv(ROWS), "s.csv")}
    errors = " ".join(io_loader.load_all(files, gaz, AS_OF)["crops"].report["errors"])
    assert "Livestock look like livestock" in errors and "HVC would be counted twice" in errors
    alone = io_loader.load_all({"crops": files["crops"]}, gaz, AS_OF)["crops"].report["errors"]
    assert len(alone) == 1                     # an HVC column on its own is fine (hectares)


def test_livestock_share_is_validated(core, gaz):
    lv = exposure.load_livestock(da_form(), "l.xlsx", gaz, AS_OF)
    with pytest.raises(ValueError, match="between 0 and 1"):
        index.compute_envi({**core, "livestock": lv}, gaz, {**AS_OF, "livestock_share": 1.5})
