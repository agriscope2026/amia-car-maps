import { errorResponse, HttpError } from "@/lib/server/auth";
import { runTcAuto } from "@/lib/server/tcAuto";

export const dynamic = "force-dynamic";
export const maxDuration = 300;

/**
 * Automatic Special Farm Weather Outlook and Advisory: called by an external scheduler (e.g. cron-job.org – Vercel's
 * free plan allows only daily cron jobs) 3 minutes after each PAGASA bulletin (5 AM, 11 AM, 5 PM, 11 PM Philippine
 * time), retried at :15 and :30. GET with `Authorization: Bearer $CRON_SECRET`. Does nothing while the admin switch
 * is off.
 */
export async function GET(req: Request) {
  try {
    const secret = process.env.CRON_SECRET ?? "";
    if (!secret || req.headers.get("authorization") !== `Bearer ${secret}`) throw new HttpError(401, "Unauthorized");
    const res = await runTcAuto();
    return Response.json(res, { status: res.ok ? 200 : 502 });
  } catch (e) {
    return errorResponse(e);
  }
}
