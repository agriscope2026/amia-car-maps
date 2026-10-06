import "server-only";
import { promises as fs } from "fs";
import path from "path";
import type { Download } from "@/lib/types";
import { LOCAL_EXPORTS_DIR } from "./repo";
import { R2_BUCKET, R2_PUBLIC_BUCKET, r2Configured, r2Copy, r2PublicUrl } from "./r2";
import { supabaseAdmin, supabaseConfigured } from "./supabase";
import { workerRaw } from "./worker";

/** Manifest → download list. `href(name)` gives the URL of one export file. */
/** Per-map files in the worker manifest: [kind, label, preview-only]. Previews feed photo mode, not downloads. */
export const MAP_FILES: [string, string, boolean][] = [
  ["png", "Map – PNG (400 dpi)", false],
  ["pdf", "Map – PDF", false],
  ["presentation", "Presentation – PNG (5760×3240)", false],
  ["presentation_pdf", "Presentation – PDF", false],
  ["poster", "A4 poster – PNG (450 dpi)", false],
  ["poster_pdf", "A4 poster – PDF", false],
  ["jpg", "Map preview", true],
  ["presentation_web", "Presentation preview", true],
  ["poster_web", "Poster preview", true],
];

/** Every file name a manifest refers to (to copy or publish them). */
export function manifestFiles(m: any): string[] {
  const maps = (m.maps ?? []).flatMap((mp: any) => MAP_FILES.map(([k]) => mp[k]).filter(Boolean));
  return [...new Set([...maps, ...(Object.values(m.files ?? {}) as string[])])];
}

/** Manifest → download list: per map its PNG and PDF (ENVI: presentation + poster), then one ZIP of all maps. */
export function downloadsFromManifest(m: any, href: (file: string) => string): Download[] {
  const out: Download[] = [];
  for (const mp of m.maps ?? []) {
    for (const [k, label, preview] of MAP_FILES)
      if (mp[k]) out.push({ label, url: href(mp[k]), alt: mp.alt, group: mp.label, layer: mp.layer, kind: k, preview });
  }
  if (m.files?.zip) out.push({ label: "All maps – PNG and PDF (ZIP)", url: href(m.files.zip), group: "Whole product", kind: "zip" });
  return out;
}

/** Local mode: copy a finished job's files from the worker into web/.data/exports/<version>/. */
export async function pullJobFiles(jobId: string, versionId: string, manifest: any) {
  const names = manifestFiles(manifest);
  const dir = path.join(LOCAL_EXPORTS_DIR, versionId);
  await fs.mkdir(dir, { recursive: true });
  for (const n of names) {
    const r = await workerRaw(`/jobs/${jobId}/files/${encodeURIComponent(n)}`);
    if (!r.ok) throw new Error(`Could not fetch ${n} from the worker (${r.status})`);
    await fs.writeFile(path.join(dir, path.basename(n)), Buffer.from(await r.arrayBuffer()));
  }
}

export const localExportUrl = (versionId: string) => (file: string) => `/api/exports/${versionId}/${encodeURIComponent(file)}`;

/** Supabase mode: on publish, copy the exports from the private bucket to the public one. */
export async function publishSupabaseExports(versionId: string, manifest: any): Promise<Download[]> {
  const names = manifestFiles(manifest);
  if (r2Configured()) {
    // Cloudflare R2: server-side copy from the private bucket to the public one
    for (const n of names) await r2Copy(R2_BUCKET, `exports/${versionId}/${n}`, R2_PUBLIC_BUCKET, `${versionId}/${n}`);
    return downloadsFromManifest(manifest, (f) => r2PublicUrl(`${versionId}/${f}`));
  }
  const sb = supabaseAdmin();
  for (const n of names) {
    const { data, error } = await sb.storage.from("exports").download(`${versionId}/${n}`);
    if (error) throw error;
    const up = await sb.storage.from("public-exports").upload(`${versionId}/${n}`, data, { upsert: true, contentType: data.type });
    if (up.error) throw up.error;
  }
  return downloadsFromManifest(manifest, (f) => sb.storage.from("public-exports").getPublicUrl(`${versionId}/${f}`).data.publicUrl);
}

export { supabaseConfigured };
