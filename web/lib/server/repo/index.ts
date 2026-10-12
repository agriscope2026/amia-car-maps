import "server-only";
import path from "path";
import type { CropsLayer, Payload } from "@/lib/types";
import { backendKind } from "../backend";
import { fileRepo } from "./file";
import { postgresRepo } from "./postgres";
import { supabaseRepo } from "./supabase";
import type { Actor, DraftPatch, Repo } from "./types";
import { withColors } from "@/lib/crops";
import { servedThroughApp } from "../r2";

export type { Actor, AuditEntry, VersionRecord } from "./types";
export { slugFor } from "./types";

/** Data access – the back end is chosen from the environment (see lib/server/backend.ts). */
function repo(): Repo {
  const k = backendKind();
  return k === "supabase" ? supabaseRepo : k === "postgres" ? postgresRepo : fileRepo;
}

const actorOf = (a: Actor | string): Actor => (typeof a === "string" ? { email: a } : a);

export const listPublished = () => repo().listPublished();
/** Download links saved with an r2.dev address are served through the app instead (see r2DirectPublic). */
export const getPublishedPayload = async (id: string) => {
  const p = await repo().getPublishedPayload(id);
  return p ? { ...p, downloads: servedThroughApp(id, p.downloads) } : p;
};
export const getCrops = async () => withColors(await repo().getCrops());
export const setCropColors = (colors: Record<string, string>) => repo().setCropColors(colors);
export const getIrrigation = () => repo().getIrrigation();
export const listVersions = () => repo().listVersions();
export const getVersion = async (id: string) => {
  const v = await repo().getVersion(id);
  return v?.exports?.downloads ? { ...v, exports: { ...v.exports, downloads: servedThroughApp(id, v.exports.downloads) } } : v;
};
export const createDraft = (payload: Payload, settings: Record<string, any>, actor: Actor | string) =>
  repo().createDraft(payload, settings, actorOf(actor));
export const updateDraft = (id: string, patch: DraftPatch, allowPublished = false) =>
  repo().updateDraft(id, patch, allowPublished);
export const publish = (id: string, actor: Actor | string) => repo().publish(id, actorOf(actor));
export const unpublish = (id: string) => repo().unpublish(id);
/** Delete a version and, on Cloudflare R2, its export files and the uploads no other version uses. */
export async function deleteVersion(id: string) {
  const v = await repo().getVersion(id);
  await repo().deleteVersion(id);
  if (v) {
    const { removeVersionFiles } = await import("../storage-cleanup");
    await removeVersionFiles(v).catch((e) => console.error(`storage cleanup of version ${id} failed:`, e));
  }
}
export const saveCrops = (c: CropsLayer, actor: Actor | string) => repo().saveCrops(c, actorOf(actor));
export const saveIrrigation = (fc: any, serviceAreas: any | null) => repo().saveIrrigation(fc, serviceAreas);
export const audit = (actor: Actor | string, action: string, entity?: string, entity_id?: string, details?: any) =>
  repo().audit(actorOf(actor), action, entity, entity_id, details);
export const listAudit = (limit = 200) => repo().listAudit(limit);

/** Export files of local/postgres mode live here (Supabase mode uses Storage). */
export const LOCAL_EXPORTS_DIR = path.join(process.cwd(), ".data", "exports");
