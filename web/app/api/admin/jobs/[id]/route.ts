import { errorResponse, HttpError, requireRole } from "@/lib/server/auth";
import { getVersion, updateDraft } from "@/lib/server/repo";
import { worker } from "@/lib/server/worker";
import { downloadsFromManifest, localExportUrl, publishSupabaseExports, pullJobFiles, supabaseConfigured } from "@/lib/server/exports";

/** Poll an export job; when it is done, attach the export files to the draft. */
export async function GET(req: Request, ctx: { params: Promise<{ id: string }> }) {
  try {
    await requireRole("editor");
    const jobId = (await ctx.params).id;
    if (!/^[a-f0-9]{32}$/.test(jobId)) throw new HttpError(404, "Unknown job");
    const versionId = new URL(req.url).searchParams.get("version") ?? "";
    const job = await worker(`/jobs/${jobId}`);
    if (job.status === "done" && versionId) {
      const v = await getVersion(versionId);
      const regen = v?.exports?.pending_job === jobId;
      if (v && (regen || (v.exports?.job_id === jobId && !v.exports.downloads?.length))) {
        if (!supabaseConfigured()) await pullJobFiles(jobId, versionId, job.manifest);
        const downloads =
          supabaseConfigured() && v.status === "published"
            ? await publishSupabaseExports(versionId, job.manifest)
            : downloadsFromManifest(job.manifest, localExportUrl(versionId));
        await updateDraft(versionId, { exports: { job_id: jobId, manifest: job.manifest, downloads } }, v.status === "published");
      }
    }
    return Response.json({ id: job.id, status: job.status, progress: job.progress, error: job.error, labels_ok: job.manifest?.labels_ok });
  } catch (e) {
    return errorResponse(e);
  }
}
