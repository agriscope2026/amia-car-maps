import { z } from "zod";
import { promises as fs } from "fs";
import path from "path";
import { assertSameOrigin, errorResponse, HttpError, requireRole } from "@/lib/server/auth";
import { audit, getSetting, setSetting } from "@/lib/server/repo";
import type { Gazetteer } from "@/lib/types";

export const dynamic = "force-dynamic";

/** Staff: the rice / corn self-sufficiency (SSL) figures of the action plan's SSL map (app setting "ssl"). GET returns
 * them; PUT saves figures edited in the admin page (the next import of the workbook replaces them again). */
export async function GET() {
  try {
    await requireRole("editor");
    return Response.json({ ssl: (await getSetting("ssl")) ?? null });
  } catch (e) {
    return errorResponse(e);
  }
}

const num = (lo: number, hi: number) => z.number().finite().min(lo).max(hi).nullable();
const row = z.object({
  ssl: num(0, 100000), // %
  final_ssl: num(-100000, 100000), // % after the projected loss
  standing_ha: num(0, 1e7),
  yield_loss_mt: num(0, 1e8),
});
const crop = z.object({
  ssl_year: z.string().trim().max(10).regex(/^(\d{4})?$/, "The SSL year is a year, e.g. 2024."),
  standing_as_of: z.string().trim().max(40),
  provinces: z.record(z.string(), row),
});
const body = z.object({ crops: z.object({ rice: crop.optional(), corn: crop.optional() }) });

async function provinceLabels(): Promise<Map<string, string>> {
  const geo = JSON.parse(await fs.readFile(path.join(process.cwd(), "public", "geo", "car.json"), "utf-8")) as Gazetteer;
  return new Map(geo.gazetteer.map((g) => [g.province.toUpperCase(), g.province]));
}

export async function PUT(req: Request) {
  try {
    await assertSameOrigin();
    const user = await requireRole("editor");
    const parsed = body.safeParse(await req.json().catch(() => null));
    if (!parsed.success) {
      const i = parsed.error.issues[0];
      throw new HttpError(400, `${i?.path.join(" › ") || "SSL"}: ${i?.message ?? "invalid figures"}`);
    }
    const labels = await provinceLabels();
    const current = ((await getSetting("ssl")) ?? { file: "", sheet: "", crops: {} }) as Record<string, any>;
    const crops: Record<string, any> = { ...(current.crops ?? {}) };
    for (const [id, c] of Object.entries(parsed.data.crops)) {
      if (!c) continue;
      const before = crops[id] ?? { provinces: {}, car: null };
      const provinces: Record<string, any> = {};
      for (const [key, r] of Object.entries(c.provinces)) {
        if (!labels.has(key)) throw new HttpError(400, `Unknown province ${key}.`);
        const old = before.provinces?.[key] ?? {};
        const changed = old.ssl !== r.ssl || old.final_ssl !== r.final_ssl;
        provinces[key] = {
          ...old, // keeps the other figures of the workbook (harvested, target, production …)
          label: labels.get(key),
          ...r,
          // the reduction follows the two SSL figures; an Excel error message no longer applies once edited
          effect: r.ssl != null && r.final_ssl != null ? Math.round((r.ssl - r.final_ssl) * 10000) / 10000 : null,
          ...(changed ? { effect_error: undefined, adjusted_ssl: undefined } : {}),
        };
      }
      crops[id] = {
        ...before,
        ssl_year: c.ssl_year,
        standing_as_of: c.standing_as_of,
        provinces,
        ok: Object.values(provinces).some((p: any) => p.ssl != null),
      };
    }
    const saved = {
      ...current,
      crops,
      edited_at: new Date().toISOString(),
      edited_by: user.email,
    };
    await setSetting("ssl", saved);
    await audit(user, "ssl_edit", "ssl", undefined, { crops: Object.keys(parsed.data.crops) });
    return Response.json({ ssl: saved });
  } catch (e) {
    return errorResponse(e);
  }
}
