"""Build reference data from the CAR boundary shapefiles.

  * data/reference/gazetteer.csv  – 77 municipalities with canonical key and PSGC code
  * ../web/public/geo/*.geojson   – simplified boundaries, region outline, outside-CAR mask, label points

PSGC codes come from the PSGC column of the standing-crops sample (DA-RFO-CAR), matched with the
same name-matching rules as every upload. Run:  python -m scripts.build_reference
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pandas as pd
from shapely.geometry import box, mapping
from shapely.ops import polylabel, unary_union

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agriclimate import reference  # noqa: E402
from agriclimate.envi import config  # noqa: E402
from agriclimate.envi.io_loader import _psgc_province, load_crops  # noqa: E402

WEB_GEO = ROOT.parent / "web" / "public" / "geo"


def psgc_codes() -> dict[str, str]:
    p = config.DEFAULT_FILES["crops"]
    res = load_crops(p, p.name, reference.gazetteer())
    raw = pd.read_excel(p, header=0)
    code_col, name_col = raw.columns[0], raw.columns[1]
    out = {}
    for r in res.report["rows"]:
        if r.get("role") != "data" or not r.get("area_key"):
            continue
        code = str(raw.iloc[r["row"] - 2][code_col])
        out[r["area_key"]] = re.sub(r"\D", "", code)
        assert _psgc_province(code) == r["area_key"].split("|")[0], (code, r)
    assert len(out) == reference.N_MUNICIPALITIES, len(out)
    _ = name_col
    return out


def _round_geom(geom, nd=5):
    gj = mapping(geom)

    def rnd(c):
        if isinstance(c, (list, tuple)) and c and isinstance(c[0], (int, float)):
            return [round(c[0], nd), round(c[1], nd)]
        return [rnd(x) for x in c]
    return {"type": gj["type"], "coordinates": rnd(gj["coordinates"])}


def _fc(features):
    return {"type": "FeatureCollection", "features": features}


def write(name: str, obj) -> int:
    WEB_GEO.mkdir(parents=True, exist_ok=True)
    s = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    (WEB_GEO / name).write_text(s, encoding="utf-8")
    return len(s.encode("utf-8"))


def main(tolerance: float = 0.0012):
    codes = psgc_codes()
    path = reference.write_gazetteer_csv(codes)
    print(f"gazetteer: {path} ({len(codes)} municipalities)")

    muni, prov = reference.boundaries()
    g = reference.gazetteer_table().set_index("area_key")
    sizes = {}
    feats, labels = [], []
    for _, r in muni.iterrows():
        k = r.area_key
        geom = r.geometry.simplify(tolerance, preserve_topology=True)
        props = {"area_key": k, "name": g.at[k, "label"], "short_name": g.at[k, "short_name"],
                 "province": g.at[k, "province_label"], "psgc": g.at[k, "psgc"], "is_city": bool(g.at[k, "is_city"])}
        feats.append({"type": "Feature", "id": int(r.OBJECTID), "properties": props, "geometry": _round_geom(geom)})
        poly = max(getattr(r.geometry, "geoms", [r.geometry]), key=lambda x: x.area)
        pt = polylabel(poly, tolerance=poly.length / 500)
        labels.append({"type": "Feature", "properties": {**props, "kind": "municipality",
                                                         "area": round(r.geometry.area * 1e4, 2)},
                       "geometry": _round_geom(pt)})
    sizes["municipalities.geojson"] = write("municipalities.geojson", _fc(feats))

    pfeats = []
    for _, r in prov.iterrows():
        geom = r.geometry.simplify(tolerance, preserve_topology=True)
        pfeats.append({"type": "Feature", "properties": {"area_key": r.area_key, "name": r.Pro_Name},
                       "geometry": _round_geom(geom)})
        pt = r.geometry.representative_point()
        labels.append({"type": "Feature", "properties": {"name": r.Pro_Name, "kind": "province",
                                                         "name_wrapped": r.Pro_Name.replace(" ", "\n")},
                       "geometry": _round_geom(pt)})
    sizes["provinces.geojson"] = write("provinces.geojson", _fc(pfeats))

    region = unary_union(list(prov.geometry)).buffer(0)
    region_s = region.simplify(tolerance, preserve_topology=True)
    sizes["region.geojson"] = write("region.geojson", _fc([{"type": "Feature", "properties": {"name": "CAR"},
                                                            "geometry": _round_geom(region_s)}]))
    mask = box(110, 2, 135, 25).difference(region_s)
    sizes["mask.geojson"] = write("mask.geojson", _fc([{"type": "Feature", "properties": {},
                                                        "geometry": _round_geom(mask)}]))
    sizes["labels.geojson"] = write("labels.geojson", _fc(labels))
    minx, miny, maxx, maxy = region.bounds
    meta = {"bounds": [round(minx, 4), round(miny, 4), round(maxx, 4), round(maxy, 4)],
            "gazetteer": [{"area_key": k, "name": g.at[k, "label"], "province": g.at[k, "province_label"],
                           "psgc": g.at[k, "psgc"]} for k in g.index]}
    sizes["car.json"] = write("car.json", meta)
    total = sum(sizes.values())
    for k, v in sizes.items():
        print(f"  {k:28s} {v / 1024:8.1f} KB")
    print(f"  total boundaries {total / 1024:.1f} KB (budget 1024 KB)")
    assert total < 1024 * 1024, "boundary assets exceed 1 MB"


if __name__ == "__main__":
    main()
