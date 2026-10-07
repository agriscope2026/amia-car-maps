"use client";

import { useEffect, useRef, useState } from "react";
import maplibregl, { type GeoJSONSource, type MapGeoJSONFeature } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { CropsLayer, Layer, Payload } from "@/lib/types";
import type { Basemap, CropMode } from "@/lib/share";
import { IRRIGATION_TYPES, irrigationTypes, circleRadius, cropBreaks, cropClass, escapeHtml, fmtNumber, fmtValue } from "@/lib/format";
import { cropRamp } from "@/lib/crops";

const BASEMAPS: Record<Basemap, { tiles: string[]; attribution: string; paint?: Record<string, number> }> = {
  light: {
    tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}"],
    attribution: "Basemap © Esri, HERE, Garmin, © OpenStreetMap contributors",
  },
  satellite: {
    tiles: ["https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"],
    attribution: "Imagery © Esri, Maxar, Earthstar Geographics",
  },
  terrain: {
    tiles: ["a", "b", "c"].map((s) => `https://${s}.tile.opentopomap.org/{z}/{x}/{y}.png`),
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>, SRTM | © <a href="https://opentopomap.org">OpenTopoMap</a> (CC-BY-SA)',
  },
};

/** Basemap tint per map type (light basemap only): background, area outside CAR, basemap opacity / saturation. */
const THEMES: Record<string, { bg: string; mask: string; opacity: number; saturation: number }> = {
  rainfall_dekad: { bg: "#d6e8f5", mask: "#eaf3fa", opacity: 0.62, saturation: -0.8 },
  rainfall_seasonal: { bg: "#d3e3f3", mask: "#e8f1fa", opacity: 0.62, saturation: -0.8 },
  drought: { bg: "#f3e2cc", mask: "#faf1e6", opacity: 0.62, saturation: -0.8 },
  envi: { bg: "#dcebd8", mask: "#eef5ec", opacity: 0.62, saturation: -0.8 },
  default: { bg: "#eef0f2", mask: "#f7f7f5", opacity: 0.95, saturation: -0.3 },
};

const ENVI_FIELDS: [string, string, (v: number) => string][] = [
  ["envi", "ENVI value", (v) => v.toFixed(3)],
  ["rank", "Rank (of 77)", (v) => String(v)],
  ["hazard_raw", "Drought forecast score", (v) => fmtNumber(v, 0)],
  ["damage_raw", "Historical damage (mean, ha/yr)", (v) => `${fmtNumber(v)} ha`],
  ["crops_raw", "Standing crops", (v) => `${fmtNumber(v)} ha`],
  ["hazard_norm", "Drought (normalized)", (v) => v.toFixed(2)],
  ["damage_norm", "Damage (normalized)", (v) => v.toFixed(2)],
  ["crops_norm", "Crops (normalized)", (v) => v.toFixed(2)],
];

export interface MapViewProps {
  bounds: [number, number, number, number];
  payload: Payload | null;
  layer: Layer | null;
  crops: CropsLayer | null;
  showCrops: boolean;
  cropSel?: string[];
  onSelectArea?: (areaKey: string) => void; // click on a municipality → details dialog
  cropMode: CropMode;
  irrigation: any | null;
  showIrrigation: boolean;
  irrTypes: string[];
  showHydro?: boolean; // rivers & water bodies (OpenStreetMap)
  basemap: Basemap;
  initialView?: { lng: number; lat: number; zoom: number };
  onViewChange?: (v: { lng: number; lat: number; zoom: number }) => void;
}

function hatchImage(): ImageData {
  const s = 8;
  const data = new Uint8ClampedArray(s * s * 4);
  for (let y = 0; y < s; y++)
    for (let x = 0; x < s; x++) {
      const on = (x + y) % s === 0 || (x + y) % s === s - 1;
      const i = (y * s + x) * 4;
      data.set(on ? [110, 110, 110, 230] : [217, 217, 217, 255], i);
    }
  return new ImageData(data, s, s);
}

