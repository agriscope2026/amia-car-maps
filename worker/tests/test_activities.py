import io

import pandas as pd

from agriclimate import activities, reference, templates


def _xlsx(rows: list[list], columns: list[str], title_rows: int = 0) -> bytes:
    buf = io.BytesIO()
    pd.DataFrame(rows, columns=columns).to_excel(buf, index=False, startrow=title_rows)
    return buf.getvalue()


def test_template_examples_parse():
    name, data = templates.template("activities")
    assert name == "activities_template.xlsx"
    res = activities.parse(data, name)
    assert res["ok"], res["report"]
    # one activity per row: the second takes place in two municipalities, the third in two whole provinces
    assert res["count"] == 3
    one, two, three = res["rows"]
    assert one["area_keys"] == ["ABRA|BANGUED"]
    assert two["area_keys"] == ["BENGUET|LA TRINIDAD", "BENGUET|TUBLAY"]
    g = reference.gazetteer_table()
    assert sorted(three["area_keys"]) == sorted(g.area_key[g.area_key.str.startswith(("IFUGAO|", "KALINGA|"))])
    first = one
    assert first["status"] == "ongoing" and first["hazard"] == "envi"
    assert first["start_date"] == "2026-10-15" and first["beneficiaries"] == 250 and first["budget"] == 375000
    assert any("example rows" in w for w in res["report"]["warnings"])


def test_aliases_dates_and_title_rows():
    cols = ["Province", "City/Municipality", "Activity", "Status", "Hazard", "Date Started", "Budget (PHP)"]
    data = _xlsx([["Benguet", "Baguio City", "SWIP desilting", "on-going", "Drought", "10/01/2026", "₱1,250,000"],
                  ["Ifugao", "Banaue", "Seed buffer stocking", "Planned", "", "2026-11", None]], cols, title_rows=2)
    res = activities.parse(data, "list.xlsx")
    assert res["ok"], res["report"]
    a, b = res["rows"]
    assert a["area_keys"] == ["BENGUET|BAGUIO"] and a["status"] == "ongoing" and a["hazard"] == "drought"
    assert a["start_date"] == "2026-10-01" and a["budget"] == 1250000
    assert b["status"] == "to_conduct" and b["hazard"] == "general" and b["start_date"] == "2026-11-01"


def test_errors_name_the_row():
    cols = ["MUNICIPALITY", "ACTIVITY", "STATUS", "START_DATE", "END_DATE", "BENEFICIARIES"]
    data = _xlsx([["Bangued", "Training", "Maybe", None, None, None],
                  ["Atlantis", "Training", "Done", None, None, None],
                  ["Tayum", "Training", "Done", "2026-12-01", "2026-11-01", None],
                  ["Tayum", "Training", "Done", None, None, "many"],
                  ["Tayum", "", "Done", None, None, None]], cols)
    res = activities.parse(data, "bad.xlsx")
    assert not res["ok"]
    errs = " | ".join(res["report"]["errors"])
    assert "Row 2: STATUS 'Maybe'" in errs
    assert "Row 3: 'Atlantis' is not a CAR municipality" in errs
    assert "Row 4: the end date" in errs
    assert "Row 5: 'many' is not a number" in errs
    assert "Row 6: the ACTIVITY is empty" in errs


def test_missing_columns():
    data = _xlsx([["Bangued", "x"]], ["MUNICIPALITY", "NOTES"])
    res = activities.parse(data, "x.xlsx")
    assert not res["ok"] and "Missing column(s): ACTIVITY, STATUS" in res["report"]["errors"][0]


def test_csv():
    csv = "MUNICIPALITY,PROVINCE,ACTIVITY,STATUS,MAP\nLagawe,Ifugao,Cloud seeding coordination,Completed,El Niño\n"
    res = activities.parse(csv.encode(), "a.csv")
    assert res["ok"], res["report"]
    assert res["rows"][0]["area_keys"] == ["IFUGAO|LAGAWE"] and res["rows"][0]["hazard"] == "envi"


def test_whole_car_and_unknown_province():
    cols = ["PROVINCE", "MUNICIPALITY", "ACTIVITY", "STATUS"]
    data = _xlsx([["All", "All", "Regional El Niño summit", "Completed"],
                  ["", "All", "Radio advisory", "Ongoing"],
                  ["Narnia", "All", "x", "Ongoing"],
                  ["Abra", "Bangued; Atlantis", "y", "Ongoing"]], cols)
    res = activities.parse(data, "x.xlsx")
    errs = " | ".join(res["report"]["errors"])
    assert "Row 4: PROVINCE 'Narnia' is not a CAR province." in errs
    assert "Row 5: 'Atlantis' is not a CAR municipality" in errs
    assert [len(r["area_keys"]) for r in res["rows"]] == [77, 77]
