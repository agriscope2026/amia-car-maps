import { errorResponse, HttpError } from "@/lib/server/auth";
import { audit, createDraft, listVersions, updateDraft } from "@/lib/server/repo";
import { worker } from "@/lib/server/worker";

export const dynamic = "force-dynamic";
export const maxDuration = 300;

/**
 * Daily job (Vercel Cron, see vercel.json): fetch the 10-day rainfall feed and, when it is a new issue,
 * save it as a draft and start its exports. It is never published automatically – an admin reviews it.
 * Vercel sends `Authorization: Bearer $CRON_SECRET`.
 */
export async function GET(req: Request) {
  try {
    const secret = process.env.CRON_SECRET ?? "";
    if (!secret || req.headers.get("authorization") !== `Bearer ${secret}`) throw new HttpError(401, "Unauthorized");
    // ?source=rainfall_seasonal reads PAGASA's seasonal forecast page; default: the 10-day feed
    const type = new URL(req.url).searchParams.get("source") === "rainfall_seasonal" ? "rainfall_seasonal" : "rainfall_dekad";
    const res = await worker(`/feeds/${type}/fetch`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }, 280_000);
    if (!res.payload?.ok) {
      await audit("cron", "feed_fetch_failed", type, undefined, { error: res.error, report: res.payload?.report?.errors });
      return Response.json({ ok: false, error: res.error ?? "Validation failed" }, { status: 502 });
    }
    const p = res.payload;
    const existing = (await listVersions()).find(
      (v) => v.type === type && v.period?.start === p.period.start && v.issued === p.issued,
    );
    if (existing) return Response.json({ ok: true, skipped: "already have this issue", id: existing.id });
    const v = await createDraft(p, { source: "feed", recommendations_draft: p.recommendations_draft, crop_advice_draft: p.crop_advice_draft, ...p.feed_settings }, "cron");
    const form = new FormData();
    form.set("settings", JSON.stringify({ version_id: v.id, texts: p.texts }));
    form.set("payload", JSON.stringify(p));
    const job = await worker(`/jobs/${type}`, { method: "POST", body: form });
    await updateDraft(v.id, { exports: { job_id: job.id } });
    await audit("cron", "create_draft", type, v.id, { period: p.period, from: type === "rainfall_seasonal" ? "PAGASA" : "feed" });
    return Response.json({ ok: true, id: v.id, job: job.id, period: p.period });
  } catch (e) {
    return errorResponse(e);
  }
}
