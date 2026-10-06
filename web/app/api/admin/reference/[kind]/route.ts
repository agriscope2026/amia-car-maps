import { assertSameOrigin, errorResponse, HttpError, requireRole } from "@/lib/server/auth";
import { audit, saveCrops, saveIrrigation } from "@/lib/server/repo";
import { MAX_UPLOAD_BYTES, worker } from "@/lib/server/worker";

/** Admins maintain the crops table and the irrigation/dams layer. `?save=1` stores a valid upload. */
export async function POST(req: Request, ctx: { params: Promise<{ kind: string }> }) {
  try {
    await assertSameOrigin();
    const user = await requireRole("admin");
    const kind = (await ctx.params).kind;
    if (!["crops", "irrigation"].includes(kind)) throw new HttpError(404, "Unknown reference layer");
    const form = await req.formData();
    const file = form.get("file");
    if (!(file instanceof File) || !file.size) throw new HttpError(400, "Choose a file.");
    if (file.size > MAX_UPLOAD_BYTES) throw new HttpError(413, "File larger than 4 MB.");
    const fwd = new FormData();
    fwd.set("file", file, file.name);
    fwd.set("settings", String(form.get("settings") ?? "{}"));
    const res = await worker(`/reference/${kind}`, { method: "POST", body: fwd });
    const save = new URL(req.url).searchParams.get("save") === "1";
    if (save && res.ok) {
      if (kind === "crops")
        await saveCrops({ as_of: res.as_of, crops: res.crops, colors: res.colors, unit: "ha", values: res.values, totals: res.totals }, user);
      else await saveIrrigation(res.geojson, res.service_areas ?? null);
      await audit(user, "reference_update", kind, file.name, { counts: res.counts ?? res.totals });
    }
    return Response.json({ ...res, saved: save && res.ok });
  } catch (e) {
    return errorResponse(e);
  }
}
