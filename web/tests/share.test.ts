import { describe, expect, it } from "vitest";
import { DEFAULT_STATE, parseState, serializeState } from "../lib/share";
import { circleRadius, cropBreaks, cropClass, escapeHtml, fmtDate, fmtValue, latestOf, sortIssues } from "../lib/format";
import type { CatalogEntry, Layer } from "../lib/types";

describe("share links", () => {
  it("round-trips product, period, layer, overlays and view", () => {
    const s = {
      ...DEFAULT_STATE,
      type: "rainfall_seasonal",
      product: "rainfall_seasonal-2026-10",
      layer: "m_2026-12",
      crops: true,
      cropSel: ["Corn", "Rice"],
      cropMode: "choropleth" as const,
      irrigation: true,
      irrTypes: ["NIS", "DAM"],
      basemap: "terrain" as const,
      view: { lng: 121.0123, lat: 17.2345, zoom: 9.5 },
    };
    const back = parseState(new URLSearchParams(serializeState(s)));
    expect(back).toEqual({ ...s, view: { lng: 121.0123, lat: 17.2345, zoom: 9.5 } });
  });

  it("defaults and ignores invalid input", () => {
    expect(serializeState(DEFAULT_STATE)).toBe("");
    const s = parseState(new URLSearchParams("v=999,abc,3&b=moon&cm=x"));
    expect(s.view).toBeUndefined();
    expect(s.basemap).toBe("light");
    expect(s.cropMode).toBe("circles");
  });
});

describe("formatting", () => {
  const mm: Layer = { id: "total", label: "", variable: "rainfall_mm", unit: "mm", values: {}, legend: { id: "x", kind: "graduated", title: "", unit: "mm", classes: [], no_data: { label: "No data", color: "#d9d9d9" } } };
  it("formats values with units", () => {
    expect(fmtValue({ value: 1234.56, class: "", color: "" }, mm)).toBe("1,234.6 mm");
    expect(fmtValue({ value: null, class: "No data", color: "" }, mm)).toBe("No data");
    expect(fmtValue({ value: 85, class: "", color: "" }, { ...mm, unit: "%" })).toBe("85% of normal");
    expect(fmtValue({ value: "Drought", class: "Drought", color: "" }, { ...mm, unit: "category" })).toBe("Drought");
  });
  it("formats dates", () => {
    expect(fmtDate("2026-10-05")).toBe("October 5, 2026");
    expect(fmtDate("2026-10")).toBe("October 2026");
  });
  it("escapes popup HTML", () => {
    expect(escapeHtml(`<img src=x onerror="a">`)).toBe("&lt;img src=x onerror=&quot;a&quot;&gt;");
  });
  it("picks the latest issue", () => {
    const e = (id: string, start: string, issued: string, version = 1) =>
      ({ id, type: "rainfall_dekad", title: "", issued, period: { kind: "dekad", start, end: start, label: "" }, status: "published", version, layers: [] }) as CatalogEntry;
    const list = [e("a", "2026-09-21", "2026-09-20"), e("b", "2026-10-01", "2026-09-30"), e("c", "2026-10-01", "2026-09-30", 2)];
    expect(latestOf(list, "rainfall_dekad")?.id).toBe("c");
    expect(sortIssues(list).map((x) => x.id)).toEqual(["c", "b", "a"]);
  });
});

describe("crop overlay", () => {
  it("scales circles by area and classes by quintile", () => {
    expect(circleRadius(100, 100, 20)).toBe(20);
    expect(circleRadius(25, 100, 20)).toBe(10);
    expect(circleRadius(0, 100)).toBe(0);
    const v = Array.from({ length: 100 }, (_, i) => i + 1);
    const b = cropBreaks(v);
    expect(b.length).toBe(4);
    expect(cropClass(1, b)).toBe(0);
    expect(cropClass(100, b)).toBe(4);
    expect(cropClass(0, b)).toBe(-1);
  });
});
