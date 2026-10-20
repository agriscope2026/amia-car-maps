import { assertSameOrigin, errorResponse, requireRole } from "@/lib/server/auth";
import { cleanActivity } from "@/lib/server/activities";
import { audit, deleteActivity, updateActivity } from "@/lib/server/repo";

/** Staff: edit one activity (e.g. move it from "To conduct" to "Ongoing"). */
export async function PUT(req: Request, ctx: { params: Promise<{ id: string }> }) {
  try {
    await assertSameOrigin();
    const user = await requireRole("editor");
    const { id } = await ctx.params;
    const row = await cleanActivity(await req.json());
    await updateActivity(id, row);
    await audit(user, "activity_edit", "activities", id, { title: row.title, status: row.status });
    return Response.json({ ok: true });
  } catch (e) {
    return errorResponse(e);
  }
}

export async function DELETE(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  try {
    await assertSameOrigin();
    const user = await requireRole("editor");
    const { id } = await ctx.params;
    await deleteActivity(id);
    await audit(user, "activity_delete", "activities", id);
    return Response.json({ ok: true });
  } catch (e) {
    return errorResponse(e);
  }
}
