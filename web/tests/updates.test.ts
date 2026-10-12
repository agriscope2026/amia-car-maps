import { describe, expect, it } from "vitest";
import { newUpdates, updateKey, updatedOn } from "../lib/updates";
import type { CatalogEntry } from "../lib/types";

const entry = (id: string, type: any, start: string, published_at: string | null, version = 1): CatalogEntry => ({
  id, type, title: id, issued: start, status: "published", version, layers: [], published_at,
  period: { kind: "season", start, end: start, label: start },
});
const NOW = new Date("2026-10-12T09:00:00");

describe("new update notice", () => {
  const catalog = [
    entry("envi-old", "envi", "2026-07-01", "2026-06-20"),
    entry("envi-new", "envi", "2026-10-01", "2026-10-10"),
    entry("dekad", "rainfall_dekad", "2026-10-05", "2026-10-05"),
    entry("drought", "drought", "2026-10-01", "2026-08-01"),      // published 72 days ago: not new
  ];

  it("lists the latest issue of each type that is recent and not seen, newest first", () => {
    expect(newUpdates(catalog, {}, NOW).map((e) => e.id)).toEqual(["envi-new", "dekad"]);
  });

  it("forgets an update once it is seen, and shows it again when it is republished", () => {
    const seen = { envi: updateKey(catalog[1]) };
    expect(newUpdates(catalog, seen, NOW).map((e) => e.id)).toEqual(["dekad"]);
    const republished = [...catalog.slice(0, 1), { ...catalog[1], version: 2 }, ...catalog.slice(2)];
    expect(newUpdates(republished, seen, NOW).map((e) => e.id)).toEqual(["envi-new", "dekad"]);
  });

  it("falls back to the issue date when the publish date is unknown", () => {
    const e = entry("x", "rainfall_seasonal", "2026-10-01", null);
    expect(updatedOn(e)).toBe("2026-10-01");
    expect(newUpdates([e], {}, NOW)).toHaveLength(1);
  });
});
