import { assertSameOrigin, errorResponse, HttpError, requireRole } from "@/lib/server/auth";
import { audit, getCrops, setCropColors } from "@/lib/server/repo";

/** Admins choose the colour of each crop (dashboard overlay + crop circles on exported maps). */
export async function POST(req: Request) {
  try {
    await assertSameOrigin();
    const user = await requireRole("admin");
    const { colors } = await req.json();
    const crops = (await getCrops())?.crops ?? [];
    if (!colors || typeof colors !== "object") throw new HttpError(400, "colors is required");
    const clean: Record<string, string> = {};
    for (const [crop, color] of Object.entries(colors)) {
      if (!crops.includes(crop)) throw new HttpError(400, `Unknown crop: ${crop}`);
      if (typeof color !== "string" || !/^#[0-9a-f]{6}$/i.test(color)) throw new HttpError(400, `Invalid colour for ${crop}`);
      clean[crop] = color.toLowerCase();
    }
    await setCropColors(clean);
    await audit(user, "crop_colors", "crops", undefined, clean);
    return Response.json({ ok: true, colors: (await getCrops())?.colors });
  } catch (e) {
    return errorResponse(e);
  }
}
