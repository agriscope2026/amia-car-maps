import { listPublished } from "@/lib/server/repo";
import { errorResponse } from "@/lib/server/auth";

export const dynamic = "force-dynamic";
const CACHE = { "Cache-Control": "public, s-maxage=60, stale-while-revalidate=600" };

export async function GET() {
  try {
    return Response.json({ products: await listPublished() }, { headers: CACHE });
  } catch (e) {
    return errorResponse(e);
  }
}
