from pathlib import Path

from agriclimate import pagasa_tc as tc
from agriclimate import reference

FIXTURE = Path(__file__).parent / "fixtures" / "pagasa_tc_rosal_tcb4.html"    # PAGASA, 21 Oct 2026 5 AM (TCB #4)


def html():
    return FIXTURE.read_text(encoding="utf-8")


def test_reads_the_bulletin():
    (b,) = tc.parse_page(html())
    assert (b["bulletin_no"], b["category"], b["name"]) == (4, "Super Typhoon", "ROSAL")
    assert b["issued_at"] == "2026-10-21T05:00:00"
    assert (b["lat"], b["lon"], b["max_wind_kmh"], b["gust_kmh"]) == (17.6, 131.1, 215, 265)
    assert b["movement"] == "Moving West Northwestward at 30 km/h"
    assert len(b["forecast"]) == 7 and "OUTSIDE PAR" in b["forecast"][-1]["where"]
    assert b["track_image"].endswith("/track_rosal.png")
    assert [g["day"] for g in b["gusts"]] == ["Today", "Tomorrow", "Friday"]
    assert tc._mentions_car(b["gusts"][0]["areas"])            # "… Cordillera Administrative Region …"
    assert set(b["signals"]) == {1} and b["signals"][1]["what_to_do"]


def test_car_municipalities_under_signal():
    p = tc.build_from_pagasa(html=html())["payload"]
    assert p["type"] == "tc_advisory" and p["ok"]
    assert p["summary"]["car_by_signal"] == {"1": ["APAYAO|CALANASAN", "APAYAO|FLORA", "APAYAO|KABUGAO", "APAYAO|LUNA",
                                                   "APAYAO|PUDTOL", "APAYAO|SANTA MARCELA"]}
    values = p["layers"][0]["values"]
    assert values["APAYAO|LUNA"]["class"] == "Wind Signal No. 1"
    assert values["BENGUET|LA TRINIDAD"]["class"] == "No wind signal"
    assert p["period"]["label"] == "Super Typhoon ROSAL – TC Bulletin #4, 5:00 AM, 21 October 2026"
    assert p["texts"]["recommendations"].startswith("Signal No. 1 in Apayao:")


def test_province_wording():
    signals = {
        2: {"luzon": "the northern portion of Abra (Tineg, Lacub), Kalinga, and the northern portion of Mountain Province (Barlig)"},
        1: {"luzon": "the rest of Abra, Ifugao, Baguio City, mainland Cagayan, and the remaining portion of Mountain Province"},
    }
    got, _ = tc.car_signals(signals)
    g = reference.gazetteer_table()
    abra = set(g.area_key[g.area_key.str.startswith("ABRA|")])
    assert got["ABRA|TINEG"] == 2 and got["ABRA|LACUB"] == 2
    assert all(got[k] == 1 for k in abra - {"ABRA|TINEG", "ABRA|LACUB"})       # "the rest of Abra"
    assert all(got[k] == 2 for k in g.area_key if k.startswith("KALINGA|"))
    assert got["MOUNTAIN PROVINCE|BARLIG"] == 2 and got["MOUNTAIN PROVINCE|BONTOC"] == 1
    assert all(got[k] == 1 for k in g.area_key if k.startswith("IFUGAO|"))
    assert got["BENGUET|BAGUIO"] == 1 and "BENGUET|LA TRINIDAD" not in got
    assert not any(k.startswith("APAYAO|") for k in got)


PDF = Path(__file__).parent / "fixtures" / "pagasa_tc_rosal_tcb4.pdf"     # the same bulletin as PDF


def test_track_and_wind_extent_from_the_pdf():
    d = tc.parse_pdf(PDF.read_bytes())
    assert d["wind_extent_km"] == 780 and d["pressure_hpa"] == 900
    assert [p["hours"] for p in d["track"]] == [12, 24, 36, 48, 60, 72, 96]
    first, last = d["track"][0], d["track"][-1]
    assert (first["lat"], first["lon"], first["wind_kmh"], first["cat"]) == (18.6, 129.1, 215, "STY")
    assert first["time"] == "2:00 PM 21 October 2026"
    assert last["outside_par"] and last["cat"] == "STS"


def test_track_buffer_and_distance_to_car():
    p = tc.build_from_pagasa(html=html(), pdf=PDF.read_bytes())["payload"]
    d = p["summary"]["car_distance"]
    assert 500 <= d["closest_km"] <= 600 and d["closest_time"] == "2:00 PM 22 October 2026"
    assert d["now_km"] > d["closest_km"] and d["car_in_buffer"]              # within 780 km of the track
    assert not d["car_in_strong_winds_now"]                                  # 1005 km away now, circle 780 km
    kinds = [f["properties"]["kind"] for f in p["tc"]["track_geojson"]["features"]]
    assert kinds[:5] == ["par", "cone", "strong_winds", "track", "now"] and kinds.count("forecast") == 7


