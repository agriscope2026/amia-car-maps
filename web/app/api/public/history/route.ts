import { getPublishedPayload, listPublished } from "@/lib/server/repo";
import { errorResponse, HttpError } from "@/lib/server/auth";
import { SUMMARY_LAYER, summaryPoint, type TrendPoint } from "@/lib/insights";
import { sortIssues } from "@/lib/format";
import type { Payload, ProductType } from "@/lib/types";

export const dynamic = "force-dynamic";

const MAX_ISSUES = 8;
// one published version never changes, so its per-area summary values are cached by id + version
const cache = new Map<string, Payload>();

async function payloadOf(id: string, version: number): Promise<Payload | null> {
  const key = `${id}:${version}`;
  if (!cache.has(key)) {
    const p = await getPublishedPayload(id);
    if (!p) return null;
    if (cache.size > 200) cache.clear();
    cache.set(key, p);
  }
  return cache.get(key)!;
}

/** An area's ENVI value, 10-day rainfall total and season rainfall total over the last published issues
 * (oldest first): GET /api/public/history?area=KALINGA|CITY%20OF%20TABUK */
export async function GET(req: Request) {
  try {
    const area = new URL(req.url).searchParams.get("area") ?? "";
    if (!area || area.length > 80) throw new HttpError(400, "area is required");
    const catalog = await listPublished();
    const series: Partial<Record<ProductType, TrendPoint[]>> = {};
    for (const type of Object.keys(SUMMARY_LAYER) as ProductType[]) {
      const issues = sortIssues(catalog.filter((p) => p.type === type)).slice(0, MAX_ISSUES).reverse();
      const pts: TrendPoint[] = [];
      for (const e of issues) {
        const p = await payloadOf(e.id, e.version);
        const pt = p && summaryPoint(p, area);
        if (pt) pts.push({ id: e.id, ...pt });
      }
      series[type] = pts;
    }
    return Response.json({ area, series }, { headers: { "Cache-Control": "public, s-maxage=300, stale-while-revalidate=3600" } });
  } catch (e) {
    return errorResponse(e);
  }
}
