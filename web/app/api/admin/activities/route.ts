import { assertSameOrigin, errorResponse, requireRole } from "@/lib/server/auth";
import { cleanActivity } from "@/lib/server/activities";
import { addActivities, audit, listActivities } from "@/lib/server/repo";

export const dynamic = "force-dynamic";

/** Staff: every activity, with who entered it and where it came from. */
export async function GET() {
  try {
    await requireRole("editor");
    return Response.json({ activities: await listActivities() });
  } catch (e) {
    return errorResponse(e);
  }
}

/** Staff: add one activity (entered by hand). */
export async function POST(req: Request) {
  try {
    await assertSameOrigin();
    const user = await requireRole("editor");
    const row = await cleanActivity(await req.json());
    await addActivities([row], user, "manual");
    await audit(user, "activity_add", "activities", undefined, { title: row.title, status: row.status, places: row.area_keys.length });
    return Response.json({ ok: true });
  } catch (e) {
    return errorResponse(e);
  }
}
