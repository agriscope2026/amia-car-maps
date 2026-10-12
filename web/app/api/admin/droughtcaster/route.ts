import { assertSameOrigin, errorResponse, requireRole } from "@/lib/server/auth";
import { audit } from "@/lib/server/repo";
import { worker } from "@/lib/server/worker";

export const maxDuration = 120;

/** The CAR drought outlook from PAGASA DroughtCaster as a drought-template CSV, for the ENVI and drought upload
 * forms (the form then validates it like an uploaded file). */
export async function POST() {
  try {
    await assertSameOrigin();
    const user = await requireRole("editor");
    const res = await worker("/droughtcaster/table", { method: "POST" }, 110_000);
    await audit(user, "droughtcaster_fetch", "drought", undefined, { issued: res.issued, months: res.months });
    return Response.json(res);
  } catch (e) {
    return errorResponse(e);
  }
}
