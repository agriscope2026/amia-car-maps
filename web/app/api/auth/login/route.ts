import { assertSameOrigin, errorResponse, HttpError, passwordLogin, supabaseServer } from "@/lib/server/auth";
import { supabaseConfigured } from "@/lib/server/supabase";
import { audit } from "@/lib/server/repo";
import { rateLimit } from "@/lib/server/ratelimit";

export async function POST(req: Request) {
  try {
    await assertSameOrigin();
    rateLimit(`login:${req.headers.get("x-forwarded-for") ?? "local"}`, 8, 10 * 60_000);
    const { email, password } = await req.json();
    if (typeof email !== "string" || typeof password !== "string") throw new HttpError(400, "Email and password are required.");
    if (supabaseConfigured()) {
      const { error } = await (await supabaseServer()).auth.signInWithPassword({ email, password });
      if (error) {
        await audit(email, "login_failed");
        throw new HttpError(401, "Wrong email or password.");
      }
    } else {
      const u = await passwordLogin(email, password);
      if (!u) {
        await audit(email, "login_failed");
        throw new HttpError(401, "Wrong email or password.");
      }
    }
    await audit(email, "login");
    return Response.json({ ok: true });
  } catch (e) {
    return errorResponse(e);
  }
}
