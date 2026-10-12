import crypto from "crypto";
import { assertSameOrigin, errorResponse, HttpError, requireRole } from "@/lib/server/auth";
import { audit } from "@/lib/server/repo";
import { loadUpload, MAX_UPLOAD_BYTES, signPayload, storeUploads, worker, type StoredFile } from "@/lib/server/worker";
import { latestEnviInput } from "@/lib/server/reuse";

const TYPES = ["envi", "rainfall_dekad", "rainfall_seasonal", "drought"];
const FIELDS: Record<string, string[]> = { envi: ["drought", "damage", "crops"], default: ["file"] };

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
        if (!/\.(csv|xlsx|xlsm|xls)$/i.test(f.name)) throw new HttpError(400, `${f.name}: upload a .csv or .xlsx file.`);
        files.push({ field, file: f });
      }
    }
    const fwd = new FormData();
    fwd.set("settings", settings);
    for (const { field, file } of files) fwd.set(field, file, file.name);
    // ENVI monthly update: historical damage changes rarely – without a new file, reuse the latest issue's
    let reused: (StoredFile & { issue: string }) | null = null;
    if (type === "envi" && !files.some((f) => f.field === "damage") && form.get("reuse_damage") !== "0") {
      const r = await latestEnviInput("damage");
      if (r) {
        fwd.set("damage", await loadUpload(r.file), r.file.filename);
        reused = { ...r.file, issue: r.issue };
      }
    }
    const payload = await worker(`/preview/${type}`, { method: "POST", body: fwd });
    const stored = files.length ? await storeUploads(uploadId, files) : [];
    // the reused file stays where it is; the new issue just points to it (its exports read it from there)
    if (reused) stored.push({ field: reused.field, filename: reused.filename, path: reused.path, sha256: reused.sha256 });
    await audit(user, "validate", type, uploadId, {
      files: stored.map((s) => s.filename), ok: payload.ok, ...(reused ? { reused_damage_from: reused.issue } : {}),
    });
    return Response.json({
      payload, uploadId, files: stored, sig: payload.ok ? signPayload(payload, uploadId) : null,
      reused: reused ? { damage: { filename: reused.filename, issue: reused.issue } } : null,
    });
  } catch (e) {
    return errorResponse(e);
  }
}
