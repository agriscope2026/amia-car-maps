import crypto from "crypto";
import { assertSameOrigin, errorResponse, HttpError, requireRole } from "@/lib/server/auth";
import { audit } from "@/lib/server/repo";
import { loadUpload, MAX_UPLOAD_BYTES, signPayload, storeUploads, worker, type StoredFile } from "@/lib/server/worker";
import { latestEnviInput } from "@/lib/server/reuse";

const TYPES = ["envi", "rainfall_dekad", "rainfall_seasonal", "drought"];
// ENVI: hvc (HVCDP Regional Summary) and livestock are optional exposure inputs
const FIELDS: Record<string, string[]> = { envi: ["drought", "damage", "crops", "hvc", "livestock"], default: ["file"] };
// inputs that change rarely: without a new file the latest ENVI issue's file is reused
const REUSABLE = ["damage", "livestock"];

/** Validate an upload with the worker and return the preview payload (signed for the draft step). */
export async function POST(req: Request, ctx: { params: Promise<{ type: string }> }) {
  try {
    await assertSameOrigin();
    const user = await requireRole("editor");
    const type = (await ctx.params).type;
    if (!TYPES.includes(type)) throw new HttpError(404, "Unknown product type");
    const form = await req.formData();
    const given = String(form.get("uploadId") ?? "");
    const uploadId = /^[a-f0-9-]{36}$/.test(given) ? given : crypto.randomUUID();
    const settings = String(form.get("settings") ?? "{}");
    JSON.parse(settings);
    const files: { field: string; file: File }[] = [];
    for (const field of FIELDS[type] ?? FIELDS.default) {
      const f = form.get(field);
      if (f instanceof File && f.size) {
        if (f.size > MAX_UPLOAD_BYTES) throw new HttpError(413, `${f.name} is larger than 4 MB.`);
        // .csv.gz: the upload page compresses the large HVCDP workbook to the columns it needs
        if (!/\.(csv|xlsx|xlsm|xls|csv\.gz)$/i.test(f.name)) throw new HttpError(400, `${f.name}: upload a .csv or .xlsx file.`);
        files.push({ field, file: f });
      }
    }
    const fwd = new FormData();
    fwd.set("settings", settings);
    for (const { field, file } of files) fwd.set(field, file, file.name);
    // ENVI monthly update: historical damage and the (quarterly) livestock inventory change rarely – without a new
    // file, reuse the latest issue's (the upload page fills in that issue's livestock "as of" date)
    const reused: Record<string, StoredFile & { issue: string; settings?: Record<string, any> }> = {};
    if (type === "envi") {
      for (const field of REUSABLE) {
        if (files.some((f) => f.field === field) || form.get(`reuse_${field}`) === "0") continue;
        const r = await latestEnviInput(field);
        if (r) {
          fwd.set(field, await loadUpload(r.file), r.file.filename);
          reused[field] = { ...r.file, issue: r.issue, settings: r.settings };
        }
      }
    }
    const payload = await worker(`/preview/${type}`, { method: "POST", body: fwd });
    const stored = files.length ? await storeUploads(uploadId, files) : [];
    // the reused file stays where it is; the new issue just points to it (its exports read it from there)
    for (const r of Object.values(reused)) stored.push({ field: r.field, filename: r.filename, path: r.path, sha256: r.sha256 });
    await audit(user, "validate", type, uploadId, {
      files: stored.map((s) => s.filename), ok: payload.ok,
      ...Object.fromEntries(Object.entries(reused).map(([k, r]) => [`reused_${k}_from`, r.issue])),
    });
    return Response.json({
      payload, uploadId, files: stored, sig: payload.ok ? signPayload(payload, uploadId) : null,
      reused: Object.keys(reused).length
        ? Object.fromEntries(Object.entries(reused).map(([k, r]) => [k, { filename: r.filename, issue: r.issue, as_of: r.settings?.livestock_as_of }]))
        : null,
    });
  } catch (e) {
    return errorResponse(e);
  }
}
