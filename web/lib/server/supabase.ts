import "server-only";
import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const URL = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const ANON = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";
const SERVICE = process.env.SUPABASE_SERVICE_ROLE_KEY ?? "";

export const supabaseConfigured = () => Boolean(URL && ANON && SERVICE);

let pub: SupabaseClient | null = null;
let admin: SupabaseClient | null = null;

/** Anonymous client: RLS limits it to published products and reference data. */
export function supabasePublic(): SupabaseClient {
  pub ??= createClient(URL, ANON, { auth: { persistSession: false } });
  return pub;
}

/** Service-role client. Only call after `requireRole()` has checked the user server-side. */
export function supabaseAdmin(): SupabaseClient {
  admin ??= createClient(URL, SERVICE, { auth: { persistSession: false } });
  return admin;
}
