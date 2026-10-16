/**
 * The HVCDP Regional Summary workbook is large (pivot tables, link sheets, 40+ formula columns – 5 MB and growing),
 * over the 4 MB upload limit. Before uploading, the browser keeps only the planting-record columns the ENVI uses
 * from the sheet that holds them and sends them as a gzip-compressed CSV (`… .csv.gz`, a few hundred kB). Values are
 * kept as stored in the workbook (dates as Excel serial numbers); all checks and computations stay in the worker.
 *
 * A minimal XLSX reader: ZIP central directory + `DecompressionStream("deflate-raw")`, shared strings and the
 * sheet XML read with regular expressions (no spreadsheet library needed).
 */

// header prefixes of the columns to keep (same names the worker looks for, envi/exposure.py HVC_COLUMNS)
export const HVC_KEEP = [
  "MONTH PLANTED", "DATE PLANTED", "PROVINCE", "MUNICIPALITY", "CITY/MUNICIPALITY", "NAME OF COMMODITY", "COMMODITY",
  "CROP GROUP", "CROPS AREA PLANTED", "AREA PLANTED", "TARGET MONTH OF HARVEST", "TARGET HARVEST", "MULTI HARVEST",
];
const HEADER_MARK = "NAME OF COMMODITY";

const norm = (s: string) => s.replace(/\s+/g, " ").trim().toUpperCase();

interface Entry { name: string; method: number; size: number; offset: number }

