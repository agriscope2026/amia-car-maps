import { describe, expect, it } from "vitest";
import { activitiesFor, activityInput, beneficiariesText, coverage, defaultVulnerableClasses, placesSummary, worstClasses, type Activity } from "../lib/activities";
import type { Layer } from "../lib/types";

const legend = (kind: "categorical" | "graduated", labels: string[]) => ({
  id: "x", kind, title: "", unit: "", no_data: { label: "No data", color: "#ccc" },
  classes: labels.map((label, i) => ({ label, color: `#00000${i}` })),
});
const layer = (id: string, values: Record<string, string>, labels = ["Not affected", "Dry condition", "Dry spell", "Drought"]): Layer => ({
  id, label: id, variable: "", unit: "", legend: legend("categorical", labels),
  values: Object.fromEntries(Object.entries(values).map(([k, c]) => [k, { value: c, class: c, color: "#000" }])),
});
const act = (area: string | string[], status: Activity["status"], hazard: Activity["hazard"] = "general", extra: Partial<Activity> = {}): Activity => ({
  id: Math.random().toString(), area_keys: Array.isArray(area) ? area : [area], title: "x", category: null, status, hazard, start_date: null, end_date: null,
  units: null, beneficiary_type: null, beneficiaries: null, budget: null, office: null, remarks: null, source: null, created_by: null, created_at: "", updated_at: "",
  ...extra,
});

describe("vulnerable classes", () => {
  it("takes the top two categorical classes and the upper half of a graduated legend", () => {
    expect(defaultVulnerableClasses({ legend: legend("categorical", ["Very Low", "Low", "Moderate", "High", "Very High"]) })).toEqual(["High", "Very High"]);
    expect(defaultVulnerableClasses({ legend: legend("graduated", ["a", "b", "c", "d", "e", "f", "g", "h"]) })).toEqual(["e", "f", "g", "h"]);
  });

  it("keeps the worst class of an area over several months", () => {
    const w = worstClasses([layer("m_1", { A: "Dry spell", B: "Not affected" }), layer("m_2", { A: "Dry condition", B: "Drought", C: "?" })]);
    expect(w.A.class).toBe("Dry spell");
    expect(w.A.layer).toBe("m_1");
    expect(w.B.class).toBe("Drought");
    expect(w.C).toBeUndefined(); // no data
  });
});

describe("coverage", () => {
  it("counts the vulnerable areas with an activity that is not postponed", () => {
    const acts = [
      act("A", "ongoing", "envi", { beneficiaries: 10, budget: 1000 }),
      act("A", "completed"),
      act("B", "postponed"),
      act("Z", "ongoing", "envi", { beneficiaries: 99 }), // not vulnerable
    ];
    const c = coverage(["A", "B", "C"], acts);
    expect(c.covered).toBe(1);
    expect(c.gaps).toEqual(["B", "C"]);
    expect(c.counts).toEqual({ to_conduct: 0, ongoing: 1, completed: 1, postponed: 1 });
    expect(c.beneficiaries).toBe(10);
    expect(c.budget).toBe(1000);
  });

  it("counts an activity in several places once, and covers each of its places", () => {
    const acts = [act(["A", "B", "Z"], "ongoing", "envi", { beneficiaries: 300, budget: 9000 })];
    const c = coverage(["A", "B", "C"], acts);
    expect(c.covered).toBe(2);
    expect(c.gaps).toEqual(["C"]);
    expect(c.counts.ongoing).toBe(1);
    expect(c.beneficiaries).toBe(300);
    expect(c.budget).toBe(9000);
  });

  it("keeps the activities for the map and the general ones", () => {
    const acts = [act("A", "ongoing", "envi"), act("A", "ongoing", "drought"), act("A", "ongoing", "general")];
    expect(activitiesFor(acts, "envi").map((a) => a.hazard)).toEqual(["envi", "general"]);
    expect(activitiesFor(acts, "all")).toHaveLength(3);
  });
});

