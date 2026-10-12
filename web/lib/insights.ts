/** Explanations and comparisons built from published payloads: why an area has its ENVI class, what changed since
 * the previous issue, and the value of an area over past issues (trend). Pure functions, shared by the dashboard,
 * the area dialog and the printable briefs. */
import type { AreaValue, Layer, Payload, ProductType } from "./types";

// ------------------------------------------------------------ ENVI parts ---

export const ENVI_PARTS = [
  { key: "hazard", label: "Drought forecast", phrase: "drought forecast", color: "#c0392b" },
  { key: "damage", label: "Past El Niño damage", phrase: "past El Niño damage", color: "#8c6d31" },
  { key: "crops", label: "Standing crops", phrase: "standing crops", color: "#2e7d32" },
] as const;

export const DEFAULT_WEIGHTS: Record<string, number> = { hazard: 0.5, damage: 0.25, crops: 0.25 };

export interface EnviPart {
  key: string;
  label: string;
  phrase: string;
  color: string;
  norm: number; // 0–1 normalized indicator
  weight: number;
  value: number; // weight × norm: what the indicator adds to the ENVI
  share: number; // value / ENVI (0–1)
}

/** What each indicator adds to an area's ENVI (weight × normalized value), or null without the indicators. */
export function enviParts(v: AreaValue | undefined, weights?: Record<string, number> | null): EnviPart[] | null {
  if (!v) return null;
  const w = weights && Object.keys(weights).length ? weights : DEFAULT_WEIGHTS;
  const parts = ENVI_PARTS.map((p) => {
    const norm = v[`${p.key}_norm`];
    const weight = Number(w[p.key] ?? 0);
    return typeof norm === "number" ? { ...p, norm, weight, value: weight * norm, share: 0 } : null;
  });
  if (parts.some((p) => p === null)) return null;
  const total = parts.reduce((s, p) => s + p!.value, 0);
  return parts.map((p) => ({ ...p!, share: total > 0 ? p!.value / total : 0 }));
}

/** Class breaks of a layer from its legend ranges (lowest … highest), else the fallback. */
export function layerBreaks(layer: Layer | null | undefined, fallback?: number[]): number[] | undefined {
  const c = layer?.legend.classes ?? [];
  if (c.length && c.every((x) => typeof x.lo === "number" && typeof x.hi === "number")) return [c[0].lo as number, ...c.map((x) => x.hi as number)];
  return fallback;
}

const pct = (x: number) => `${Math.round(x * 100)}%`;

/** One plain-language sentence: why the area has its class, biggest factor first. */
export function enviSentence(name: string, cls: string, envi: number, parts: EnviPart[]): string {
  const total = parts.reduce((s, p) => s + p.value, 0);
  if (!(total > 0)) return `${name} is ${cls}: all three indicators are at their lowest in CAR.`;
  const [a, b, c] = [...parts].sort((x, y) => y.value - x.value);
  const main = a.share >= 0.5 ? `mainly because of its ${a.phrase}` : `because of its ${a.phrase}`;
  return (
    `${name} is ${cls} (ENVI ${envi.toFixed(2)}) ${main} (${pct(a.share)} of the score), ` +
    `then ${b.phrase} (${pct(b.share)}) and ${c.phrase} (${pct(c.share)}).`
  );
}

// ---------------------------------------------------- change since last ---

/** Layer used for a product's trend and, when the same map is not in the previous issue, for the comparison. */
export const SUMMARY_LAYER: Partial<Record<ProductType, { layer: string; field?: string; perArea?: string; unit: string; label: string }>> = {
  envi: { layer: "envi", field: "envi", unit: "", label: "ENVI" },
  // rainfall totals have no map of their own (older issues: a total layer); every day / month map carries them
  rainfall_dekad: { layer: "total", perArea: "total", unit: "mm", label: "10-day rainfall total" },
  rainfall_seasonal: { layer: "season_total", perArea: "season_total", unit: "mm", label: "Season rainfall total" },
};

/** The layer to compare between two issues: the same map if the previous issue has it, else the product's
 * summary layer (10-day total, season total, ENVI). Null when nothing comparable exists. */
export function compareLayerId(cur: Payload, layerId: string | undefined, prev: Payload): string | null {
  const has = (p: Payload, id: string) => p.layers.some((l) => l.id === id);
  if (layerId && has(cur, layerId) && has(prev, layerId)) return layerId;
  const s = SUMMARY_LAYER[cur.type]?.layer;
  return s && has(cur, s) && has(prev, s) ? s : null;
}

export interface Change {
  from: string;
  to: string;
  fromColor: string;
  toColor: string;
  dir: 1 | -1; // 1 = moved to a higher class (more vulnerable / wetter / drier category), -1 = lower
  steps: number;
}

/** Areas whose class moved between two issues (class order = the legend order, lowest first). */
export function classChanges(cur: Layer, prev: Layer): Record<string, Change> {
  const order = cur.legend.classes.map((c) => c.label);
  const out: Record<string, Change> = {};
  for (const [k, v] of Object.entries(cur.values)) {
    const p = prev.values[k];
    if (!p) continue;
    const i = order.indexOf(v.class);
    const j = order.indexOf(p.class);
    if (i < 0 || j < 0 || i === j) continue;
    out[k] = { from: p.class, to: v.class, fromColor: p.color, toColor: v.color, dir: i > j ? 1 : -1, steps: Math.abs(i - j) };
  }
  return out;
}

/** What "up" means for a product, in words, and the marker colours (up, down). */
export function changeMeaning(type: ProductType): { up: string; down: string; upColor: string; downColor: string } {
  if (type === "envi") return { up: "more vulnerable", down: "less vulnerable", upColor: "#b2182b", downColor: "#2166ac" };
  if (type === "drought") return { up: "drier category", down: "wetter category", upColor: "#b2182b", downColor: "#2166ac" };
  return { up: "more rain", down: "less rain", upColor: "#2166ac", downColor: "#a6611a" };
}

// ----------------------------------------------------------------- trend ---

export interface TrendPoint {
  id: string;
  period: string; // period label
  start: string;
  issued: string;
  value: number | null;
  class: string;
  color: string;
}

/** An area's summary value in one payload (ENVI value, 10-day total, season total). */
export function summaryPoint(p: Payload, area: string): Omit<TrendPoint, "id"> | null {
  const s = SUMMARY_LAYER[p.type];
  if (!s) return null;
  const base = { period: p.period.label, start: p.period.start, issued: p.issued };
  const layer = p.layers.find((l) => l.id === s.layer);
  const v = layer?.values[area];
  if (v) {
    const raw = s.field ? v[s.field] : v.value;
    return { ...base, value: typeof raw === "number" ? raw : null, class: v.class, color: v.color };
  }
  const x = s.perArea ? p.layers[0]?.values[area]?.[s.perArea] : undefined;
  return typeof x === "number" ? { ...base, value: x, class: "", color: "#6b8f7a" } : null;
}
