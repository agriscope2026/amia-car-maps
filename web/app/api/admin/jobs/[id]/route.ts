import { errorResponse, HttpError, requireRole } from "@/lib/server/auth";
import { worker } from "@/lib/server/worker";
import { attachJobExports } from "@/lib/server/versionOps";

/** Poll an export job; when it is done, attach the export files to the draft. */
export async function GET(req: Request, ctx: { params: Promise<{ id: string }> }) {
  try {
    await requireRole("editor");
    const jobId = (await ctx.params).id;
    if (!/^[a-f0-9]{32}$/.test(jobId)) throw new HttpError(404, "Unknown job");
    const versionId = new URL(req.url).searchParams.get("version") ?? "";
    let job: any;
    try {
      job = await worker(`/jobs/${jobId}`);
    } catch (e) {
      // the worker keeps jobs on its own disk: after a restart (deploy, crash, out of memory) the job is gone
      if (e instanceof HttpError && e.status === 404)
        return Response.json({
          id: jobId, status: "error", progress: [],
          error: "The map worker restarted while making these exports (a new deploy, or it ran out of memory). " +
            "Click Generate exports again.",
        });
      throw e;
    }
    if (job.status === "done" && versionId) await attachJobExports(versionId, jobId, job);
    return Response.json({ id: job.id, status: job.status, progress: job.progress, error: job.error, labels_ok: job.manifest?.labels_ok });
  } catch (e) {
    return errorResponse(e);
  }
}
