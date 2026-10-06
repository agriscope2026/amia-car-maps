export type ProductType = "envi" | "rainfall_dekad" | "rainfall_seasonal" | "drought";
export type Status = "draft" | "published" | "archived";

export const PRODUCT_TYPES: { id: ProductType; label: string; short: string }[] = [
  { id: "envi", label: "El Niño Vulnerability Index (ENVI)", short: "ENVI" },
  { id: "rainfall_dekad", label: "10-day rainfall forecast", short: "10-day rainfall" },
  { id: "rainfall_seasonal", label: "Seasonal rainfall forecast", short: "Seasonal rainfall" },
  { id: "drought", label: "Drought forecast", short: "Drought forecast" },
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
}

export interface Period {
  kind: "dekad" | "month" | "season";
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
}

export const FARM_CROPS: { key: "advice_rice" | "advice_corn" | "advice_hvc"; crop: string; label: string; color: string }[] = [
  { key: "advice_rice", crop: "rice", label: "Rice", color: "#2e7d32" },
  { key: "advice_corn", crop: "corn", label: "Corn", color: "#e0a100" },
  { key: "advice_hvc", crop: "hvc", label: "HVC (high-value crops)", color: "#7b3fa0" },
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
