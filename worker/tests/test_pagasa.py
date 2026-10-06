"""PAGASA seasonal forecast: reading the CAR rows of the published table images (offline fixtures)."""
from pathlib import Path

import pytest

from agriclimate import pagasa_seasonal as ps

F = Path(__file__).parent / "fixtures" / "pagasa"


def _fetch(url):
    f = F / url.rsplit("/", 1)[-1]
    if not f.exists():
        raise RuntimeError("not in the fixtures")
    return f.read_bytes()


@pytest.fixture(scope="module")
def data():
    html = (F / "seasonal.html").read_text(encoding="utf-8", errors="replace")
    return ps.read_pagasa(html, _fetch)


def test_title_parsing():
    t = ps.parse_title("FORECAST RAINFALL in mm (October 2026 - March 2027) as of September 2026")
    assert t == {"kind": "mm", "start": "2026-10", "end": "2027-03", "as_of": "2026-09"}
    assert ps.parse_title("FORECAST RAINFALL in % Normal (October 2026 - March 2027) as of September 2026")["kind"] == "pct"


def test_car_values_read_from_the_mm_table(data):
    assert not data["report"]["errors"]
    assert data["months"] == ["2026-10", "2026-11", "2026-12", "2027-01", "2027-02", "2027-03"]
    mm = data["mm"]
    assert set(mm) == set(ps.CAR)
    # values as printed in PAGASA's image (MIN / MAX / MEAN)
    assert mm["ABRA"]["2026-10"] == {"min": 53.5, "max": 206.3, "mean": 135.4}
    assert mm["APAYAO"]["2026-11"]["mean"] == 70.9
    assert mm["MOUNTAIN PROVINCE"]["2027-03"] == {"min": 8.2, "max": 18.8, "mean": 12.4}
    assert all(c["min"] <= c["mean"] <= c["max"] for p in mm.values() for c in p.values() if "min" in c)


def test_pct_normal_table_and_low_confidence_flag(data):
    assert data["pct"]["ABRA"]["2026-10"]["value"] == 53.2 and data["pct"]["KALINGA"]["2027-03"]["value"] == 11.8
    # a cell OCR is unsure about is reported for the admin to check
    assert any("Low OCR confidence" in w for w in data["report"]["warnings"])


def test_seasonal_payload_from_pagasa():
    html = (F / "seasonal.html").read_text(encoding="utf-8", errors="replace")
    p = ps.build_from_pagasa({}, html, _fetch)
    assert p["ok"], p["report"]["errors"]
    assert p["period"]["label"] == "October 2026 – March 2027" and p["issued"] == "2026-09-01"
    oct_ = p["layers"][0]["values"]
    assert oct_["ABRA|BANGUED"]["value"] == 135.4 and oct_["ABRA|TUBO"]["value"] == 135.4   # provincial value
    assert any(l["id"] == "pct_normal" for l in p["layers"])
    assert p["pagasa"]["images"]["mm"].endswith("2026_6ab36040bee12.jpg") and len(p["pagasa"]["table"]) == 36
    assert "PAGASA" in p["texts"]["sources"]
