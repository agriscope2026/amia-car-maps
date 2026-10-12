import "server-only";
import { R2_BUCKET, R2_PUBLIC_BUCKET, r2Configured, r2Delete, r2DeletePrefix, r2List, type R2Object } from "./r2";
import { listVersions, type VersionRecord } from "./repo";
import { manifestFiles } from "./exports";

/**
 * Cloudflare R2 housekeeping. Files that nothing uses any more:
 *  - private `uploads/…`   raw inputs no version refers to (previews never saved, deleted versions);
 *  - private `exports/<version>/…` files of deleted versions, and files a regenerated export no longer lists;
 *  - public  `<version>/…` files of versions that are not published, or no longer listed in their export.
 * Recent files are never touched (a validation or export may be running), nor keys outside these patterns.
 */
const RECENT_HOURS = 24;
const VERSION_LIMIT = 200; // listVersions() returns at most this many: beyond it, files could look unused

export interface CleanupGroup {
  bucket: string;
  label: string;
  keepCount: number;
  keepBytes: number;
  remove: R2Object[];
  removeBytes: number;
}

export interface CleanupPlan {
  groups: CleanupGroup[];
  removeCount: number;
  removeBytes: number;
  versions: number;
  blocked?: string;
}

const recent = (o: R2Object, now: number) => !o.modified || now - Date.parse(o.modified) < RECENT_HOURS * 3_600_000;
const sum = (xs: R2Object[]) => xs.reduce((s, o) => s + o.size, 0);

/** Export files a version still uses: those in its current manifest; everything while an export is running. */
function liveExportFiles(v: VersionRecord): Set<string> | "all" {
  const ex = v.exports;
  if (!ex?.manifest || ex.pending_job) return "all";
  return new Set(manifestFiles(ex.manifest));
}

function group(bucket: string, label: string, objects: R2Object[], isUsed: (o: R2Object) => boolean, now: number): CleanupGroup {
  const remove = objects.filter((o) => !isUsed(o) && !recent(o, now));
  const keep = objects.filter((o) => !remove.includes(o));
  return { bucket, label, keepCount: keep.length, keepBytes: sum(keep), remove, removeBytes: sum(remove) };
}

export async function planCleanup(now = Date.now()): Promise<CleanupPlan> {
  if (!r2Configured()) return { groups: [], removeCount: 0, removeBytes: 0, versions: 0, blocked: "Cloudflare R2 is not configured." };
  const versions = await listVersions();
  if (versions.length >= VERSION_LIMIT)
    return { groups: [], removeCount: 0, removeBytes: 0, versions: versions.length,
      blocked: `There are ${VERSION_LIMIT} or more versions; delete old versions in the admin first so none are missed.` };
  const byId = new Map(versions.map((v) => [v.id, v]));
  const uploads = new Set(versions.flatMap((v) => (v.settings?.input_files ?? []).map((f: { path: string }) => `uploads/${f.path}`)));

  const priv = await r2List(R2_BUCKET);
  const pub = await r2List(R2_PUBLIC_BUCKET);

  const upObjs = priv.filter((o) => o.key.startsWith("uploads/"));
  const exObjs = priv.filter((o) => o.key.startsWith("exports/"));
  const groups = [
    group(R2_BUCKET, "Uploaded input files", upObjs, (o) => uploads.has(o.key), now),
    group(R2_BUCKET, "Export files (drafts and published)", exObjs, (o) => {
      const [, id, ...rest] = o.key.split("/");
      const v = byId.get(id);
      if (!v) return false; // version deleted
      const live = liveExportFiles(v);
      return live === "all" || live.has(rest.join("/")) || o.key.endsWith(".json");
    }, now),
    group(R2_PUBLIC_BUCKET, "Published files (public bucket)", pub, (o) => {
      const [id, ...rest] = o.key.split("/");
      const v = byId.get(id);
      if (!v) return false;
      if (v.status !== "published") return Boolean(v.exports?.pending_job); // unpublished: no longer public
      const live = liveExportFiles(v);
      return live === "all" || live.has(rest.join("/"));
    }, now),
  ];
  const removeCount = groups.reduce((s, g) => s + g.remove.length, 0);
  const removeBytes = groups.reduce((s, g) => s + g.removeBytes, 0);
  return { groups, removeCount, removeBytes, versions: versions.length };
}

/** Delete what planCleanup() found unused. Returns what was removed. */
export async function runCleanup(): Promise<{ deleted: number; bytes: number }> {
  const plan = await planCleanup();
  if (plan.blocked) throw new Error(plan.blocked);
  for (const g of plan.groups) for (const o of g.remove) await r2Delete(g.bucket, o.key);
  return { deleted: plan.removeCount, bytes: plan.removeBytes };
}

/** After an export was regenerated: drop the version's files the new export no longer lists (both buckets). */
export async function pruneVersionFiles(versionId: string, manifest: any, published: boolean): Promise<number> {
  if (!r2Configured() || !manifest) return 0;
  const live = new Set(manifestFiles(manifest));
  let n = 0;
  for (const o of await r2List(R2_BUCKET, `exports/${versionId}/`)) {
    const name = o.key.slice(`exports/${versionId}/`.length);
    if (!live.has(name) && !name.endsWith(".json")) (await r2Delete(R2_BUCKET, o.key), n++);
  }
  for (const o of await r2List(R2_PUBLIC_BUCKET, `${versionId}/`)) {
    const name = o.key.slice(`${versionId}/`.length);
    if (!published || !live.has(name)) (await r2Delete(R2_PUBLIC_BUCKET, o.key), n++);
  }
  return n;
}

/** A deleted version's files: its exports, its public copies, and the uploads no other version uses. */
export async function removeVersionFiles(v: VersionRecord): Promise<void> {
  if (!r2Configured()) return;
  await r2DeletePrefix(R2_BUCKET, `exports/${v.id}/`);
  await r2DeletePrefix(R2_PUBLIC_BUCKET, `${v.id}/`);
  const others = new Set(
    (await listVersions()).filter((x) => x.id !== v.id).flatMap((x) => (x.settings?.input_files ?? []).map((f: { path: string }) => f.path)),
  );
  for (const f of v.settings?.input_files ?? []) if (!others.has(f.path)) await r2Delete(R2_BUCKET, `uploads/${f.path}`);
}