export default function MapView(props: MapViewProps) {
  const el = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const propsRef = useRef(props);
  const labelPts = useRef<any>(null);
  const [ready, setReady] = useState(false);
  propsRef.current = props;

  // ------------------------------------------------------------ create ---
  useEffect(() => {
    if (!el.current) return;
    const [x0, y0, x1, y1] = props.bounds;
    const pad = 3; // degrees around CAR you can pan to when zoomed out (northern Luzon)
    const bm = BASEMAPS[props.basemap];
    const map = new maplibregl.Map({
      container: el.current,
      style: {
        version: 8,
        glyphs: "/glyphs/{fontstack}/{range}.pbf",
        sources: { basemap: { type: "raster", tiles: bm.tiles, tileSize: 256, attribution: bm.attribution, maxzoom: 18 } },
        layers: [
          { id: "bg", type: "background", paint: { "background-color": "#eef0f2" } },
          { id: "basemap", type: "raster", source: "basemap", paint: { "raster-saturation": -0.3, "raster-opacity": 0.95 } },
        ],
      },
      bounds: [x0, y0, x1, y1],
      fitBoundsOptions: { padding: 24 },
      maxBounds: [x0 - pad * 2, y0 - pad, x1 + pad * 2, y1 + pad],
      minZoom: 4.5,
      maxZoom: 15,
      attributionControl: { compact: true },
      dragRotate: false,
      pitchWithRotate: false,
      // ?print=1 keeps the WebGL buffer so the map can be printed / captured (slightly slower)
      canvasContextAttributes: { preserveDrawingBuffer: new URLSearchParams(window.location.search).has("print") },
    });
    map.touchZoomRotate.disableRotation();
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-right");
    // fullscreen the whole dashboard, not only the map canvas, so dialogs and photo mode stay visible
    const app = el.current.closest(".app") as HTMLElement | null;
    map.addControl(new maplibregl.FullscreenControl(app ? { container: app } : {}), "top-right");
    if (props.initialView) map.jumpTo({ center: [props.initialView.lng, props.initialView.lat], zoom: props.initialView.zoom });
    mapRef.current = map;

    map.on("load", async () => {
      map.addImage("hatch", hatchImage(), { pixelRatio: 1 });
      map.addSource("muni", { type: "geojson", data: "/geo/municipalities.geojson", promoteId: "area_key" });
      map.addSource("prov", { type: "geojson", data: "/geo/provinces.geojson" });
      map.addSource("region", { type: "geojson", data: "/geo/region.geojson" });
      map.addSource("mask", { type: "geojson", data: "/geo/mask.geojson" });
      map.addSource("labels", { type: "geojson", data: "/geo/labels.geojson" });
      map.addSource("crop-pts", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      map.addSource("irr", { type: "geojson", data: { type: "FeatureCollection", features: [] } });
      // rivers & water bodies: filled from /geo/hydro.geojson the first time the overlay is switched on
      map.addSource("hydro", { type: "geojson", data: { type: "FeatureCollection", features: [] },
        attribution: "Rivers & water bodies © OpenStreetMap contributors" });

      map.addLayer({ id: "muni-fill", type: "fill", source: "muni",
        paint: { "fill-color": ["coalesce", ["feature-state", "color"], "#d9d9d9"], "fill-opacity": 0.88 } });
      map.addLayer({ id: "muni-nodata", type: "fill", source: "muni",
        paint: { "fill-pattern": "hatch", "fill-opacity": ["case", ["boolean", ["feature-state", "nodata"], false], 0.9, 0] } });
      map.addLayer({ id: "crop-fill", type: "fill", source: "muni", layout: { visibility: "none" },
        paint: { "fill-color": ["coalesce", ["feature-state", "cropColor"], "#f2f2f2"], "fill-opacity": 0.9 } });
      map.addLayer({ id: "mask", type: "fill", source: "mask", paint: { "fill-color": "#f7f7f5", "fill-opacity": 0.72 } });
      map.addLayer({ id: "muni-line", type: "line", source: "muni",
        paint: { "line-color": "#6f6f6f", "line-width": ["interpolate", ["linear"], ["zoom"], 7, 0.3, 11, 1] } });
      map.addLayer({ id: "hydro-water", type: "fill", source: "hydro", layout: { visibility: "none" },
        filter: ["==", ["get", "kind"], "water"],
        paint: { "fill-color": "#3a8fd8", "fill-opacity": 0.85, "fill-outline-color": "#1c5fa8" } });
      map.addLayer({ id: "hydro-river", type: "line", source: "hydro", layout: { visibility: "none", "line-join": "round", "line-cap": "round" },
        filter: ["==", ["get", "kind"], "river"],
        paint: { "line-color": "#1f78d1", "line-width": ["interpolate", ["linear"], ["zoom"], 7, 0.8, 10, 1.8, 13, 3.2] } });
      map.addLayer({ id: "muni-hover", type: "line", source: "muni",
        paint: { "line-color": "#111", "line-width": ["case", ["boolean", ["feature-state", "hover"], false], 2.6, 0] } });
      map.addLayer({ id: "prov-line", type: "line", source: "prov",
        paint: { "line-color": "#141414", "line-width": ["interpolate", ["linear"], ["zoom"], 7, 1.3, 11, 2.4] } });
      map.addLayer({ id: "region-halo", type: "line", source: "region", paint: { "line-color": "#ffffff", "line-width": 6, "line-opacity": 0.8 } });
      map.addLayer({ id: "region-line", type: "line", source: "region", paint: { "line-color": "#0b532f", "line-width": 3.2 } });
      map.addLayer({ id: "crop-circles", type: "circle", source: "crop-pts", layout: { visibility: "none" },
        paint: { "circle-radius": ["get", "r"], "circle-color": ["get", "color"], "circle-opacity": 0.62,
          "circle-stroke-color": "#1f1f1f", "circle-stroke-width": 0.8 } });
      map.addLayer({ id: "irr-points", type: "circle", source: "irr", layout: { visibility: "none" },
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["zoom"], 7, 5, 12, 9],
          "circle-color": "#969696", // set per type when the data arrives
          "circle-stroke-color": "#ffffff", "circle-stroke-width": 1.6,
        } });
      map.addLayer({ id: "irr-labels", type: "symbol", source: "irr", minzoom: 10, layout: { visibility: "none",
          "text-field": ["get", "name"], "text-font": ["Montserrat Medium"], "text-size": 11, "text-offset": [0, 1.1],
          "text-anchor": "top", "text-max-width": 10 },
        paint: { "text-color": "#08306b", "text-halo-color": "#fff", "text-halo-width": 1.4 } });
      const hydroText = { "text-color": "#0d4f91", "text-halo-color": "rgba(255,255,255,0.95)", "text-halo-width": 1.8 };
      map.addLayer({ id: "hydro-river-labels", type: "symbol", source: "hydro", minzoom: 9.5, filter: ["==", ["get", "kind"], "river"],
        layout: { visibility: "none", "symbol-placement": "line", "text-field": ["get", "name"], "text-font": ["Montserrat SemiBold"],
          "text-size": 12, "symbol-spacing": 280,
          "text-max-angle": 60, "text-letter-spacing": 0.04 }, // winding mountain rivers: allow sharper bends than usual
        paint: hydroText });
      map.addLayer({ id: "hydro-water-labels", type: "symbol", source: "hydro", minzoom: 10, filter: ["==", ["get", "kind"], "water"],
        layout: { visibility: "none", "text-field": ["get", "name"], "text-font": ["Montserrat Medium"], "text-size": 11, "text-max-width": 8 },
        paint: hydroText });
      map.addLayer({ id: "labels-muni", type: "symbol", source: "labels", minzoom: 8.2,
        filter: ["==", ["get", "kind"], "municipality"],
        layout: { "text-field": ["get", "name"], "text-font": ["Montserrat SemiBold"],
          "text-size": ["interpolate", ["linear"], ["zoom"], 8.2, 10, 12, 14], "text-max-width": 7,
          "text-padding": 2, "symbol-sort-key": ["-", 0, ["get", "area"]] },
        paint: { "text-color": "#1d1d1d", "text-halo-color": "rgba(255,255,255,0.92)", "text-halo-width": 1.5 } });
      map.addLayer({ id: "labels-prov", type: "symbol", source: "labels", maxzoom: 9.4,
        filter: ["==", ["get", "kind"], "province"],
        layout: { "text-field": ["get", "name"], "text-font": ["Montserrat Bold"], "text-transform": "uppercase",
          "text-size": ["interpolate", ["linear"], ["zoom"], 6, 11, 9, 16], "text-letter-spacing": 0.08, "text-max-width": 8 },
        paint: { "text-color": "#202020", "text-halo-color": "rgba(255,255,255,0.95)", "text-halo-width": 2 } });

      labelPts.current = await (await fetch("/geo/labels.geojson")).json();
      setReady(true);
    });

    // hover + popups
    let hovered: string | number | undefined;
    const hoverPopup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, className: "hover-popup", offset: 12 });
    map.on("mousemove", ["muni-fill", "crop-fill"], (e) => {
      const f = e.features?.[0];
      if (!f) return;
      if (hovered !== undefined) map.setFeatureState({ source: "muni", id: hovered }, { hover: false });
      hovered = f.id;
      map.setFeatureState({ source: "muni", id: hovered! }, { hover: true });
      map.getCanvas().style.cursor = "pointer";
      hoverPopup.setLngLat(e.lngLat).setHTML(hoverHtml(f, propsRef.current)).addTo(map);
    });
    map.on("mouseleave", ["muni-fill", "crop-fill"], () => {
      if (hovered !== undefined) map.setFeatureState({ source: "muni", id: hovered }, { hover: false });
      hovered = undefined;
      map.getCanvas().style.cursor = "";
      hoverPopup.remove();
    });
    map.on("click", (e) => {
      const irr = map.queryRenderedFeatures(e.point, { layers: ["irr-points"] }).filter(() => propsRef.current.showIrrigation);
      hoverPopup.remove();
      if (irr.length) {
        new maplibregl.Popup({ maxWidth: "300px" }).setLngLat(e.lngLat).setHTML(irrigationHtml(irr[0].properties)).addTo(map);
        return;
      }
      const f = map.queryRenderedFeatures(e.point, { layers: ["muni-fill", "crop-fill"] })[0];
      if (!f) return;
      const onSelect = propsRef.current.onSelectArea;
      if (onSelect) onSelect(String(f.id ?? f.properties?.area_key));
      else new maplibregl.Popup({ maxWidth: "320px" }).setLngLat(e.lngLat).setHTML(areaHtml(f, propsRef.current)).addTo(map);
    });
    map.on("moveend", () => {
      const c = map.getCenter();
      propsRef.current.onViewChange?.({ lng: c.lng, lat: c.lat, zoom: map.getZoom() });
    });

    return () => map.remove();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ------------------------------------------------- product colouring ---
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const values = props.layer?.values ?? {};
    const features = map.querySourceFeatures("muni");
    const keys = new Set<string>(Object.keys(values));
    for (const f of features) keys.add(String(f.id ?? f.properties?.area_key));
    for (const k of keys) {
      const v = values[k];
      map.setFeatureState({ source: "muni", id: k }, { color: v?.color ?? "#d9d9d9", nodata: !v || v.class === "No data" });
    }
  }, [ready, props.layer]);

  // -------------------------------------------------------------- crops ---
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const sel = (props.cropSel ?? []).filter((c) => props.crops?.crops.includes(c));
    const on = props.showCrops && !!props.crops && sel.length > 0;
    const vals = props.crops?.values ?? {};
    const colors = props.crops?.colors ?? {};
    if (on && labelPts.current) {
      // circles: one per municipality and selected crop, area ∝ ha (same scale for every crop)
      const max = Math.max(0, ...Object.values(vals).flatMap((c) => sel.map((k) => c[k] ?? 0)));
      const feats = labelPts.current.features
        .filter((f: any) => f.properties.kind === "municipality")
        .flatMap((f: any) =>
          sel.map((crop) => {
            const ha = vals[f.properties.area_key]?.[crop] ?? 0;
            return { ...f, properties: { ...f.properties, crop, ha, r: circleRadius(ha, max), color: colors[crop] ?? "#2e7d32" } };
          }),
        )
        .filter((f: any) => f.properties.ha > 0)
        .sort((a: any, b: any) => b.properties.ha - a.properties.ha); // big circles first, small ones on top
      (map.getSource("crop-pts") as GeoJSONSource).setData({ type: "FeatureCollection", features: feats });
      // choropleth: the first selected crop, shaded in its own colour
      const crop = sel[0];
      const all = Object.values(vals).map((c) => c[crop] ?? 0);
      const br = cropBreaks(all);
      const ramp = cropRamp(colors[crop] ?? "#2e7d32");
      for (const [k, c] of Object.entries(vals)) {
        const i = cropClass(c[crop] ?? 0, br);
        map.setFeatureState({ source: "muni", id: k }, { cropColor: i < 0 ? "#f5f5f5" : ramp[i] });
      }
    }
    const circles = on && props.cropMode === "circles";
    const choro = on && props.cropMode === "choropleth";
    map.setLayoutProperty("crop-circles", "visibility", circles ? "visible" : "none");
    map.setLayoutProperty("crop-fill", "visibility", choro ? "visible" : "none");
    map.setLayoutProperty("muni-fill", "visibility", choro ? "none" : "visible");
    map.setLayoutProperty("muni-nodata", "visibility", choro ? "none" : "visible");
  }, [ready, props.showCrops, props.crops, props.cropSel, props.cropMode]);

  // ------------------------------------------------- rivers & water bodies ---
  const hydroLoaded = useRef(false);
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    if (props.showHydro && !hydroLoaded.current) {
      hydroLoaded.current = true;
      (map.getSource("hydro") as GeoJSONSource).setData("/geo/hydro.geojson");
    }
    const vis = props.showHydro ? "visible" : "none";
    for (const id of ["hydro-water", "hydro-river", "hydro-river-labels", "hydro-water-labels"]) map.setLayoutProperty(id, "visibility", vis);
  }, [ready, props.showHydro]);

  // --------------------------------------------------------- irrigation ---
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    if (props.irrigation) {
      (map.getSource("irr") as GeoJSONSource).setData(props.irrigation);
      // colours per type from the data, so new types uploaded by an admin get their own colour
      const pairs = irrigationTypes(props.irrigation).flatMap((t) => [t.code, t.color]);
      map.setPaintProperty("irr-points", "circle-color", pairs.length ? (["match", ["get", "type"], ...pairs, "#969696"] as any) : "#969696");
    }
    const vis = props.showIrrigation ? "visible" : "none";
    map.setLayoutProperty("irr-points", "visibility", vis);
    map.setLayoutProperty("irr-labels", "visibility", vis);
    const filter: any = ["in", ["get", "type"], ["literal", props.irrTypes]];
    map.setFilter("irr-points", filter);
    map.setFilter("irr-labels", filter);
  }, [ready, props.irrigation, props.showIrrigation, props.irrTypes]);

  // ----------------------------------------------------------- basemap ---
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const src = map.getSource("basemap") as maplibregl.RasterTileSource;
    src.setTiles(BASEMAPS[props.basemap].tiles);
    // light basemap: tinted to match the selected map (blue for rainfall, sand for drought, green for ENVI)
    const th = props.basemap === "light" ? THEMES[props.payload?.type ?? "default"] ?? THEMES.default : null;
    map.setPaintProperty("bg", "background-color", th?.bg ?? "#eef0f2");
    map.setPaintProperty("basemap", "raster-opacity", th?.opacity ?? 1);
    map.setPaintProperty("basemap", "raster-saturation", th?.saturation ?? 0);
    map.setPaintProperty("mask", "fill-color", th?.mask ?? "#f7f7f5");
    map.setPaintProperty("mask", "fill-opacity", props.basemap === "light" ? 0.66 : 0.6);
  }, [ready, props.basemap, props.payload?.type]);

  return (
    <div
      ref={el}
      className="map"
      role="application"
      aria-label="Interactive map of the Cordillera Administrative Region. Use the arrow keys to pan and plus/minus to zoom."
    />
  );
}

