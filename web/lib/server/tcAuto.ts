import "server-only";
import { promises as fs } from "fs";
import path from "path";
import { audit, createDraft, deleteVersion, getSetting, getVersion, listVersions, LOCAL_EXPORTS_DIR, setSetting, unpublish, updateDraft,
  type VersionRecord } from "./repo";
import { HttpError } from "./auth";
import { worker } from "./worker";
import { attachJobExports, publishDraft } from "./versionOps";

/**
 * Automatic Special Farm Weather Outlook and Advisory. PAGASA issues its Tropical Cyclone Bulletin at 5 AM, 11 AM,
 * 5 PM and 11 PM (Philippine time); when "automatic" is on, a scheduled run 3 minutes later (vercel.json, with
 * retries at :15 and :30 in case PAGASA is late) fetches the new bulletin, makes the exports, publishes it and
 * deletes the older advisories.
 *
 * A run can be cut short (serverless time limit, worker restart): the next run picks up the same bulletin where it
 * stopped – exports still running, or ready but not yet published.
 */
export const TC_AUTO_KEY = "tc_auto";
const ACTOR = "automatic (PAGASA bulletin)";
const TYPE = "tc_advisory";

export interface TcAutoSetting {
  enabled: boolean;
  updated_by?: string;
  updated_at?: string;
  last_run?: { at: string; result: string; ok: boolean; bulletin?: string; version_id?: string };
}

export async function getTcAuto(): Promise<TcAutoSetting> {
  return { enabled: false, ...((await getSetting(TC_AUTO_KEY)) ?? {}) };
}

async function remember(last: TcAutoSetting["last_run"]) {
  await setSetting(TC_AUTO_KEY, { ...(await getTcAuto()), last_run: last });
}

const bulletinKey = (p: any) => `${p?.tc?.name ?? "?"} #${p?.tc?.bulletin_no ?? "?"}`;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Remove every other advisory: unpublish the live one, then delete it (drafts someone made by hand are kept). */
async function removeOlder(keep: string) {
  const old = (await listVersions()).filter(
    (v) => v.type === TYPE && v.id !== keep && (v.status !== "draft" || v.settings?.source === "pagasa-auto"),
  );
  for (const v of old) {
    if (v.status === "published") await unpublish(v.id);
    await deleteVersion(v.id);
    if (/^[\w-]+$/.test(v.id)) await fs.rm(path.join(LOCAL_EXPORTS_DIR, v.id), { recursive: true, force: true });
  }
  return old.length;
}

/** Wait for the export job (until the deadline), attach its files and publish. */
async function finish(v: VersionRecord, deadline: number): Promise<{ done: boolean; result: string }> {
  let jobId = v.exports?.job_id;
  if (!v.exports?.manifest) {
    if (!jobId) {
      const form = new FormData();
      form.set("settings", JSON.stringify({ ...v.settings, version_id: v.id, texts: v.payload?.texts }));
      form.set("payload", JSON.stringify(v.payload));
      jobId = (await worker(`/jobs/${TYPE}`, { method: "POST", body: form })).id as string;
      await updateDraft(v.id, { exports: { job_id: jobId } });
    }
    for (;;) {
      let job: any;
      try {
        job = await worker(`/jobs/${jobId}`);
      } catch (e) {
        if (e instanceof HttpError && e.status === 404) {
          // the worker restarted and lost the job: start it again next time
          await updateDraft(v.id, { exports: {} });
          return { done: false, result: "The map worker restarted during the exports – they are restarted on the next run." };
        }
        throw e;
      }
      if (job.status === "error") {
        await updateDraft(v.id, { exports: {} });
        return { done: false, result: `Exports failed: ${job.error ?? "unknown error"} – tried again on the next run.` };
      }
      if (job.status === "done") {
        await attachJobExports(v.id, jobId!, job);
        break;
      }
      if (Date.now() > deadline) return { done: false, result: "Exports still running – published on the next run." };
      await sleep(4000);
    }
  }
  await publishDraft(v.id, ACTOR);
  const removed = await removeOlder(v.id);
  return { done: true, result: `Published${removed ? `; ${removed} older advisor${removed > 1 ? "ies" : "y"} deleted` : ""}.` };
}

/**
 * One automatic run. `force` runs it even when automatic updating is off (the admin's "Run now").
 * `budgetMs`: how long it may take (stays under the serverless time limit).
 */
export async function runTcAuto({ force = false, budgetMs = 250_000 } = {}) {
  const started = Date.now();
  const deadline = started + budgetMs;
  const setting = await getTcAuto();
  if (!setting.enabled && !force) return { ok: true, skipped: "Automatic updating is off." };
  const at = new Date().toISOString();
  try {
    const res = await worker("/feeds/tc_advisory/fetch", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }, 120_000);
    const p = res.payload;
    if (!p?.ok) {
      const result = res.error ?? "PAGASA has no active tropical cyclone bulletin.";
      await remember({ at, ok: true, result: `Nothing to publish: ${result}` });
      return { ok: true, skipped: result };
    }
    const key = bulletinKey(p);
    const same = (await listVersions()).find((v) => v.type === TYPE && v.settings?.tc_bulletin === key);
    if (same?.status === "published") {
      await remember({ at, ok: true, result: "Already published – waiting for PAGASA's next bulletin.", bulletin: key, version_id: same.id });
      return { ok: true, skipped: "already published", bulletin: key };
    }
    let v = same ? await getVersion(same.id) : null;
    if (!v) {
      const created = await createDraft(p, { source: "pagasa-auto", tc_bulletin: key }, ACTOR);
      v = await getVersion(created.id);
      await audit(ACTOR, "create_draft", TYPE, created.id, { bulletin: key, period: p.period });
    }
    const out = await finish(v!, deadline);
    if (out.done) await audit(ACTOR, "publish", "product_version", v!.id, { type: TYPE, bulletin: key, automatic: true });
    await remember({ at, ok: true, result: out.result, bulletin: key, version_id: v!.id });
    return { ok: true, published: out.done, result: out.result, bulletin: key, id: v!.id };
  } catch (e) {
    const result = `Failed: ${(e as Error).message}`;
    await remember({ at, ok: false, result }).catch(() => undefined);
    await audit(ACTOR, "tc_auto_failed", TYPE, undefined, { error: (e as Error).message }).catch(() => undefined);
    return { ok: false, error: result };
  }
}
