import { assertSameOrigin, errorResponse, HttpError, requireRole } from "@/lib/server/auth";
import { audit, getCrops, getVersion, updateDraft } from "@/lib/server/repo";
import { loadUpload, worker } from "@/lib/server/worker";

/** Start an export job on the worker for a draft version. */
export async function POST(req: Request, ctx: { params: Promise<{ id: string }> }) {
  try {
    await assertSameOrigin();
    const user = await requireRole("editor");
    const id = (await ctx.params).id;
    const v = await getVersion(id);
    if (!v?.payload) throw new HttpError(404, "Not found");
    if (v.status === "archived") throw new HttpError(409, "Archived versions cannot be exported.");
    if (v.status === "published" && user.role !== "admin")
      throw new HttpError(403, "Only admins can regenerate the exports of a published version.");
    // optional: standing crops as proportional circles on the maps (seasonal rainfall)
    const body = await req.json().catch(() => ({}));
    let cropList: string[] = Array.isArray(body.crop_overlay) ? body.crop_overlay.filter((c: unknown) => typeof c === "string") : v.settings.crop_overlay_crops ?? [];
    let crop_overlay = null;
    if (cropList.length) {
      const crops = await getCrops();
      if (!crops) throw new HttpError(409, "Upload a standing crops table first (Reference data).");
      cropList = cropList.filter((c) => crops.crops.includes(c));
      const values = Object.fromEntries(
        Object.entries(crops.values).map(([k, row]) => [k, Object.fromEntries(cropList.map((c) => [c, row[c] ?? 0]))]),
      );
      crop_overlay = { as_of: crops.as_of, crops: Object.fromEntries(cropList.map((c) => [c, crops.colors?.[c] ?? "#2e7d32"])), values };
    }
    if (Array.isArray(body.crop_overlay))
      await updateDraft(id, { settings: { crop_overlay_crops: cropList } }, v.status === "published");
    const form = new FormData();
    form.set("settings", JSON.stringify({ ...v.settings, version_id: v.id, texts: v.payload.texts, crop_overlay }));
    if (v.type === "envi") {
      for (const f of v.settings.input_files ?? []) form.set(f.field, await loadUpload(f), f.filename);
    } else {
      form.set("payload", JSON.stringify(v.payload));
    }
    const job = await worker(`/jobs/${v.type}`, { method: "POST", body: form });
    if (v.status === "published") {
      // keep the live files until the new ones are ready
      await updateDraft(id, { exports: { ...(v.exports ?? {}), pending_job: job.id } }, true);
    } else {
      await updateDraft(id, { exports: { job_id: job.id } });
    }
    await audit(user, "export", "product_version", id, { job: job.id, crop_overlay: cropList });
    return Response.json({ job: job.id });
  } catch (e) {
    return errorResponse(e);
  }
}