describe("activity input", () => {
  const ok = { area_keys: ["ABRA|TAYUM"], title: " Seed stocking ", status: "ongoing" };

  it("trims text, fills defaults and turns blanks into null", () => {
    const a = activityInput.parse({ ...ok, category: "", start_date: "", budget: null });
    expect(a).toMatchObject({ title: "Seed stocking", hazard: "general", category: null, start_date: null, budget: null });
  });

  it("refuses an unknown status, a negative number and an end before the start", () => {
    expect(activityInput.safeParse({ ...ok, status: "maybe" }).success).toBe(false);
    expect(activityInput.safeParse({ ...ok, beneficiaries: -1 }).success).toBe(false);
    expect(activityInput.safeParse({ ...ok, start_date: "2026-12-01", end_date: "2026-11-01" }).success).toBe(false);
    expect(activityInput.safeParse({ ...ok, area_keys: ["Tayum"] }).success).toBe(false);
    expect(activityInput.safeParse({ ...ok, area_keys: [] }).success).toBe(false);
  });

  it("removes repeated places", () => {
    expect(activityInput.parse({ ...ok, area_keys: ["ABRA|TAYUM", "ABRA|BANGUED", "ABRA|TAYUM"] }).area_keys).toEqual(["ABRA|BANGUED", "ABRA|TAYUM"]);
  });
});

describe("places summary", () => {
  const towns = [
    { area_key: "A|1", name: "Bangued", province: "Abra" }, { area_key: "A|2", name: "Tayum", province: "Abra" },
    { area_key: "B|1", name: "La Trinidad", province: "Benguet" }, { area_key: "B|2", name: "Tublay", province: "Benguet" },
    { area_key: "B|3", name: "Itogon", province: "Benguet" },
  ];
  it("names whole provinces, then municipalities", () => {
    expect(placesSummary(["A|1", "A|2", "B|1", "B|2"], towns)).toBe("Abra (all 2) · Benguet: La Trinidad, Tublay");
    expect(placesSummary(towns.map((t) => t.area_key), towns)).toBe("Whole CAR (all 5 municipalities)");
    expect(placesSummary(["B|1", "B|2", "B|3", "A|1"], [...towns, { area_key: "B|4", name: "Kapangan", province: "Benguet" }], 2))
      .toBe("Abra: Bangued · Benguet: Itogon + 2 more");
  });
});

describe("beneficiaries: individual farmers or farmer groups (FCA)", () => {
  it("counts farmers and FCAs apart, and words them", () => {
    const acts = [
      act("ABRA|BANGUED", "completed", "general", { beneficiaries: 2, beneficiary_type: "individual", units: 2 }),
      act("ABRA|BANGUED", "to_conduct", "general", { beneficiaries: 1, beneficiary_type: "fca", units: 1 }),
      act("ABRA|BANGUED", "ongoing", "general", { beneficiaries: 5 }),
    ];
    const c = coverage(["ABRA|BANGUED"], acts);
    expect([c.beneficiaries, c.farmers, c.fcas]).toEqual([8, 7, 1]);
    expect(beneficiariesText(3, "fca")).toBe("3 FCAs");
    expect(beneficiariesText(1, "fca")).toBe("1 FCA");
    expect(beneficiariesText(250, "individual")).toBe("250 farmers");
    expect(beneficiariesText(5, null)).toBe("5 beneficiaries");
    expect(beneficiariesText(null, "fca")).toBe("");
  });

  it("accepts units and the beneficiary type on input", () => {
    const a = activityInput.parse({ area_keys: ["ABRA|BANGUED"], title: "Provision of PISOS", status: "completed", units: 2,
      beneficiary_type: "fca", beneficiaries: 1 });
    expect([a.units, a.beneficiary_type, a.beneficiaries]).toEqual([2, "fca", 1]);
    expect(activityInput.safeParse({ area_keys: ["ABRA|BANGUED"], title: "x", status: "completed", beneficiary_type: "group" }).success).toBe(false);
  });
});
