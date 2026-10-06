import "server-only";
import path from "path";
import type { CropsLayer, Payload } from "@/lib/types";
import { backendKind } from "../backend";
import { fileRepo } from "./file";
import { postgresRepo } from "./postgres";
import { supabaseRepo } from "./supabase";
import type { Actor, DraftPatch, Repo } from "./types";
import { withColors } from "@/lib/crops";

export type { Actor, AuditEntry, VersionRecord } from "./types";
export { slugFor } from "./types";

/** Data access – the back end is chosen from the environment (see lib/server/backend.ts). */
function repo(): Repo {
  const k = backendKind();
  return k === "supabase" ? supabaseRepo : k === "postgres" ? postgresRepo : fileRepo;
}

const actorOf = (a: Actor | string): Actor => (typeof a === "string" ? { email: a } : a);

export const listPublished = () => repo().listPublished();
export const getPublishedPayload = (id: string) => repo().getPublishedPayload(id);
export const getCrops = async () => withColors(await repo().getCrops());
export const setCropColors = (colors: Record<string, string>) => repo().setCropColors(colors);
export const getIrrigation = () => repo().getIrrigation();
export const listVersions = () => repo().listVersions();
export const getVersion = (id: string) => repo().getVersion(id);
export const createDraft = (payload: Payload, settings: Record<string, any>, actor: Actor | string) =>
  repo().createDraft(payload, settings, actorOf(actor));
export const updateDraft = (id: string, patch: DraftPatch, allowPublished = false) =>
  repo().updateDraft(id, patch, allowPublished);
export const publish = (id: string, actor: Actor | string) => repo().publish(id, actorOf(actor));
export const unpublish = (id: string) => repo().unpublish(id);
export const deleteVersion = (id: string) => repo().deleteVersion(id);
export const saveCrops = (c: CropsLayer, actor: Actor | string) => repo().saveCrops(c, actorOf(actor));
export const saveIrrigation = (fc: any, serviceAreas: any | null) => repo().saveIrrigation(fc, serviceAreas);
export const audit = (actor: Actor | string, action: string, entity?: string, entity_id?: string, details?: any) =>
  repo().audit(actorOf(actor), action, entity, entity_id, details);
export const listAudit = (limit = 200) => repo().listAudit(limit);

/** Export files of local/postgres mode live here (Supabase mode uses Storage). */
export const LOCAL_EXPORTS_DIR = path.join(process.cwd(), ".data", "exports");
