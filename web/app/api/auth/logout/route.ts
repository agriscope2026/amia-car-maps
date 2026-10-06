import { assertSameOrigin, currentUser, errorResponse, logout } from "@/lib/server/auth";
import { audit } from "@/lib/server/repo";

export async function POST() {
  try {
    await assertSameOrigin();
    const u = await currentUser();
    await logout();
    if (u) await audit(u.email, "logout");
    return Response.json({ ok: true });
  } catch (e) {
    return errorResponse(e);
  }
}
