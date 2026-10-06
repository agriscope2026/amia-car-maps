import type { CropsLayer } from "./types";

/** Default crop colours (same as the worker); admins can change them on the Reference data page. */
const DEFAULTS: Record<string, string> = { Rice: "#2e7d32", Corn: "#e0a100" };
const PALETTE = ["#1565c0", "#7b3fa0", "#c62828", "#00838f", "#6d4c41", "#ef6c00", "#ad1457", "#558b2f", "#283593", "#9e9d24"];

export function cropColors(crops: string[], saved?: Record<string, string> | null): Record<string, string> {
  const out: Record<string, string> = {};
  const used = new Set(Object.values(saved ?? {}));
  const free = PALETTE.filter((c) => !used.has(c));
  let i = 0;
  for (const c of crops) out[c] = saved?.[c] || DEFAULTS[c] || free[i++] || PALETTE[i % PALETTE.length];
  return out;
}

export function withColors(c: CropsLayer | null): CropsLayer | null {
  return c ? { ...c, colors: cropColors(c.crops, c.colors) } : c;
}

/** Five shades from very light to the crop colour, for the single-crop choropleth. */
export function cropRamp(hex: string): string[] {
  const n = parseInt(hex.slice(1), 16);
  const rgb = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  return [0.15, 0.35, 0.55, 0.78, 1].map((t) => {
    const c = rgb.map((v) => Math.round(255 + (v - 255) * t));
    return `#${c.map((v) => v.toString(16).padStart(2, "0")).join("")}`;
  });
}
