import { existsSync, readFileSync } from "fs";
import path from "path";
import { gunzipSync } from "zlib";
import { describe, expect, it } from "vitest";
import { hvcCsv, slimHvcFile } from "../lib/hvcSlim";

// the DA-RFO-CAR sample (not in every checkout)
const SAMPLE = path.join(__dirname, "..", "..", "sample data", "sample input", "HVC REGIONAL SUMMARY 2025-2026.xlsx");

describe.skipIf(!existsSync(SAMPLE))("HVCDP Regional Summary slimming", () => {
  const file = () => new File([readFileSync(SAMPLE)], path.basename(SAMPLE));

  it("keeps the planting-record columns of the summary sheet", async () => {
    const { csv, sheet, rows } = await hvcCsv(file());
    const [head, first] = csv.split("\n");
    expect(sheet).toBe("REGIONAL SUMMARY");
    expect(rows).toBeGreaterThan(30000);
    expect(head).toContain("NAME OF COMMODITY");
    expect(head).toContain("DATE PLANTED");
    expect(head).toContain("TARGET MONTH OF HARVEST");
    expect(head).not.toContain("BARANGAY");
    expect(first.split(",")[0]).toMatch(/^4\d{4}$/); // month planted as an Excel serial date
  }, 60_000);

  it("compresses it under the 4 MB upload limit", async () => {
    const { file: out, note } = await slimHvcFile(file());
    expect(out.name).toMatch(/\.csv\.gz$/);
    expect(out.size).toBeLessThan(1024 * 1024);
    const csv = gunzipSync(Buffer.from(await out.arrayBuffer())).toString("utf8");
    expect(csv.split("\n").length).toBeGreaterThan(30000);
    expect(note).toContain("planting records");
  }, 60_000);
});
