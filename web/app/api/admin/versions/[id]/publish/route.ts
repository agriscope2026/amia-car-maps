import { assertSameOrigin, errorResponse, HttpError, requireRole } from "@/lib/server/auth";
import { audit, getVersion, publish, updateDraft } from "@/lib/server/repo";
import { publishSupabaseExports, supabaseConfigured } from "@/lib/server/exports";

/** Admins publish a draft: earlier published versions of the same product are archived. */
export async function POST(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  try {
    await assertSameOrigin();
    const user = await requireRole("admin");
    const id = (await ctx.params).id;
    const v = await getVersion(id);
    if (!v) throw new HttpError(404, "Not found");
    if (v.status !== "draft") throw new HttpError(409, "Only drafts can be published.");
    if (!v.exports?.manifest) throw new HttpError(409, "Generate the exports before publishing.");
    if (supabaseConfigured()) {
      const downloads = await publishSupabaseExports(id, v.exports.manifest);
      await updateDraft(id, { exports: { ...v.exports, downloads } });
    }
    await publish(id, user);
    await audit(user, "publish", "product_version", id, { type: v.type, version: v.version, period: v.period });
    return Response.json({ ok: true });
  } catch (e) {
    return errorResponse(e);
  }
}
