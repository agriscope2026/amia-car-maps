import "server-only";
import crypto from "crypto";
import { cookies, headers } from "next/headers";
import { createServerClient } from "@supabase/ssr";
import { ANON, supabaseAdmin, supabaseConfigured } from "./supabase";
import { backendKind } from "./backend";
import { q } from "./db";
import { verifyPassword } from "./password";

export type Role = "editor" | "admin";
export interface User {
  id: string;
  email: string;
  role: Role;
}

const SESSION_COOKIE = "car_session";
const SESSION_TTL_S = 8 * 3600;

export class HttpError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

// ------------------------------------------------- session cookie auth ---
// Used by the PostgreSQL back end (users in auth.users with scrypt hashes, roles in profiles) and by the
// file back end (one admin from DEV_ADMIN_EMAIL / DEV_ADMIN_PASSWORD, refused in production).
// The session is an HMAC-signed, httpOnly, SameSite=Strict cookie; Supabase mode uses Supabase Auth instead.

function secret() {
  const s = process.env.SESSION_SECRET ?? "";
  if (s.length < 32) throw new HttpError(500, "SESSION_SECRET must be at least 32 characters.");
  return s;
}

function sign(data: string) {
  return crypto.createHmac("sha256", secret()).update(data).digest("base64url");
}

export function localAuthAllowed() {
  return backendKind() === "file" && (process.env.NODE_ENV !== "production" || process.env.ALLOW_LOCAL_ADMIN === "1");
}

function safeEqual(a: string, b: string) {
  const ha = crypto.createHash("sha256").update(a).digest();
  const hb = crypto.createHash("sha256").update(b).digest();
  return crypto.timingSafeEqual(ha, hb);
}

async function setSession(user: User) {
  const body = Buffer.from(JSON.stringify({ ...user, exp: Math.floor(Date.now() / 1000) + SESSION_TTL_S })).toString("base64url");
  (await cookies()).set(SESSION_COOKIE, `${body}.${sign(body)}`, {
    httpOnly: true,
    sameSite: "strict",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: SESSION_TTL_S,
  });
}

/** Email + password sign-in for the PostgreSQL and file back ends. Returns null on a wrong login. */
export async function passwordLogin(email: string, password: string): Promise<User | null> {
  const mail = email.trim().toLowerCase();
  let user: User | null = null;
  if (backendKind() === "postgres") {
    const [r] = await q(
      `select u.id, u.email, u.encrypted_password, p.role, p.active
       from auth.users u join profiles p on p.id = u.id where lower(u.email) = $1`,
      [mail],
    );
    const ok = verifyPassword(password, r?.encrypted_password);
    if (ok && r.active) user = { id: r.id, email: r.email, role: r.role };
  } else if (localAuthAllowed()) {
    const e = process.env.DEV_ADMIN_EMAIL ?? "";
    const p = process.env.DEV_ADMIN_PASSWORD ?? "";
    if (!e || !p) throw new HttpError(500, "Set DEV_ADMIN_EMAIL and DEV_ADMIN_PASSWORD in web/.env.local.");
    if (safeEqual(mail, e.toLowerCase()) && safeEqual(password, p)) user = { id: "local-admin", email: e, role: "admin" };
  }
  if (user) await setSession(user);
  return user;
}

async function sessionUser(): Promise<User | null> {
  const raw = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!raw) return null;
  const [body, sig] = raw.split(".");
  if (!body || !sig || !safeEqual(sig, sign(body))) return null;
  const s = JSON.parse(Buffer.from(body, "base64url").toString());
  if (s.exp < Date.now() / 1000) return null;
  if (backendKind() === "postgres") {
    // re-read role and active flag so changes take effect immediately
    const [p] = await q(`select role, active from profiles where id = $1`, [s.id]);
    if (!p?.active) return null;
    return { id: s.id, email: s.email, role: p.role };
  }
  return { id: s.id, email: s.email, role: s.role };
}

// -------------------------------------------------------------- Supabase ---

export async function supabaseServer() {
  const store = await cookies();
  return createServerClient(process.env.NEXT_PUBLIC_SUPABASE_URL!, ANON, {
    cookies: {
      getAll: () => store.getAll(),
      setAll: (list) => {
        try {
          for (const { name, value, options } of list) store.set(name, value, { ...options, sameSite: "lax", httpOnly: true });
        } catch {
          /* called from a server component: cookies are read-only there */
        }
      },
    },
  });
}

export async function currentUser(): Promise<User | null> {
  const kind = backendKind();
  if (kind === "postgres") return sessionUser();
  if (kind === "file") return localAuthAllowed() ? sessionUser() : null;
  const sb = await supabaseServer();
  const { data } = await sb.auth.getUser();
  if (!data.user) return null;
  const { data: profile } = await supabaseAdmin()
    .from("profiles")
    .select("role, active")
    .eq("id", data.user.id)
    .maybeSingle();
  if (!profile?.active) return null;
  return { id: data.user.id, email: data.user.email ?? "", role: profile.role as Role };
}

export async function logout() {
  if (supabaseConfigured()) await (await supabaseServer()).auth.signOut();
  (await cookies()).delete(SESSION_COOKIE);
}

/** Server-side role check for every admin API. Admin implies editor. */
export async function requireRole(role: Role): Promise<User> {
  const u = await currentUser();
  if (!u) throw new HttpError(401, "Please sign in.");
  if (role === "admin" && u.role !== "admin") throw new HttpError(403, "Only admins can do this.");
  return u;
}

/** CSRF defence for cookie-authenticated mutations: the request must come from our own origin. */
export async function assertSameOrigin() {
  const h = await headers();
  const origin = h.get("origin");
  const host = h.get("x-forwarded-host") ?? h.get("host");
  if (!origin || !host || new URL(origin).host !== host) throw new HttpError(403, "Cross-site request refused.");
}

export function errorResponse(e: unknown) {
  const status = e instanceof HttpError ? e.status : 500;
  // Supabase/PostgREST errors are plain objects ({ message, details, hint, code }), not Error instances
  const o = (e && typeof e === "object" ? e : {}) as { message?: unknown; details?: unknown; hint?: unknown; code?: unknown };
  const message =
    e instanceof Error
      ? e.message
      : typeof o.message === "string"
        ? [o.message, o.details, o.hint].filter((x) => typeof x === "string" && x).join(" – ") + (o.code ? ` (${o.code})` : "")
        : "Unexpected error";
  if (status === 500) console.error(e);
  return Response.json({ error: message }, { status });
}
