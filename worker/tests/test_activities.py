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
    # one activity per row; the third takes place in two whole provinces
    assert res["count"] == 3
    one, two, three = res["rows"]
    assert one["area_keys"] == ["ABRA|BANGUED"] and two["area_keys"] == ["KALINGA|TABUK"]
    g = reference.gazetteer_table()
    assert sorted(three["area_keys"]) == sorted(g.area_key[g.area_key.str.startswith(("IFUGAO|", "KALINGA|"))])
    assert one["status"] == "completed" and one["hazard"] == "general"          # no MAP column: every map
    assert one["start_date"] == "2026-03-01" and one["budget"] == 160000
    # No. of units, and the beneficiaries: individual farmers or farmer groups (FCA) and how many
    assert (one["units"], one["beneficiary_type"], one["beneficiaries"]) == (2, "individual", 2)
    assert (two["units"], two["beneficiary_type"], two["beneficiaries"]) == (1, "fca", 1)
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


def test_problems_are_warnings_and_the_row_is_kept():
    cols = ["MUNICIPALITY", "ACTIVITY", "STATUS", "START_DATE", "END_DATE", "BENEFICIARIES"]
    data = _xlsx([["Bangued", "Training", "Maybe", None, None, None],
                  ["Atlantis", "Training", "Done", None, None, None],
                  ["Tayum", "Training", "Done", "2026-12-01", "2026-11-01", None],
                  ["Tayum", "Training", "Done", "soon", None, "many"],
                  ["Tayum", "", "Done", None, None, None],
                  ["Tayum", "Seeds", None, None, None, 5]], cols)
    res = activities.parse(data, "bad.xlsx")
    assert res["ok"], res["report"]["errors"]
    warns = " | ".join(res["report"]["warnings"])
    assert "Row 2: STATUS 'Maybe' – saved as To conduct" in warns
    assert "Row 3: 'Atlantis' is not a CAR municipality" in warns and "row skipped" in warns
    assert "Row 4: the end date 2026-11-01 is before the start date 2026-12-01" in warns
    assert "Row 5: 'soon' is not a date" in warns and "Row 5: 'many' is not a number" in warns
    assert "Row 6: the ACTIVITY is empty – row skipped." in warns
    assert "Row 7: STATUS is empty – saved as To conduct" in warns
    by_row = {r["row"]: r for r in res["rows"]}
    assert sorted(by_row) == [2, 4, 5, 7]                           # rows 3 (no place) and 6 (no activity) skipped
    assert by_row[2]["status"] == "to_conduct" and by_row[4]["end_date"] is None and by_row[4]["start_date"]
    assert by_row[5]["start_date"] is None and by_row[5]["beneficiaries"] is None
    assert res["report"]["warnings"][0].startswith("2 row(s) skipped")


def test_no_status_column_and_province_only():
    data = _xlsx([["Abra", "", "Seed distribution"], ["Narnia", "Bangued; Atlantis", "PISOS"]],
                 ["PROVINCE", "MUNICIPALITY", "ACTIVITY"])
    res = activities.parse(data, "x.xlsx")
    assert res["ok"] and [r["status"] for r in res["rows"]] == ["to_conduct", "to_conduct"]
    assert len(res["rows"][0]["area_keys"]) == 27 and res["rows"][1]["area_keys"] == ["ABRA|BANGUED"]
    assert any("No STATUS column" in w for w in res["report"]["warnings"])


def test_missing_columns():
    data = _xlsx([["Bangued", "x"]], ["MUNICIPALITY", "NOTES"])
    res = activities.parse(data, "x.xlsx")
    assert not res["ok"] and "Missing column(s): ACTIVITY." in res["report"]["errors"][0]


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
    warns = " | ".join(res["report"]["warnings"])
    assert res["ok"]
    assert "Row 4: PROVINCE 'Narnia' is not a CAR province – ignored." in warns
    assert "Row 5: 'Atlantis' is not a CAR municipality" in warns
    # Narnia + All: no known place, so the row is skipped (not spread over the whole CAR); Bangued kept, Atlantis left out
    assert [len(r["area_keys"]) for r in res["rows"]] == [77, 77, 1]
    assert "Row 4: no place it can be shown on (x) – row skipped" in warns


def test_beneficiary_type_words():
    cols = ["Municipality", "Activity", "No. of Units", "Status", "Beneficiary Type", "Beneficiaries"]
    data = _xlsx([["Bangued", "Cistern", 3, "Completed", "Farmer Cooperative", 1],
                  ["Bangued", "PISOS", 2, "Completed", "Farmers", 2],
                  ["Bangued", "Seeds", None, "Completed", None, 40],
                  ["Bangued", "Training", None, "Completed", "Barangay", 10]], cols)
    res = activities.parse(data, "list.xlsx")
    assert [r["beneficiary_type"] for r in res["rows"]][:3] == ["fca", "individual", None]
    assert res["rows"][0]["units"] == 3
    assert [r["beneficiary_type"] for r in res["rows"]][3] is None
    assert any("BENEFICIARY_TYPE 'Barangay' not known" in w for w in res["report"]["warnings"])
