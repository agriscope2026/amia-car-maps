export type ProductType = "envi" | "rainfall_dekad" | "rainfall_seasonal" | "drought" | "tc_advisory";
export type Status = "draft" | "published" | "archived";

export const PRODUCT_TYPES: { id: ProductType; label: string; short: string }[] = [
  { id: "envi", label: "El Niño Vulnerability Index (ENVI)", short: "ENVI" },
  { id: "rainfall_dekad", label: "10-day rainfall forecast", short: "10-day rainfall" },
  { id: "rainfall_seasonal", label: "Seasonal rainfall forecast", short: "Seasonal rainfall" },
  { id: "drought", label: "Drought forecast", short: "Drought forecast" },
  { id: "tc_advisory", label: "Special Farm Weather Outlook (tropical cyclone)", short: "Tropical cyclone" },
];

export interface LegendClass {
  label: string;
  color: string;
  lo?: number | null;
  hi?: number | null;
  count?: number;
  desc?: string; // category name, e.g. "Very Light Rain"
}

export interface Legend {
  id: string;
  kind: "graduated" | "categorical";
  title: string;
  unit: string;
  closed?: "left" | "right";
  classes: LegendClass[];
  no_data: { label: string; color: string; count?: number };
}

export interface AreaValue {
  value: number | string | null;
  class: string;
  color: string;
  [extra: string]: number | string | null | undefined;
}

export interface Layer {
  id: string;
  label: string;
  variable: string;
  unit: string;
  legend: Legend;
  values: Record<string, AreaValue>;
  recommendations?: string; // ENVI monthly layers: draft recommendations for that month
}

export interface Period {
  kind: "dekad" | "month" | "season" | "event"; // event: a tropical cyclone bulletin
  start: string;
  end: string;
  label: string;
  months?: string[];
}

export interface Texts {
  title: string;
  subtitle: string;
  notes: string;
  disclaimer: string;
  sources: string;
  recommendations: string;
  issuing_office: string;
  legend_title?: string;
  // farm recommendations shown under the legend of the 10-day, seasonal and drought maps
  advice_rice?: string;
  advice_corn?: string;
  advice_hvc?: string;
  advice_livestock?: string;
}

export const FARM_CROPS: { key: "advice_rice" | "advice_corn" | "advice_hvc" | "advice_livestock"; crop: string; label: string; color: string }[] = [
  { key: "advice_rice", crop: "rice", label: "Rice", color: "#2e7d32" },
  { key: "advice_corn", crop: "corn", label: "Corn", color: "#e0a100" },
  { key: "advice_hvc", crop: "hvc", label: "HVC (high-value crops)", color: "#7b3fa0" },
  { key: "advice_livestock", crop: "livestock", label: "Livestock & poultry", color: "#8d5524" },
];

export interface Download {
  label: string;
  path?: string; // demo/local: relative to /demo or the export route
  url?: string; // absolute URL (Supabase public bucket)
  alt?: string;
  group?: string; // map label (one group per map) or "Whole product"
  layer?: string; // layer id of the map the file belongs to
  kind?: string; // png | pdf | presentation | poster | jpg (preview) | zip …
  preview?: boolean; // used by photo mode, not listed as a download
}

export interface Payload {
  id?: string;
  type: ProductType;
  ok: boolean;
  title: string;
  subtitle: string;
  issued: string;
  period: Period;
  level: string;
  source: string;
  layers: Layer[];
  summary: Record<string, any>;
  method?: Record<string, any>;
  texts: Texts;
  downloads?: Download[];
  synthetic?: boolean;
  report?: any;
  recommendations_draft?: string;
  crop_advice_draft?: Record<string, string>;
  exposure?: Exposure; // ENVI: what the crops indicator was made of
  tc?: TropicalCyclone; // farm weather outlook: the PAGASA tropical cyclone bulletin it was made from
}

/** What the Special Farm Weather Outlook keeps of a PAGASA Tropical Cyclone Bulletin. */
export interface TropicalCyclone {
  bulletin_no: number | null;
  category: string | null; // "Super Typhoon"
  name: string | null; // "ROSAL"
  issued_text: string;
  issued_at: string | null;
  next_bulletin: string;
  headline: string;
  location_text: string;
  lat: number | null;
  lon: number | null;
  movement: string;
  strength: string;
  max_wind_kmh: number | null;
  gust_kmh: number | null;
  forecast: { time: string; where: string }[];
  gusts: { day: string; date: string; areas: string }[];
  rainfall: string[];
  highest_possible: string;
  outlook: string[];
  track_image: string | null;
  bulletin_pdf: string | null;
  page_url: string;
  // from the bulletin PDF: forecast positions with coordinates, and how far the strong winds reach
  track?: { hours: number; time: string; lat: number; lon: number; where: string; wind_kmh: number; category: string; cat: string; outside_par: boolean }[];
  wind_extent_km?: number | null;
  pressure_hpa?: number | null;
  track_geojson?: { type: "FeatureCollection"; features: { type: "Feature"; geometry: any; properties: Record<string, any> }[] };
}

/** ENVI exposure inputs besides rice and corn: HVC (HVCDP Regional Summary) and livestock. */
export interface Exposure {
  hvc: boolean;
  livestock: boolean;
  livestock_share: number;
  crops_as_of?: string | null;
  livestock_as_of?: string | null;
  hvc_summary?: HvcSummary | null;
  livestock_summary?: { as_of: string | null; heads: Record<string, number>; tlu_total: number; tlu_factors: Record<string, number> } | null;
}

export interface HvcSummary {
  as_of: string;
  n_records: number;
  first_planting: string;
  last_planting: string;
  standing_ha: number;
  short_cycle_ha: number;
  perennial_ha: number;
  by_province: Record<string, number>;
  by_group: Record<string, number>;
  top_commodities: { commodity: string; ha: number }[];
  outlook: { month: string; label: string; short_cycle_ha: number; perennial_ha: number; harvest_due_ha: number }[];
  provinces_without_data: string[];
}

export interface CatalogEntry {
  id: string;
  type: ProductType;
  title: string;
  issued: string;
  period: Period;
  status: Status;
  version: number;
  synthetic?: boolean;
  layers: { id: string; label: string }[];
  published_at?: string | null; // when this version went live (the dashboard's "new update" notice)
}

export interface CropsLayer {
  as_of: string;
  crops: string[];
  colors?: Record<string, string>; // colour per crop (admin-chosen)
  unit: "ha";
  values: Record<string, Record<string, number>>;
  totals?: Record<string, number>;
}

export interface Gazetteer {
  bounds: [number, number, number, number];
  gazetteer: { area_key: string; name: string; province: string; psgc: string }[];
}
