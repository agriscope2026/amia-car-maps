"""Generate SYNTHETIC rainfall sample files (for tests and the local demo only – not forecasts).

Values follow a smooth west–east / north–south gradient so maps look plausible; every file carries a
README row saying the data are synthetic. Run:  python -m scripts.make_demo_samples
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agriclimate import reference, templates  # noqa: E402

OUT = ROOT / "data" / "sample"
WARNING = "SYNTHETIC DEMO DATA – generated for testing the portal; NOT a PAGASA forecast."


def _centroids() -> pd.DataFrame:
    muni, _ = reference.boundaries()
    c = muni.geometry.representative_point()
    return pd.DataFrame({"area_key": muni.area_key, "x": c.x, "y": c.y}).set_index("area_key")


def _write(df: pd.DataFrame, name: str, notes: list[str]) -> Path:
    path = OUT / name
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        df.to_excel(xw, sheet_name="DATA", index=False)
        pd.DataFrame({"README": [WARNING] + notes}).to_excel(xw, sheet_name="README", index=False)
    return path


def main():
    g = reference.gazetteer_table()
    c = _centroids().reindex(g.area_key)
    xn = (c.x - c.x.min()) / (c.x.max() - c.x.min())   # 0 west → 1 east
    yn = (c.y - c.y.min()) / (c.y.max() - c.y.min())   # 0 south → 1 north
    rng = np.random.default_rng(2026)

    base = pd.DataFrame({"PSGC": g.psgc.values, "PROVINCE": g.province_label.values, "MUNICIPALITY": g.label.values})
    dekad = base.copy()
    wet = 0.65 * xn.values + 0.35 * yn.values
    for d in range(1, 11):                     # a rain event moving in around days 4–7
        peak = np.exp(-((d - 5.5) ** 2) / 4)
        dekad[f"DAY_{d}"] = np.round((1 + 28 * wet ** 1.5) * (0.4 + 2.2 * peak) + rng.normal(0, 1.5, len(g)), 1).clip(0)
    p1 = _write(dekad, "DEMO_rainfall_10day_2026-10-01.xlsx", templates.TEMPLATE_INFO["rainfall_dekad"][1])

    seas = base.copy()
    shape = {"OCT_2026": 1.0, "NOV_2026": 0.75, "DEC_2026": 0.45, "JAN_2027": 0.3, "FEB_2027": 0.22, "MAR_2027": 0.2}
    wet = 0.55 * xn.values + 0.45 * yn.values
    for col, f in shape.items():
        seas[col] = np.round(f * (60 + 520 * wet) + rng.normal(0, 8, len(g)), 0).clip(0)
    months = list(shape)
    seas["SEASON_TOTAL"] = seas[months].sum(axis=1)
    seas["NORMAL_MM"] = np.round(seas["SEASON_TOTAL"] / (0.55 + 0.8 * yn.values * 0.9 + rng.normal(0, .05, len(g))))
    seas["PCT_NORMAL"] = np.round(seas.SEASON_TOTAL / seas.NORMAL_MM * 100)
    p2 = _write(seas, "DEMO_rainfall_seasonal_2026-10_2027-03.xlsx", templates.TEMPLATE_INFO["rainfall_seasonal"][1])

    irr = pd.DataFrame([
        ("DEMO Abra River Irrigation System", "NIS", 17.565, 120.640, "Bangued", "Abra", "Abra River", 2150,
         "Operational"),
        ("DEMO Chico River Irrigation System", "NIS", 17.465, 121.420, "Tabuk", "Kalinga", "Chico River", 8700,
         "Operational"),
        ("DEMO Lamut CIS", "CIS", 16.660, 121.220, "Lamut", "Ifugao", "Lamut River", 410, "Operational"),
        ("DEMO Paracelis SWIP", "SWIP", 17.180, 121.410, "Paracelis", "Mountain Province", "Creek", 85,
         "For rehabilitation"),
        ("DEMO Pudtol SSIP", "SSIP", 18.230, 121.380, "Pudtol", "Apayao", "Apayao River", 40, "Operational"),
        ("DEMO Ambuklao Dam", "DAM", 16.465, 120.745, "Bokod", "Benguet", "Agno River", None, "Operational"),
    ], columns=["NAME", "TYPE", "LAT", "LON", "MUNICIPALITY", "PROVINCE", "RIVER", "SERVICE_AREA_HA", "STATUS"])
    irr["SOURCE"] = "Synthetic demo record (approximate location)"
    p3 = _write(irr, "DEMO_irrigation_sources.xlsx", templates.TEMPLATE_INFO["irrigation"][1])
    for p in (p1, p2, p3):
        print("wrote", p)


if __name__ == "__main__":
    main()
