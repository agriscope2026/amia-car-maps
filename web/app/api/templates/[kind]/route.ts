import { errorResponse } from "@/lib/server/auth";
import { workerRaw } from "@/lib/server/worker";

export async function GET(req: Request, ctx: { params: Promise<{ kind: string }> }) {
  try {
    const kind = (await ctx.params).kind;
    if (!/^[a-z_]+$/.test(kind)) return Response.json({ error: "Unknown template" }, { status: 404 });
    const q = new URL(req.url).searchParams;
    const qs = new URLSearchParams();
    for (const k of ["period_start", "period_end"]) if (/^\d{4}-\d{2}/.test(q.get(k) ?? "")) qs.set(k, q.get(k)!.slice(0, 7));
    const r = await workerRaw(`/templates/${kind}?${qs}`);
    if (!r.ok) return Response.json({ error: "Template not available" }, { status: r.status });
    return new Response(r.body, {
      headers: { "Content-Type": r.headers.get("content-type") ?? "application/octet-stream", "Content-Disposition": r.headers.get("content-disposition") ?? "attachment" },
    });
  } catch (e) {
    return errorResponse(e);
  }
}