// ------------------------------------------------------------- popups ---

function areaHeader(f: MapGeoJSONFeature) {
  const p = f.properties as any;
  return `<div class="pp-title">${escapeHtml(p.name)}</div><div class="pp-sub">${escapeHtml(p.province)}</div>`;
}

function hoverHtml(f: MapGeoJSONFeature, props: MapViewProps) {
  const key = String(f.id);
  const layer = props.layer;
  let line = "";
  if (layer) {
    const v = layer.values[key];
    const val = fmtValue(v, layer);
    line = `<div class="pp-value">${escapeHtml(val)}${v && v.class !== val && v.class !== "No data" ? ` · ${escapeHtml(v.class)}` : ""}</div>`;
  }
  if (props.showCrops && props.crops && props.cropSel?.length) {
    for (const c of props.cropSel) {
      const ha = props.crops.values[key]?.[c];
      line += `<div class="pp-sub">${escapeHtml(c)}: ${ha !== undefined ? fmtNumber(ha) + " ha" : "no data"}</div>`;
    }
  }
  if (props.onSelectArea) line += `<div class="pp-hint">Click for details & recommendations</div>`;
  return areaHeader(f) + line;
}

function areaHtml(f: MapGeoJSONFeature, props: MapViewProps) {
  const key = String(f.id);
  const { layer, payload } = props;
  let html = areaHeader(f);
  if (layer && payload) {
    const v = layer.values[key];
    html += `<div class="pp-layer">${escapeHtml(layer.label)}</div>`;
    html += `<div class="pp-value">${escapeHtml(fmtValue(v, layer))}</div>`;
    if (v && v.class !== "No data" && typeof v.value === "number")
      html += `<div class="pp-class"><span class="sw" style="background:${escapeHtml(v.color)}"></span>${escapeHtml(v.class)}${layer.unit === "mm" ? " mm" : ""}</div>`;
    if (v && typeof v.value === "string" && v.class !== "No data")
      html += `<div class="pp-class"><span class="sw" style="background:${escapeHtml(v.color)}"></span>${escapeHtml(v.class)}</div>`;
    if (payload.type === "envi" && v) {
      html += `<table class="pp-table">${ENVI_FIELDS.filter(([k]) => typeof v[k] === "number")
        .map(([k, label, fmt]) => `<tr><th>${label}</th><td>${escapeHtml(fmt(v[k] as number))}</td></tr>`)
        .join("")}</table>`;
    }
    if (payload.type === "rainfall_seasonal" && v) {
      const extra = [
        typeof v.season_total === "number" ? `<tr><th>Season total</th><td>${fmtNumber(v.season_total)} mm</td></tr>` : "",
        typeof v.pct_normal === "number" ? `<tr><th>% of normal</th><td>${fmtNumber(v.pct_normal, 0)}%</td></tr>` : "",
      ].join("");
      if (extra) html += `<table class="pp-table">${extra}</table>`;
    }
  }
  const crops = props.crops?.values[key];
  if (crops && Object.keys(crops).length) {
    html += `<div class="pp-layer">Standing crops (as of ${escapeHtml(props.crops!.as_of)})</div><table class="pp-table">${Object.entries(crops)
      .map(([c, ha]) => `<tr><th>${escapeHtml(c)}</th><td>${fmtNumber(ha)} ha</td></tr>`)
      .join("")}</table>`;
  }
  if (payload) html += `<div class="pp-links"><a href="#notes">Notes</a> · <a href="#recommendations">Recommendations</a></div>`;
  return html;
}

function irrigationHtml(p: any) {
  const label = p.type_label || IRRIGATION_TYPES[p.type]?.label || String(p.type ?? "Other").replace(/_/g, " ");
  const rows: [string, any][] = [
    ["Type", label],
    ["River / source", p.river],
    ["Municipality", [p.municipality, p.province].filter(Boolean).join(", ")],
    ["Service area", p.service_area_ha != null && p.service_area_ha !== "" ? `${fmtNumber(Number(p.service_area_ha))} ha` : null],
    ["Status", p.status],
    ["Data source", p.source],
  ];
  return `<div class="pp-title">${escapeHtml(p.name)}</div><table class="pp-table">${rows
    .filter(([, v]) => v)
    .map(([k, v]) => `<tr><th>${k}</th><td>${escapeHtml(v)}</td></tr>`)
    .join("")}</table>`;
}