function entries(buf: Uint8Array): Map<string, Entry> {
  const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  let eocd = -1;
  for (let i = buf.length - 22; i >= Math.max(0, buf.length - 66000); i--) {
    if (dv.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
  }
  if (eocd < 0) throw new Error("not an .xlsx file");
  const n = dv.getUint16(eocd + 10, true);
  let p = dv.getUint32(eocd + 16, true);
  const out = new Map<string, Entry>();
  const dec = new TextDecoder();
  for (let i = 0; i < n; i++) {
    if (dv.getUint32(p, true) !== 0x02014b50) throw new Error("damaged .xlsx file");
    const method = dv.getUint16(p + 10, true);
    const size = dv.getUint32(p + 20, true);
    const nameLen = dv.getUint16(p + 28, true), extra = dv.getUint16(p + 30, true), comment = dv.getUint16(p + 32, true);
    const offset = dv.getUint32(p + 42, true);
    const name = dec.decode(buf.subarray(p + 46, p + 46 + nameLen));
    out.set(name, { name, method, size, offset });
    p += 46 + nameLen + extra + comment;
  }
  return out;
}

async function read(buf: Uint8Array, e: Entry | undefined): Promise<string> {
  if (!e) return "";
  const dv = new DataView(buf.buffer, buf.byteOffset, buf.byteLength);
  const start = e.offset + 30 + dv.getUint16(e.offset + 26, true) + dv.getUint16(e.offset + 28, true);
  const data = buf.slice(start, start + e.size);
  if (e.method === 0) return new TextDecoder().decode(data);
  if (e.method !== 8) throw new Error(`unsupported compression in ${e.name}`);
  const stream = new Blob([data]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
  return new Response(stream).text();
}

const unescape = (s: string) =>
  s.replace(/&(lt|gt|amp|quot|apos|#\d+|#x[0-9a-f]+);/gi, (_, k: string) =>
    k === "lt" ? "<" : k === "gt" ? ">" : k === "amp" ? "&" : k === "quot" ? '"' : k === "apos" ? "'"
      : String.fromCodePoint(k[1] === "x" || k[1] === "X" ? parseInt(k.slice(2), 16) : parseInt(k.slice(1), 10)));

const text = (xml: string) => unescape([...xml.matchAll(/<t(?:\s[^>]*)?>([\s\S]*?)<\/t>/g)].map((m) => m[1]).join(""));

function colIndex(ref: string): number {
  let n = 0;
  for (const ch of ref) {
    const c = ch.charCodeAt(0);
    if (c < 65 || c > 90) break;
    n = n * 26 + (c - 64);
  }
  return n - 1;
}

/** Rows of a sheet as arrays of cell texts (empty cells as ""). */
function* rows(xml: string, shared: string[]): Generator<string[]> {
  const rowRe = /<row\b[^>]*?(?:\/>|>([\s\S]*?)<\/row>)/g;
  const cellRe = /<c\b([^>]*?)(?:\/>|>([\s\S]*?)<\/c>)/g;
  for (const r of xml.matchAll(rowRe)) {
    const out: string[] = [];
    for (const c of (r[1] ?? "").matchAll(cellRe)) {
      const attrs = c[1], body = c[2] ?? "";
      const ref = /\br="([A-Z]+)\d+"/.exec(attrs)?.[1];
      const t = /\bt="(\w+)"/.exec(attrs)?.[1];
      const v = /<v>([\s\S]*?)<\/v>/.exec(body)?.[1];
      let val = "";
      if (t === "s" && v !== undefined) val = shared[Number(v)] ?? "";
      else if (t === "inlineStr") val = text(body);
      else if (v !== undefined) val = unescape(v);
      const i = ref ? colIndex(ref) : out.length;
      while (out.length < i) out.push("");
      out[i] = val;
    }
    yield out;
  }
}

const csvCell = (s: string) => (/[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);

/** The planting records of an HVCDP Regional Summary workbook as CSV text (kept columns only). */
export async function hvcCsv(file: Blob): Promise<{ csv: string; sheet: string; rows: number }> {
  const buf = new Uint8Array(await file.arrayBuffer());
  const zip = entries(buf);
  const shared = [...(await read(buf, zip.get("xl/sharedStrings.xml"))).matchAll(/<si>([\s\S]*?)<\/si>/g)].map((m) => text(m[1]));
  const wb = await read(buf, zip.get("xl/workbook.xml"));
  const rels = await read(buf, zip.get("xl/_rels/workbook.xml.rels"));
  const target = (rid: string) => {
    const t = new RegExp(`<Relationship\\b[^>]*Id="${rid}"[^>]*Target="([^"]+)"`).exec(rels)?.[1]
      ?? new RegExp(`<Relationship\\b[^>]*Target="([^"]+)"[^>]*Id="${rid}"`).exec(rels)?.[1] ?? "";
    return t.startsWith("/") ? t.slice(1) : `xl/${t}`;
  };
  const sheets = [...wb.matchAll(/<sheet\b[^>]*?name="([^"]*)"[^>]*?r:id="([^"]+)"/g)].map((m) => ({ name: unescape(m[1]), path: target(m[2]) }));
  // the sheet called "Regional Summary" first, then the others
  sheets.sort((a, b) => Number(/regional summary/i.test(b.name)) - Number(/regional summary/i.test(a.name)));
  for (const sh of sheets) {
    const xml = await read(buf, zip.get(sh.path));
    let keep: number[] | null = null;
    const lines: string[] = [];
    let seen = 0;
    for (const r of rows(xml, shared)) {
      if (!keep) {
        if (++seen > 20) break;
        if (!r.some((c) => norm(c).startsWith(HEADER_MARK))) continue;
        keep = r.map((c, i) => (HVC_KEEP.some((k) => norm(c).startsWith(k)) ? i : -1)).filter((i) => i >= 0);
      }
      if (keep.every((i) => !r[i])) continue;
      lines.push(keep.map((i) => csvCell(r[i] ?? "")).join(","));
    }
    if (keep) return { csv: lines.join("\n"), sheet: sh.name, rows: lines.length - 1 };
  }
  throw new Error(`no sheet has a "${HEADER_MARK}" column – is this the HVCDP Regional Summary?`);
}

/** HVCDP workbook → compressed CSV file ready to upload (CSV files are passed through unchanged). */
export async function slimHvcFile(file: File): Promise<{ file: File; note: string }> {
  if (!/\.xlsx$|\.xlsm$/i.test(file.name)) return { file, note: "" };
  const { csv, sheet, rows: n } = await hvcCsv(file);
  const gz = await new Response(new Blob([csv]).stream().pipeThrough(new CompressionStream("gzip"))).blob();
  const name = `${file.name.replace(/\.(xlsx|xlsm)$/i, "")}.csv.gz`;
  const kb = (b: number) => (b > 1024 * 1024 ? `${(b / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} kB`);
  return {
    file: new File([gz], name, { type: "application/gzip" }),
    note: `${n.toLocaleString()} planting records read from sheet “${sheet}”; ${kb(file.size)} reduced to ${kb(gz.size)} for upload.`,
  };
}
