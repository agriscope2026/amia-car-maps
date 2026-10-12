import { assertSameOrigin, errorResponse, requireRole } from "@/lib/server/auth";
import { audit } from "@/lib/server/repo";
import { planCleanup, runCleanup } from "@/lib/server/storage-cleanup";

export const dynamic = "force-dynamic";
export const maxDuration = 300;

/** Storage cleanup (admins): GET = what is unused in Cloudflare R2 (nothing is deleted), POST = delete it. */
export async function GET() {
  try {
    await requireRole("admin");
    const p = await planCleanup();
    return Response.json({
      ...p,
      // a sample of the file names per group (the full lists can be long)
      groups: p.groups.map((g) => ({ ...g, remove: g.remove.slice(0, 50), removeTotal: g.remove.length })),
    });
  } catch (e) {
    return errorResponse(e);
  }
}

export async function POST() {
  try {
    await assertSameOrigin();
    const user = await requireRole("admin");
    const r = await runCleanup();
    await audit(user, "storage_cleanup", "storage", undefined, r);
    return Response.json(r);
  } catch (e) {
    return errorResponse(e);
  }
}
