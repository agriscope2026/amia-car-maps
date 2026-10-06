import { getPublishedPayload } from "@/lib/server/repo";
import { errorResponse } from "@/lib/server/auth";

export const dynamic = "force-dynamic";

export async function GET(_req: Request, ctx: { params: Promise<{ id: string }> }) {
  try {
    const p = await getPublishedPayload((await ctx.params).id);
    if (!p) return Response.json({ error: "Not found" }, { status: 404 });
    delete p.report;
    return Response.json(p, { headers: { "Cache-Control": "public, s-maxage=300, stale-while-revalidate=3600" } });
  } catch (e) {
    return errorResponse(e);
  }
}
