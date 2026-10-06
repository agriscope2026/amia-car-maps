import { assertSameOrigin, errorResponse, requireRole } from "@/lib/server/auth";
import { audit, unpublish } from "@/lib/server/repo";

/** Admins can take a published product (or a demo product) off the public dashboard. */
export async function POST(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  try {
    await assertSameOrigin();
    const user = await requireRole("admin");
    const id = (await ctx.params).id;
    await unpublish(id);
    await audit(user, "unpublish", "product_version", id);
    return Response.json({ ok: true });
  } catch (e) {
    return errorResponse(e);
  }
}
