import crypto from "crypto";
import { assertSameOrigin, errorResponse, HttpError, requireRole } from "@/lib/server/auth";
import { audit } from "@/lib/server/repo";
import { signPayload, worker } from "@/lib/server/worker";

export const maxDuration = 300;

/** Automatic sources: 10-day rainfall feed, and PAGASA's seasonal forecast (read from its published tables). */
const SOURCES: Record<string, string> = {
  rainfall_dekad: "/feeds/rainfall_dekad/fetch",
  rainfall_seasonal: "/feeds/rainfall_seasonal/fetch",
};

/** Fetch the latest forecast from an automatic source and return it as a signed preview (a draft-to-be). */
export async function POST(req: Request) {
  try {
    await assertSameOrigin();
    const user = await requireRole("editor");
    const body = await req.json().catch(() => ({}));
    const type = typeof body.type === "string" ? body.type : "rainfall_dekad";
    const path = SOURCES[type];
    if (!path) throw new HttpError(400, "Unknown source");
    const res = await worker(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }, 280_000);
    const uploadId = crypto.randomUUID();
    await audit(user, "feed_fetch", type, uploadId, { ok: res.ok, error: res.error, period: res.payload?.period });
    if (!res.payload) return Response.json({ error: res.error ?? "Fetch failed", state: res.state }, { status: 502 });
    return Response.json({
      payload: res.payload,
      uploadId,
      files: [],
      sig: res.payload.ok ? signPayload(res.payload, uploadId) : null,
      state: res.state,
    });
  } catch (e) {
    return errorResponse(e);
  }
}
