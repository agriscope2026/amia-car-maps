"""Rice / corn self-sufficiency (SSL) read from the action-plan workbook."""
import io

import openpyxl
import pytest

from agriclimate import ssl, templates

PROVS = ["ABRA", "APAYAO", "BENGUET", "IFUGAO", "KALINGA", "MP"]


def workbook(rice_effect=(0.496, 1.5585, 0.0782, 0.2757, 0.9867, 0.1967), corn_error=True, drop_effect=False) -> bytes:
    """A miniature of the DA-RFO-CAR sheet: title rows, a utilization table, a RICE and a CORN block (SSL as % format)."""
    wb = openpyxl.Workbook()
    wb.active.title = "DATA"
    ws = wb.create_sheet("PROJECTED PDN LOSS AND SSL")
    ws["H2"] = "Total Production Utilization by province"
    for crop, top, effects in (("RICE", 10, rice_effect), ("CORN", 30, [None] * 6)):
        ws.cell(top, 1, "PROVINCE")
        ws.cell(top, 2, f"{crop} COMMODITY")
        ws.cell(top, 7, "Est.  Production (MT)\n ((Annual Target-EPYL)+harvested)*65.4% milling recovery)")
        ws.cell(top, 8, "Adjusted SSL (%) from PYL")
        ws.cell(top, 10, "Effect to SSL in  (% reduction)")
        ws.cell(top + 1, 2, "SELF SUFFICIENCY LEVEL (SSL) (%) (2024)")
        ws.cell(top + 1, 3, "Standing Crop (ha.) (as of October 15)")
        ws.cell(top + 1, 5, "HARVESTED (MT) 1st Sem")
        ws.cell(top + 1, 6, "CY 2026 Annual Target (MT)")
        ws.cell(top + 2, 3, "Reproductive (from newlyplanted to vegetative)")
        ws.cell(top + 2, 4, "Est Potential Yield Loss (MT)")
        ws.cell(top + 2, 9, "Final SSL")
        for i, p in enumerate(PROVS + ["CAR"]):
            r = top + 3 + i
            ws.cell(r, 1, p)
            base = 1.0 + i / 10
            ws.cell(r, 2, base).number_format = "0.00%"
            ws.cell(r, 3, 100.0 * (i + 1))
            ws.cell(r, 4, 350.0 * (i + 1))
            ws.cell(r, 5, 10.0)
            ws.cell(r, 6, 1000.0)
            ws.cell(r, 7, 777.0)
            eff = effects[i] if i < 6 else 0.02
            if eff is None:
                if corn_error:
                    for c in (8, 9, 10):
                        ws.cell(r, c, "#DIV/0!")
                continue
            ws.cell(r, 8, eff)
            ws.cell(r, 9, base - eff).number_format = "0.00%"
            if not drop_effect:
                ws.cell(r, 10, eff).number_format = "0.00%"
        ws.cell(top + 11, 1, "for identification")      # rows after the table are not provinces
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_reads_effect_per_province_in_percent():
    r = ssl.parse(workbook(), "plan.xlsx")
    assert r["ok"] and r["sheet"] == "PROJECTED PDN LOSS AND SSL"
    rice = r["crops"]["rice"]
    assert rice["ok"] and rice["ssl_year"] == "2024" and rice["standing_as_of"] == "October 15"
    abra = rice["provinces"]["ABRA"]
    assert abra["effect"] == pytest.approx(49.6) and abra["ssl"] == pytest.approx(100.0)
    assert abra["final_ssl"] == pytest.approx(50.4) and abra["standing_ha"] == 100 and abra["yield_loss_mt"] == 350
    # the production header mentions "harvested" and "annual target": each column belongs to one field only
    assert abra["production_mt"] == 777 and abra["harvested_mt"] == 10 and abra["target_mt"] == 1000
    assert set(rice["provinces"]) == {"ABRA", "APAYAO", "BENGUET", "IFUGAO", "KALINGA", "MOUNTAIN PROVINCE"}
    assert rice["car"]["label"] == "CAR"


def test_excel_errors_in_the_loss_keep_the_ssl_on_the_map():
    r = ssl.parse(workbook(), "plan.xlsx")
    corn = r["crops"]["corn"]
    # the map shows the SSL: corn has one even though its projected loss is #DIV/0!
    assert corn["ok"] and corn["provinces"]["ABRA"]["ssl"] == pytest.approx(100.0)
    assert corn["provinces"]["ABRA"]["effect"] is None and corn["provinces"]["ABRA"]["effect_error"] == "#DIV/0!"
    assert any("Corn: the projected loss" in w and "#DIV/0!" in w and "still shows their SSL" in w
               for w in r["warnings"])


def test_missing_cached_effect_is_recomputed_from_ssl_and_final():
    r = ssl.parse(workbook(drop_effect=True), "plan.xlsx")
    assert r["crops"]["rice"]["provinces"]["KALINGA"]["effect"] == pytest.approx(98.67)


def test_workbook_without_ssl_sheet_gives_nothing():
    wb = openpyxl.Workbook()
    buf = io.BytesIO()
    wb.save(buf)
    assert ssl.parse(buf.getvalue(), "plan.xlsx") is None
    assert ssl.parse(b"a,b\n1,2", "plan.csv") is None


def test_template_has_the_ssl_sheet_the_reader_understands():
    _, data = templates.template("activities")
    wb = openpyxl.load_workbook(io.BytesIO(data))
    assert ssl.TEMPLATE_SHEET in wb.sheetnames
    r = ssl.parse(data, "activities_template.xlsx")
    # an empty template: the sheet and both tables are found, but there is no SSL yet
    assert r is not None and set(r["crops"]) == {"rice", "corn"} and not r["ok"]
    assert set(r["crops"]["rice"]["provinces"]) == {"ABRA", "APAYAO", "BENGUET", "IFUGAO", "KALINGA",
                                                    "MOUNTAIN PROVINCE"}
