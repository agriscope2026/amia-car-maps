import "server-only";
import { getVersion, publish, updateDraft, type Actor } from "./repo";
import { downloadsFromManifest, localExportUrl, publishSupabaseExports, pullJobFiles, supabaseConfigured } from "./exports";
import { pruneVersionFiles } from "./storage-cleanup";

/** A finished export job: attach its files to the version (once). Used when polling a job and by automatic runs. */
export async function attachJobExports(versionId: string, jobId: string, job: any) {
  const v = await getVersion(versionId);
  const regen = v?.exports?.pending_job === jobId;
  if (!v || !(regen || (v.exports?.job_id === jobId && !v.exports.downloads?.length))) return;
  if (!supabaseConfigured()) await pullJobFiles(jobId, versionId, job.manifest);
  const downloads =
    supabaseConfigured() && v.status === "published"
      ? await publishSupabaseExports(versionId, job.manifest)
      : downloadsFromManifest(job.manifest, localExportUrl(versionId, job.manifest?.created));
  await updateDraft(versionId, { exports: { job_id: jobId, manifest: job.manifest, downloads } }, v.status === "published");
  // files of the previous export that the new one no longer has (renamed / removed kinds) – R2 only
  await pruneVersionFiles(versionId, job.manifest, v.status === "published").catch((e) => console.error("prune failed:", e));
}

/** Publish a draft whose exports are ready: earlier published versions of the same product are archived. */
export async function publishDraft(id: string, actor: Actor | string) {
  const v = await getVersion(id);
  if (!v) throw new Error("Not found");
  if (v.status !== "draft") throw new Error("Only drafts can be published.");
  if (!v.exports?.manifest) throw new Error("Generate the exports before publishing.");
  if (supabaseConfigured()) {
    const downloads = await publishSupabaseExports(id, v.exports.manifest);
    await updateDraft(id, { exports: { ...v.exports, downloads } });
  }
  await publish(id, actor);
  return v;
}
