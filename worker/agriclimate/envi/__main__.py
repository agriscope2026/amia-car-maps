"""Headless run: ``python -m envi [--drought F] [--damage F] [--crops F] [--weights a,b,c] [--classes equal]``."""
import argparse
import json
from pathlib import Path

from . import config, pipeline


def main():
    ap = argparse.ArgumentParser(description=config.APP_TITLE)
    for ds in ("drought", "damage", "crops"):
        ap.add_argument(f"--{ds}", type=Path, default=config.DEFAULT_FILES[ds])
    ap.add_argument("--weights", default=None, help="hazard,damage,crops (must sum to 1)")
    ap.add_argument("--classes", choices=["equal", "quantile", "jenks"], default="equal")
    ap.add_argument("--layout", choices=["qgz", "qpt"], default="qgz")
    ap.add_argument("--renderer", choices=["auto", "qgis", "matplotlib"], default="auto")
    ap.add_argument("--reporting-month", help="month the report is issued (as of), YYYY-MM")
    ap.add_argument("--period", help="data period YYYY-MM:YYYY-MM, e.g. 2026-10:2027-03")
    ap.add_argument("--crops-as-of", help="standing crops inventory date, YYYY-MM-DD")
    ap.add_argument("--recommendations", type=Path, help="text file with agricultural recommendations "
                                                         "(default: generated automatically)")
    a = ap.parse_args()
    settings = {"classification": a.classes, "layout": a.layout, "renderer": a.renderer}
    if a.reporting_month:
        settings["reporting_month"] = a.reporting_month
    if a.period:
        settings["period_start"], settings["period_end"] = a.period.split(":")
    if a.crops_as_of:
        settings["crops_as_of"] = a.crops_as_of
    if a.recommendations:
        settings["recommendations"] = a.recommendations.read_text(encoding="utf-8")
    if a.weights:
        h, d, c = (float(x) for x in a.weights.split(","))
        settings["weights"] = {"hazard": h, "damage": d, "crops": c}
    files = {"drought": (a.drought, a.drought.name), "damage": (a.damage, a.damage.name),
             "crops": (a.crops, a.crops.name)}
    res = pipeline.run(files, settings, progress=lambda step, state, msg: print(f"[{step:12}] {state:7} {msg}"))
    print(json.dumps({k: res[k] for k in ("run_id", "folder", "renderer", "files")}, indent=2))


if __name__ == "__main__":
    main()
