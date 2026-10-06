import { assertSameOrigin, errorResponse, HttpError, requireRole } from "@/lib/server/auth";
import { promises as fs } from "fs";
import path from "path";
import { audit, deleteVersion, getVersion, LOCAL_EXPORTS_DIR, updateDraft } from "@/lib/server/repo";

const TEXT_KEYS = ["title", "subtitle", "notes", "disclaimer", "sources", "recommendations", "advice_rice", "advice_corn",
  "advice_hvc"] as const;

export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  try {
    await requireRole("editor");
    const v = await getVersion((await ctx.params).id);
    if (!v) throw new HttpError(404, "Not found");
    return Response.json(v);
  } catch (e) {
    return errorResponse(e);
  }
}

/** Edit the texts of a draft (title, subtitle, notes, disclaimer, sources, recommendations). */
export async function PATCH(req: Request, ctx: { params: Promise<{ id: string }> }) {
  try {
    await assertSameOrigin();
    const user = await requireRole("editor");
    const id = (await ctx.params).id;
    const body = await req.json();
    const texts: Record<string, string> = {};
    for (const k of TEXT_KEYS) {
      const val = body.texts?.[k];
      if (val === undefined) continue;
      if (typeof val !== "string" || val.length > 20000) throw new HttpError(400, `Invalid ${k}`);
      texts[k] = val;
    }
    const v = await getVersion(id);
    if (!v) throw new HttpError(404, "Not found");
    if (v.status === "published" && user.role !== "admin")
      throw new HttpError(403, "Only admins can edit a published version.");
    if (v.status === "archived") throw new HttpError(409, "Archived versions are read-only.");
    await updateDraft(id, { texts }, v.status === "published");
    await audit(user, v.status === "published" ? "edit_published" : "edit", "product_version", id, {
      fields: Object.keys(texts),
    });
    return Response.json({ ok: true });
  } catch (e) {
    return errorResponse(e);
  }
}

/** Admins permanently delete an archived (or draft) version and its export files. Published versions are protected. */
export async function DELETE(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  try {
    await assertSameOrigin();
    const user = await requireRole("admin");
    const id = (await ctx.params).id;
    const v = await getVersion(id);
    if (!v) throw new HttpError(404, "Not found");
    if (v.status === "published") throw new HttpError(409, "Unpublish this version before deleting it.");
    await deleteVersion(id);
    if (/^[\w-]+$/.test(id)) await fs.rm(path.join(LOCAL_EXPORTS_DIR, id), { recursive: true, force: true });
    await audit(user, "delete_version", "product_version", id, { type: v.type, version: v.version, period: v.period, status: v.status });
    return Response.json({ ok: true });
  } catch (e) {
    return errorResponse(e);
  }
}
