/** Dashboard state ⇄ URL query string (share links encode product, period, overlays and view). */

export type CropMode = "circles" | "choropleth";
export type Basemap = "light" | "satellite" | "terrain";

export interface ViewState {
  type?: string; // map type (product type)
  product?: string; // product id (issue / period)
  layer?: string; // layer id (month, season total …)
  crops: boolean;
  cropSel?: string[]; // crops shown (circles: several; choropleth: the first one)
  cropMode: CropMode;
  irrigation: boolean;
  irrTypes?: string[];
  hydro: boolean; // rivers & water bodies
  basemap: Basemap;
  view?: { lng: number; lat: number; zoom: number };
  photo?: boolean; // photo mode (finished map images + recommendations)
}

export const DEFAULT_STATE: ViewState = { crops: false, cropMode: "circles", irrigation: false, hydro: false, basemap: "satellite" };

const num = (s: string | null) => (s !== null && s !== "" && Number.isFinite(Number(s)) ? Number(s) : undefined);

export function parseState(q: URLSearchParams): ViewState {
  const s: ViewState = { ...DEFAULT_STATE };
  const str = (k: string) => q.get(k) || undefined;
  s.type = str("type");
  s.product = str("p");
  s.layer = str("l");
  const ov = (q.get("o") ?? "").split(",");
  s.crops = ov.includes("crops");
  s.irrigation = ov.includes("irr");
  s.hydro = ov.includes("water");
  const cs = q.get("crop");
  s.cropSel = cs ? cs.split(",").filter(Boolean) : undefined;
  s.cropMode = q.get("cm") === "choropleth" ? "choropleth" : "circles";
  const t = q.get("it");
  s.irrTypes = t ? t.split(",").filter(Boolean) : undefined;
  const b = q.get("b");
  s.basemap = b === "light" || b === "terrain" ? b : "satellite";
  if (q.get("photo") === "1") s.photo = true;
  const v = (q.get("v") ?? "").split(",").map((x) => num(x));
  if (v.length === 3 && v.every((x) => x !== undefined)) {
    const [lng, lat, zoom] = v as number[];
    if (Math.abs(lng) <= 180 && Math.abs(lat) <= 90 && zoom >= 0 && zoom <= 22) s.view = { lng, lat, zoom };
  }
  return s;
}

export function serializeState(s: ViewState): string {
  const q = new URLSearchParams();
  if (s.type) q.set("type", s.type);
  if (s.product) q.set("p", s.product);
  if (s.layer) q.set("l", s.layer);
  const ov = [s.crops && "crops", s.irrigation && "irr", s.hydro && "water"].filter(Boolean) as string[];
  if (ov.length) q.set("o", ov.join(","));
  if (s.crops && s.cropSel?.length) q.set("crop", s.cropSel.join(","));
  if (s.crops && s.cropMode !== "circles") q.set("cm", s.cropMode);
  if (s.irrigation && s.irrTypes?.length) q.set("it", s.irrTypes.join(","));
  if (s.basemap !== "satellite") q.set("b", s.basemap);
  if (s.photo) q.set("photo", "1");
  if (s.view) q.set("v", [s.view.lng.toFixed(4), s.view.lat.toFixed(4), s.view.zoom.toFixed(2)].join(","));
  return q.toString();
}
