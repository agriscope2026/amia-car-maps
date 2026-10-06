import { assertSameOrigin, errorResponse, HttpError, requireRole } from "@/lib/server/auth";
import { audit, createDraft } from "@/lib/server/repo";
import { verifyPayload } from "@/lib/server/worker";

/** Save a validated (signed) preview as a new draft version. */
export async function POST(req: Request) {
  try {
    await assertSameOrigin();
    const user = await requireRole("editor");
    const { payload, sig, uploadId, files, settings } = await req.json();
    if (!payload?.ok || typeof sig !== "string" || typeof uploadId !== "string" || !verifyPayload(payload, uploadId, sig))
      throw new HttpError(400, "Validate the upload again before saving (the preview is missing or was changed).");
    const v = await createDraft(payload, { ...(settings ?? {}), upload_id: uploadId, input_files: files ?? [] }, user);
    await audit(user, "create_draft", payload.type, v.id, { version: v.version, period: payload.period });
    return Response.json({ id: v.id, version: v.version });
  } catch (e) {
    return errorResponse(e);
  }
}
