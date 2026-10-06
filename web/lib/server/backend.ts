import "server-only";
import { supabaseConfigured } from "./supabase";

/**
 * Which data back end the server uses:
 *  - "supabase": NEXT_PUBLIC_SUPABASE_URL + keys (production on Vercel)
 *  - "postgres": DATABASE_URL (local development database, or a self-hosted PostgreSQL + PostGIS)
 *  - "file":     neither – bundled demo data + web/.data/db.json (quick look, no database)
 */
export type BackendKind = "supabase" | "postgres" | "file";

export function backendKind(): BackendKind {
  if (supabaseConfigured()) return "supabase";
  if (process.env.DATABASE_URL) return "postgres";
  return "file";
}
