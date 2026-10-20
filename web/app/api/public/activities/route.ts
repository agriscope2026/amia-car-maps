import { listActivities } from "@/lib/server/repo";
import { errorResponse } from "@/lib/server/auth";

export const dynamic = "force-dynamic";

/** Every activity, for the public activities page. */
export async function GET() {
  try {
    const activities = (await listActivities()).map(({ created_by: _by, source: _src, ...a }) => a);
    return Response.json({ activities }, { headers: { "Cache-Control": "public, s-maxage=60, stale-while-revalidate=600" } });
  } catch (e) {
    return errorResponse(e);
  }
}
