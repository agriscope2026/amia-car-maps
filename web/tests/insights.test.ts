import { describe, expect, it } from "vitest";
import { classChanges, compareLayerId, enviParts, enviSentence, summaryPoint } from "../lib/insights";
import type { Layer, Payload } from "../lib/types";

const legend = (labels: string[]) => ({
  id: "x", kind: "categorical" as const, title: "", unit: "", no_data: { label: "No data", color: "#ccc" },
  classes: labels.map((label) => ({ label, color: `#${label.length}00000` })),
});
const CLASSES = ["Very Low", "Low", "Moderate", "High", "Very High"];
const layer = (id: string, values: Record<string, string>): Layer => ({
  id, label: id, variable: "", unit: "", legend: legend(CLASSES),
  values: Object.fromEntries(Object.entries(values).map(([k, c]) => [k, { value: c, class: c, color: "#000" }])),
});
const payload = (type: any, layers: Layer[]): Payload =>
  ({ type, layers, period: { kind: "season", start: "2026-10-01", end: "", label: "Oct 2026" }, issued: "2026-09-15" }) as any;

describe("ENVI parts", () => {
  const v = { value: "High", class: "High", color: "#f00", envi: 0.65, hazard_norm: 0.8, damage_norm: 0.4, crops_norm: 0.6 };

  it("adds up weight × normalized indicator to the ENVI", () => {
    const parts = enviParts(v, { hazard: 0.5, damage: 0.25, crops: 0.25 })!;
    expect(parts.map((p) => p.value)).toEqual([0.4, 0.1, 0.15]);
    expect(parts.reduce((s, p) => s + p.value, 0)).toBeCloseTo(0.65);
    expect(parts.reduce((s, p) => s + p.share, 0)).toBeCloseTo(1);
  });

  it("falls back to the default weights and needs all three indicators", () => {
    expect(enviParts(v, null)![0].weight).toBe(0.7);
    expect(enviParts({ ...v, crops_norm: null }, null)).toBeNull();
  });

  it("explains the class with the biggest factor first", () => {
    const s = enviSentence("Tabuk", "High", 0.65, enviParts(v, null)!);
    expect(s).toBe("Tabuk is High (ENVI 0.65) mainly because of its drought forecast (79% of the score), then standing crops (13%) and past El Niño damage (8%).");
  });
});

describe("change since the last issue", () => {
  it("lists areas that moved class, with the direction", () => {
    const cur = layer("envi", { A: "High", B: "Low", C: "Moderate", D: "No data" });
    const prev = layer("envi", { A: "Moderate", B: "Very High", C: "Moderate", D: "Low" });
    const ch = classChanges(cur, prev);
    expect(Object.keys(ch).sort()).toEqual(["A", "B"]);
    expect(ch.A).toMatchObject({ from: "Moderate", to: "High", dir: 1, steps: 1 });
    expect(ch.B).toMatchObject({ dir: -1, steps: 3 });
  });

  it("compares the same map, else the summary layer, else nothing", () => {
    const cur = payload("rainfall_dekad", [layer("d_2026-10-05", {}), layer("total", {})]);
    const prev = payload("rainfall_dekad", [layer("d_2026-09-25", {}), layer("total", {})]);
    expect(compareLayerId(cur, "d_2026-10-05", prev)).toBe("total");
    expect(compareLayerId(cur, "total", prev)).toBe("total");
    const d1 = payload("drought", [layer("m_2026-10", {}), layer("m_2026-11", {})]);
    const d0 = payload("drought", [layer("m_2026-09", {}), layer("m_2026-10", {})]);
    expect(compareLayerId(d1, "m_2026-10", d0)).toBe("m_2026-10");
    expect(compareLayerId(d1, "m_2026-11", d0)).toBeNull();
  });

  it("reads an area's summary value for the trend", () => {
    const l = layer("envi", { A: "High" });
    l.values.A.envi = 0.71;
    expect(summaryPoint(payload("envi", [l]), "A")).toMatchObject({ value: 0.71, class: "High" });
    expect(summaryPoint(payload("envi", [l]), "Z")).toBeNull();
    expect(summaryPoint(payload("drought", [l]), "A")).toBeNull();
  });
});
