import { getCrops } from "@/lib/server/repo";
import { errorResponse } from "@/lib/server/auth";

export const dynamic = "force-dynamic";

export async function GET() {
  try {
    return Response.json(await getCrops(), { headers: { "Cache-Control": "public, s-maxage=300, stale-while-revalidate=3600" } });
  } catch (e) {
    return errorResponse(e);
  }
}
