import { errorResponse, requireRole } from "@/lib/server/auth";
import { latestEnviInput } from "@/lib/server/reuse";

export const dynamic = "force-dynamic";

/** What the ENVI upload reuses when no new file is given: the historical damage file of the latest ENVI issue. */
export async function GET() {
  try {
    await requireRole("editor");
    const r = await latestEnviInput("damage");
    return Response.json({ damage: r && { filename: r.file.filename, issue: r.issue, issued: r.issued, status: r.status } });
  } catch (e) {
    return errorResponse(e);
  }
}
