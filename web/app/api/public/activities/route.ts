import { getSetting, listActivities } from "@/lib/server/repo";
import { errorResponse } from "@/lib/server/auth";

export const dynamic = "force-dynamic";

/** Every activity, for the public activities page, with the latest rice / corn self-sufficiency (SSL) figures. */
export async function GET() {
  try {
    const [list, ssl] = await Promise.all([listActivities(), getSetting("ssl")]);
    const activities = list.map(({ created_by: _by, source: _src, ...a }) => a);
    // who edited the SSL figures stays private
    const { edited_by: _editor, ...sslPublic } = (ssl ?? {}) as Record<string, unknown>;
    return Response.json({ activities, ssl: ssl ? sslPublic : null }, {
      headers: { "Cache-Control": "public, s-maxage=60, stale-while-revalidate=600" },
    });
  } catch (e) {
    return errorResponse(e);
  }
}
