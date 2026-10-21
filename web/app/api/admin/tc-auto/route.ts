import { assertSameOrigin, errorResponse, HttpError, requireRole } from "@/lib/server/auth";
import { audit, setSetting } from "@/lib/server/repo";
import { getTcAuto, runTcAuto, TC_AUTO_KEY } from "@/lib/server/tcAuto";

export const maxDuration = 300;

/** The automatic Special Advisory switch and the result of its last run. */
export async function GET() {
  try {
    await requireRole("editor");
    return Response.json(await getTcAuto());
  } catch (e) {
    return errorResponse(e);
  }
}

/** Admins turn automatic updating on or off: { enabled: boolean }. */
export async function PUT(req: Request) {
  try {
    await assertSameOrigin();
    const user = await requireRole("admin");
    const body = await req.json().catch(() => ({}));
    if (typeof body.enabled !== "boolean") throw new HttpError(400, "enabled must be true or false");
    const next = { ...(await getTcAuto()), enabled: body.enabled, updated_by: user.email, updated_at: new Date().toISOString() };
    await setSetting(TC_AUTO_KEY, next);
    await audit(user, body.enabled ? "tc_auto_on" : "tc_auto_off", "app_settings", TC_AUTO_KEY);
    return Response.json(next);
  } catch (e) {
    return errorResponse(e);
  }
}

/** Admins run it now (fetch, export, publish, delete the older ones) – also while automatic updating is off. */
export async function POST() {
  try {
    await assertSameOrigin();
    const user = await requireRole("admin");
    await audit(user, "tc_auto_run", "app_settings", TC_AUTO_KEY);
    const res = await runTcAuto({ force: true });
    return Response.json({ ...res, setting: await getTcAuto() }, { status: res.ok ? 200 : 502 });
  } catch (e) {
    return errorResponse(e);
  }
}