TRACK_PNG = Path(__file__).parent / "fixtures" / "pagasa_tc_rosal_tcb4_track.png"   # PAGASA's track image, same bulletin


def test_storm_force_circle_measured_on_the_pagasa_image():
    # yellow circle = 780 km (bulletin); the red one is about 0.36 of it on PAGASA's image
    assert 250 <= tc.storm_force_km(TRACK_PNG.read_bytes(), 780) <= 310
    p = tc.build_from_pagasa(html=html(), pdf=PDF.read_bytes(), track_png=TRACK_PNG.read_bytes())["payload"]
    kinds = [f["properties"]["kind"] for f in p["tc"]["track_geojson"]["features"]]
    assert kinds[:5] == ["par", "cone", "strong_winds", "storm_force", "track"]
    assert tc.storm_force_km(b"", 780) is None


def test_without_the_pdf_the_map_has_no_track():
    p = tc.build_from_pagasa(html=html())["payload"]
    assert "car_distance" not in p["summary"]
    assert [f["properties"]["kind"] for f in p["tc"]["track_geojson"]["features"]] == ["par", "now"]
    assert any("forecast track" in w for w in p["report"]["warnings"])


def test_exports_are_one_a4_page_and_the_facebook_posts(tmp_path):
    from agriclimate import exports
    p = tc.build_from_pagasa(html=html(), pdf=PDF.read_bytes())["payload"]
    p["tc"]["track_image"] = None                                         # no network in tests: our own track map
    m = exports.export_product(p, tmp_path, {})
    # A4 first; then the Facebook posts: the advisory (track first – no title page), what to do now, during/after
    assert [x["layer"] for x in m["maps"]] == ["a4", "advisory", "recommendations", "recommendations_2", "crops"]
    a4 = m["maps"][0]
    assert (tmp_path / a4["pdf"]).read_bytes()[:5] == b"%PDF-"
    from PIL import Image
    assert Image.open(tmp_path / a4["poster"]).size == (3720, 5262)       # A4 at 450 dpi
    assert all(Image.open(tmp_path / x["social"]).size == (2160, 2700) for x in m["maps"][1:])


ADVISORY = Path(__file__).parent / "fixtures" / "pagasa_weather_advisory_3.html"
REGIONAL = Path(__file__).parent / "fixtures" / "pagasa_nlprsd_no_warning.html"


def test_heavy_rainfall_from_the_weather_advisory():
    a = tc.parse_weather_advisory(ADVISORY.read_text(encoding="utf-8"))
    assert a["number"] == 3 and a["days"] == ["Today", "Tomorrow", "Friday (October 23)"]
    rows = {r["class"]: r["by_day"] for r in a["rows"]}
    assert rows["100–200 mm"] == {"Today": [], "Tomorrow": ["Batanes"], "Friday (October 23)": []}
    assert rows["50–100 mm"]["Today"] == ["Ilocos Norte", "Apayao", "Cagayan"]
    assert a["car"] == {"Apayao": [("Today", "50–100 mm"), ("Tomorrow", "50–100 mm")]}
    assert tc.parse_regional_warnings(REGIONAL.read_text(encoding="utf-8")) == []      # none in effect


def test_one_cell_per_day():
    assert tc._cells("- Batanes -", 3) == [[], ["Batanes"], []]
    assert tc._cells("Abra and Benguet Mountain Province, Ifugao, and Kalinga -", 3) == [
        ["Abra", "Benguet"], ["Mountain Province", "Ifugao", "Kalinga"], []]


def test_recommendations_get_more_urgent_as_the_storm_nears():
    p = tc.build_from_pagasa(html=html(), pdf=PDF.read_bytes(), advisory_html=ADVISORY.read_text(encoding="utf-8"),
                             regional_html=REGIONAL.read_text(encoding="utf-8"))["payload"]
    assert p["summary"]["situation"]["stage"] == "approaching" and p["summary"]["situation"]["hours_to_closest"] == 33
    rec = p["texts"]["recommendations"]
    assert "Heavy rain in Apayao today and tomorrow (50–100 mm)" in rec
    assert "Before the storm – within 24 hours (Apayao):" in rec
    assert "During the storm:" in rec and "After the storm:" in rec
    near = tc.recommendations(2, ["Apayao"], {}, [], hours_to_closest=10, in_buffer=True)
    assert "NOW – within 12 hours (Apayao):" in near and "Signal No. 2" in near
    far = tc.recommendations(0, [], {}, [], hours_to_closest=None, in_buffer=False)
    assert far.startswith("Prepare now") and "During the storm" not in far


def test_no_active_cyclone():
    res = tc.build_from_pagasa(html="<html><body><h1>No Active Tropical Cyclone</h1></body></html>")
    assert not res["ok"] and "no active tropical cyclone" in res["error"].lower()
