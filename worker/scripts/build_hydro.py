"""Build the rivers and water bodies layer for CAR from OpenStreetMap.

  * data/gis/hydro.geojson          – used by the map exports (worker)
  * ../web/public/geo/hydro.geojson – the dashboard's "Rivers & water bodies" overlay

Rivers are OSM ``waterway=river`` lines; water bodies are lakes, reservoirs and wide river areas
(``natural=water`` / ``landuse=reservoir``) of at least MIN_AREA_KM2. Everything is clipped to the CAR
region and simplified. Data © OpenStreetMap contributors (ODbL) – the maps credit it.

Run:  python -m scripts.build_hydro            (downloads from the Overpass API)
      python -m scripts.build_hydro osm.json   (uses a saved Overpass response)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import geopandas as gpd
import httpx
from shapely.geometry import LineString, Polygon, mapping
from shapely.ops import linemerge, polygonize, unary_union

ROOT = Path(__file__).resolve().parents[1]
WEB_GEO = ROOT.parent / "web" / "public" / "geo"
OUT_WORKER = ROOT / "data" / "gis" / "hydro.geojson"
OUT_WEB = WEB_GEO / "hydro.geojson"

BBOX = "16.10,120.35,18.62,121.75"   # CAR plus a margin (S, W, N, E)
QUERY = f"""[out:json][timeout:180];(
  way["waterway"="river"]({BBOX});
  way["natural"="water"]["water"~"^(lake|reservoir|river|oxbow|lagoon)$"]({BBOX});
  relation["natural"="water"]["water"~"^(lake|reservoir|river)$"]({BBOX});
  way["landuse"="reservoir"]({BBOX});
);out geom;"""
MIN_AREA_KM2 = 0.05        # drop ponds; keep lakes, reservoirs and wide river reaches
SIMPLIFY_DEG = 0.00025     # ≈ 27 m – invisible at print and dashboard scales


def fetch() -> dict:
    r = httpx.post("https://overpass-api.de/api/interpreter", data={"data": QUERY}, timeout=300,
                   headers={"User-Agent": "amia-car-maps/1.0 (DA-RFO-CAR map portal)"})
    r.raise_for_status()
    return r.json()


def _coords(geom: list[dict]) -> list[tuple[float, float]]:
    return [(p["lon"], p["lat"]) for p in geom if p]


def features(osm: dict) -> tuple[list[dict], list[dict]]:
    rivers, waters = [], []
    for el in osm["elements"]:
        tags = el.get("tags", {})
        name = tags.get("name:en") or tags.get("name") or ""
        if el["type"] == "way" and tags.get("waterway") == "river":
            pts = _coords(el.get("geometry", []))
            if len(pts) >= 2:
                rivers.append({"name": name, "geometry": LineString(pts)})
        elif el["type"] == "way":
            pts = _coords(el.get("geometry", []))
            if len(pts) >= 4 and pts[0] == pts[-1]:
                waters.append({"name": name, "kind": tags.get("water") or "reservoir", "geometry": Polygon(pts)})
        elif el["type"] == "relation":
            outer = [LineString(_coords(m["geometry"])) for m in el.get("members", [])
                     if m.get("role") in ("outer", "") and len(m.get("geometry", [])) >= 2]
            inner = [LineString(_coords(m["geometry"])) for m in el.get("members", [])
                     if m.get("role") == "inner" and len(m.get("geometry", [])) >= 2]
            polys = list(polygonize(linemerge(outer))) if outer else []
            holes = unary_union(list(polygonize(linemerge(inner)))) if inner else None
            for p in polys:
                waters.append({"name": name, "kind": tags.get("water") or "lake",
                               "geometry": p.difference(holes) if holes is not None else p})
    return rivers, waters


def build(osm: dict) -> dict:
    region = gpd.read_file(WEB_GEO / "region.geojson").to_crs(4326).geometry.union_all().buffer(0.002)
    rivers, waters = features(osm)

    rv = gpd.GeoDataFrame(rivers, crs=4326)
    rv = rv.dissolve(by="name", as_index=False)                     # one feature per named river
    rv["geometry"] = rv.geometry.intersection(region).simplify(SIMPLIFY_DEG)
    rv = rv[~rv.geometry.is_empty]

    wb = gpd.GeoDataFrame(waters, crs=4326)
    wb["geometry"] = wb.geometry.make_valid().intersection(region).simplify(SIMPLIFY_DEG)
    wb = wb[~wb.geometry.is_empty & wb.geometry.geom_type.isin(["Polygon", "MultiPolygon"])]
    wb = wb[wb.geometry.to_crs(32651).area / 1e6 >= MIN_AREA_KM2]   # UTM 51N: area in m²

    def rnd(g):  # 5 decimals ≈ 1 m: plenty, and keeps the file small
        return json.loads(json.dumps(mapping(g)), parse_float=lambda s: round(float(s), 5))

    feats = [{"type": "Feature", "properties": {"kind": "river", "name": r.name}, "geometry": rnd(r.geometry)}
             for r in rv.itertuples()]
    feats += [{"type": "Feature", "properties": {"kind": "water", "water": w.kind, "name": w.name},
               "geometry": rnd(w.geometry)} for w in wb.itertuples()]
    return {"type": "FeatureCollection",
            "attribution": "Rivers and water bodies © OpenStreetMap contributors (ODbL)",
            "features": feats}


def main() -> None:
    osm = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")) if len(sys.argv) > 1 else fetch()
    fc = build(osm)
    text = json.dumps(fc, ensure_ascii=False, separators=(",", ":"))
    for out in (OUT_WORKER, OUT_WEB):
        out.write_text(text, encoding="utf-8")
    n_r = sum(f["properties"]["kind"] == "river" for f in fc["features"])
    print(f"{n_r} rivers, {len(fc['features']) - n_r} water bodies, {len(text) / 1e6:.2f} MB -> {OUT_WORKER}, {OUT_WEB}")


if __name__ == "__main__":
    main()
