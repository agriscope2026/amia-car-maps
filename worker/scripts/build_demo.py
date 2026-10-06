"""Build the dashboard's local demo data (used when Supabase is not configured).

Writes ../web/public/demo/: catalog.json, one payload per product, crops.json, irrigation.geojson and
the export files of each product (maps PDF/PNG, XLSX, CSV, ZIP). Rainfall and irrigation demo data are
SYNTHETIC (see make_demo_samples.py) and the catalog marks them as such.
Run:  python -m scripts.build_demo [--no-exports]
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agriclimate import api, exports  # noqa: E402
from agriclimate.envi import config  # noqa: E402
from agriclimate.products import envi_product, reference_layers  # noqa: E402

SAMPLE = ROOT / "data" / "sample"
from agriclimate import rainfall_feed  # noqa: E402

_feed = json.loads((ROOT / "tests" / "fixtures" / "rainfall_feed_2026-10-05.json").read_text(encoding="utf-8"))
_FEED_XLSX, _FEED_SETTINGS = rainfall_feed.to_template(_feed)
_FEED_SETTINGS["source"] = ("10-day forecast via Cordillera weather API (snapshot of " + _FEED_SETTINGS["issue_date"]
                            + "); processed by DA-RFO-CAR AMIA")
DEMO = ROOT.parent / "web" / "public" / "demo"

PRODUCTS = [
    ("envi-2026-09", "envi", {k: (p.read_bytes(), p.name) for k, p in config.DEFAULT_FILES.items()},
     {"issue_date": "2026-09-15", "period_start": "2026-10", "period_end": "2027-03"}, False),
    ("drought-2026-09", "drought", {"file": ((config.DEFAULT_FILES["drought"]).read_bytes(), "drought forecast.csv")},
     {"issue_date": "2026-09-15", "period_start": "2026-10"}, False),
    # real 10-day forecast: snapshot of the Cordillera weather API (tests/fixtures), not synthetic
    ("rainfall_dekad-2026-10-05", "rainfall_dekad", {"file": (_FEED_XLSX, "rainfall_feed.xlsx")},
     {**_FEED_SETTINGS, "source": _FEED_SETTINGS["source"]}, False),
    ("rainfall_seasonal-2026-10", "rainfall_seasonal",
     {"file": ((SAMPLE / "DEMO_rainfall_seasonal_2026-10_2027-03.xlsx").read_bytes(), "seasonal.xlsx")},
     {"issue_date": "2026-09-30", "period_start": "2026-10"}, True),
]
MAP_FILES = [("png", "Map – PNG (400 dpi)", False), ("pdf", "Map – PDF", False),
             ("presentation", "Presentation – PNG (5760×3240)", False),
             ("presentation_pdf", "Presentation – PDF", False),
             ("poster", "A4 poster – PNG (450 dpi)", False), ("poster_pdf", "A4 poster – PDF", False),
             ("jpg", "Map preview", True), ("presentation_web", "Presentation preview", True),
             ("poster_web", "Poster preview", True)]


def main(with_exports: bool = True):
    shutil.rmtree(DEMO, ignore_errors=True)
    (DEMO / "products").mkdir(parents=True)
    catalog = []
    envi_payload = None
    for pid, ptype, files, settings, synthetic in PRODUCTS:
        payload = api.build_payload(ptype, files, settings)
        assert payload["ok"], payload["report"]
        payload.pop("report", None)
        if ptype == "envi":
            envi_payload = payload
        downloads = []
        if with_exports:
            tmp = ROOT / "outputs" / "demo" / pid
            shutil.rmtree(tmp, ignore_errors=True)
            m = exports.export_product(payload, tmp, settings, files if ptype == "envi" else None)
            dest = DEMO / "exports" / pid
            dest.mkdir(parents=True)
            # same entries as the web app (lib/server/exports.ts): map images and PDFs, previews for photo mode
            for mp in m["maps"]:
                for key, label, preview in MAP_FILES:
                    f = mp.get(key)
                    if f:
                        shutil.copy2(tmp / f, dest / f)
                        downloads.append({"label": label, "path": f"exports/{pid}/{f}", "alt": mp["alt"],
                                          "group": mp["label"], "layer": mp["layer"], "kind": key, "preview": preview})
            f = m["files"]["zip"]
            shutil.copy2(tmp / f, dest / f)
            downloads.append({"label": "All maps – PNG and PDF (ZIP)", "path": f"exports/{pid}/{f}",
                              "group": "Whole product", "kind": "zip"})
        payload["downloads"] = downloads
        payload["id"] = pid
        payload["synthetic"] = synthetic
        (DEMO / "products" / f"{pid}.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                                                       encoding="utf-8")
        catalog.append({"id": pid, "type": ptype, "title": payload["title"], "issued": payload["issued"],
                        "period": payload["period"], "status": "published", "version": 1, "synthetic": synthetic,
                        "layers": [{"id": lyr["id"], "label": lyr["label"]} for lyr in payload["layers"]]})
        print("built", pid)

    crops = reference_layers.build_crops(*[(p.read_bytes(), p.name) for p in [config.DEFAULT_FILES["crops"]]][0],
                                         {"as_of": "2026-09-15"})
    crops.pop("report")
    (DEMO / "crops.json").write_text(json.dumps(crops, ensure_ascii=False), encoding="utf-8")
    irr = reference_layers.build_irrigation((SAMPLE / "DEMO_irrigation_sources.xlsx").read_bytes(), "irr.xlsx")
    irr["geojson"]["synthetic"] = True
    (DEMO / "irrigation.geojson").write_text(json.dumps(irr["geojson"], ensure_ascii=False), encoding="utf-8")
    (DEMO / "catalog.json").write_text(json.dumps({"products": catalog}, indent=1, ensure_ascii=False),
                                       encoding="utf-8")
    _ = envi_product
    size = sum(p.stat().st_size for p in DEMO.rglob("*") if p.is_file())
    print(f"demo data: {size / 2**20:.1f} MB in {DEMO}")


if __name__ == "__main__":
    main("--no-exports" not in sys.argv)
