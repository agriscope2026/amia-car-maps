import type { AreaValue, CatalogEntry, Layer, ProductType } from "./types";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

export function fmtDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m) return iso;
  return d ? `${MONTHS[m - 1]} ${d}, ${y}` : `${MONTHS[m - 1]} ${y}`;
}

export function fmtNumber(v: number, digits = 1): string {
  return v.toLocaleString("en-PH", { maximumFractionDigits: digits });
}

/** Value with its unit, e.g. "42.5 mm", "1,336 ha", "Very High". */
export function fmtValue(v: AreaValue | undefined, layer: Layer): string {
  if (!v || v.value === null || v.value === undefined || v.value === "") return "No data";
  if (typeof v.value === "string") return v.value;
  if (layer.unit === "%") return `${fmtNumber(v.value, 0)}% of normal`;
  if (layer.unit === "mm" || layer.unit === "ha") return `${fmtNumber(v.value)} ${layer.unit}`;
  return fmtNumber(v.value, 3);
}

export function legendLabel(label: string, unit: string, kind: string): string {
  return kind === "graduated" && unit === "mm" ? `${label} mm` : label;
}

/** Latest issue first; ties broken by period start. */
export function sortIssues(list: CatalogEntry[]): CatalogEntry[] {
  return [...list].sort((a, b) => b.period.start.localeCompare(a.period.start) || b.issued.localeCompare(a.issued) || b.version - a.version);
}

export function latestOf(list: CatalogEntry[], type: ProductType): CatalogEntry | undefined {
  return sortIssues(list.filter((p) => p.type === type))[0];
}

export function defaultLayer(type: ProductType, layers: { id: string }[]): string | undefined {
  if (type === "rainfall_seasonal") return layers.find((l) => l.id === "season_total")?.id ?? layers[0]?.id;
  return layers[0]?.id;
}

export function escapeHtml(s: unknown): string {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);
}

/** Proportional-circle radius (px) for a crop area, scaled so the largest area is `maxR`. */
export function circleRadius(ha: number, maxHa: number, maxR = 26): number {
  if (!(ha > 0) || !(maxHa > 0)) return 0;
  return Math.max(2, Math.sqrt(ha / maxHa) * maxR);
}

/** Sequential green ramp for the crop-area choropleth (5 quantile-ish classes). */
export const CROP_COLORS = ["#edf8e9", "#bae4b3", "#74c476", "#31a354", "#006d2c"];
export function cropBreaks(values: number[]): number[] {
  const v = values.filter((x) => x > 0).sort((a, b) => a - b);
  if (!v.length) return [0, 0, 0, 0];
  const q = (p: number) => v[Math.min(v.length - 1, Math.floor(p * v.length))];
  return [q(0.2), q(0.4), q(0.6), q(0.8)];
}
export function cropClass(ha: number, breaks: number[]): number {
  if (!(ha > 0)) return -1;
  let i = 0;
  while (i < breaks.length && ha >= breaks[i]) i++;
  return i;
}

export const IRRIGATION_TYPES: Record<string, { label: string; color: string }> = {
  NIS: { label: "National irrigation system (NIA)", color: "#08519c" },
  CIS: { label: "Communal irrigation system (NIA)", color: "#3182bd" },
  SWIP: { label: "Small water impounding project", color: "#6a51a3" },
  SSIP: { label: "Small-scale irrigation project", color: "#9e9ac8" },
  DAM: { label: "Dam", color: "#252525" },
  RIVER: { label: "River (water source)", color: "#0aa2c0" },
  OTHER: { label: "Other", color: "#969696" },
};
/** colours for irrigation types that are not in IRRIGATION_TYPES (new types in an upload), in order */
const EXTRA_IRR_COLORS = ["#e6550d", "#31a354", "#d6616b", "#8c6d31", "#e377c2", "#17becf", "#bcbd22", "#7f7f7f"];

export interface IrrigationType {
  code: string;
  label: string;
  color: string;
  count: number;
}

/** The irrigation types present in the data: known types first (fixed colours), then new ones (alphabetical). */
export function irrigationTypes(data: any): IrrigationType[] {
  const seen = new Map<string, { label?: string; count: number }>();
  for (const f of data?.features ?? []) {
    const code = String(f.properties?.type || "OTHER");
    const t = seen.get(code) ?? { count: 0 };
    t.count += 1;
    t.label ??= f.properties?.type_label || undefined;
    seen.set(code, t);
  }
  const known = Object.keys(IRRIGATION_TYPES).filter((k) => seen.has(k));
  const extra = [...seen.keys()].filter((k) => !IRRIGATION_TYPES[k]).sort();
  return [
    ...known.map((code) => ({ code, label: seen.get(code)!.label ?? IRRIGATION_TYPES[code].label, color: IRRIGATION_TYPES[code].color, count: seen.get(code)!.count })),
    ...extra.map((code, i) => ({
      code,
      label: seen.get(code)!.label ?? code.replace(/_/g, " ").toLowerCase().replace(/^./, (c) => c.toUpperCase()),
      color: EXTRA_IRR_COLORS[i % EXTRA_IRR_COLORS.length],
      count: seen.get(code)!.count,
    })),
  ];
}
