import { errorResponse, requireRole } from "@/lib/server/auth";
import { latestEnviInput } from "@/lib/server/reuse";

export const dynamic = "force-dynamic";

/** What the ENVI upload reuses when no new file is given: the historical damage and livestock files of the latest
 * ENVI issue that has them. */
export async function GET() {
  try {
    await requireRole("editor");
    const [d, l] = await Promise.all([latestEnviInput("damage"), latestEnviInput("livestock")]);
    const info = (r: Awaited<ReturnType<typeof latestEnviInput>>) =>
      r && { filename: r.file.filename, issue: r.issue, issued: r.issued, status: r.status, as_of: r.settings?.livestock_as_of ?? null };
    return Response.json({ damage: info(d), livestock: info(l) });
  } catch (e) {
    return errorResponse(e);
  }
}
