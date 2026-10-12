import "server-only";
import { AwsClient } from "aws4fetch";

/**
 * Cloudflare R2 (S3-compatible) file storage – used instead of Supabase Storage when the R2_* variables are set.
 *  - R2_BUCKET (private): `uploads/<upload>/<file>` (raw inputs) and `exports/<version>/<file>` (draft exports)
 *  - R2_PUBLIC_BUCKET (public access on, served at R2_PUBLIC_URL): `<version>/<file>` (published exports)
 */
const ACCOUNT = process.env.R2_ACCOUNT_ID ?? "";
const KEY_ID = process.env.R2_ACCESS_KEY_ID ?? "";
const SECRET = process.env.R2_SECRET_ACCESS_KEY ?? "";
export const R2_BUCKET = process.env.R2_BUCKET || "amia-car-maps";
export const R2_PUBLIC_BUCKET = process.env.R2_PUBLIC_BUCKET || "amia-car-maps-public";
const PUBLIC_URL = (process.env.R2_PUBLIC_URL ?? "").replace(/\/+$/, "");

export const r2Configured = () => Boolean(ACCOUNT && KEY_ID && SECRET);

let client: AwsClient | null = null;
const aws = () => (client ??= new AwsClient({ accessKeyId: KEY_ID, secretAccessKey: SECRET, service: "s3", region: "auto" }));
const endpoint = () => `https://${ACCOUNT}.r2.cloudflarestorage.com`;
const objUrl = (bucket: string, key: string) =>
  `${endpoint()}/${bucket}/${key.split("/").map(encodeURIComponent).join("/")}`;

async function check(r: Response, what: string) {
  if (!r.ok) throw new Error(`R2 ${what} failed (${r.status}): ${(await r.text()).slice(0, 300)}`);
  return r;
}

export async function r2Put(bucket: string, key: string, body: BodyInit, contentType?: string) {
  await check(await aws().fetch(objUrl(bucket, key), {
    method: "PUT", body, headers: contentType ? { "Content-Type": contentType } : {},
  }), `upload of ${key}`);
}

export async function r2Get(bucket: string, key: string): Promise<Blob> {
  const r = await check(await aws().fetch(objUrl(bucket, key)), `download of ${key}`);
  return r.blob();
}

/** Server-side copy (no download/upload through the web app). Both buckets must be in the same account. */
export async function r2Copy(srcBucket: string, srcKey: string, dstBucket: string, dstKey: string) {
  await check(await aws().fetch(objUrl(dstBucket, dstKey), {
    method: "PUT", headers: { "x-amz-copy-source": `/${srcBucket}/${srcKey.split("/").map(encodeURIComponent).join("/")}` },
  }), `copy of ${srcKey}`);
}

/** Short-lived download link for a private object. */
export async function r2SignedUrl(bucket: string, key: string, seconds = 300, downloadName?: string) {
  const u = new URL(objUrl(bucket, key));
  u.searchParams.set("X-Amz-Expires", String(seconds));
  if (downloadName) u.searchParams.set("response-content-disposition", `attachment; filename="${downloadName}"`);
  const signed = await aws().sign(u.toString(), { method: "GET", aws: { signQuery: true } });
  return signed.url;
}

/**
 * Published files are linked straight to the public bucket only on a custom domain. Cloudflare's shared `*.r2.dev`
 * address is blocked by some ISPs, office firewalls and DNS filters (it is often abused for phishing) and is
 * rate-limited, so without a custom domain the files are served through the app (/api/exports/…) instead.
 */
export function r2DirectPublic(): boolean {
  if (!PUBLIC_URL) return false;
  try {
    return !new URL(PUBLIC_URL).hostname.toLowerCase().endsWith(".r2.dev");
  } catch {
    return false;
  }
}

/** Saved download links that point to an `r2.dev` address → the app's own file route (no re-publish needed). */
export function servedThroughApp<T extends { url?: string }>(versionId: string, downloads: T[] | undefined): T[] | undefined {
  if (!downloads || r2DirectPublic()) return downloads;
  return downloads.map((d) => {
    try {
      const u = d.url ? new URL(d.url) : null;
      if (!u || !u.hostname.toLowerCase().endsWith(".r2.dev")) return d;
      const name = decodeURIComponent(u.pathname.split("/").pop() ?? "");
      return { ...d, url: `/api/exports/${versionId}/${encodeURIComponent(name)}` };
    } catch {
      return d;
    }
  });
}

export function r2PublicUrl(key: string) {
  if (!PUBLIC_URL) throw new Error("Set R2_PUBLIC_URL (the public bucket's r2.dev or custom-domain URL).");
  return `${PUBLIC_URL}/${key.split("/").map(encodeURIComponent).join("/")}`;
}

export interface R2Object {
  key: string;
  size: number;
  modified: string; // ISO date
}

/** Every object under a prefix (the whole bucket with prefix ""), following continuation pages. */
export async function r2List(bucket: string, prefix = ""): Promise<R2Object[]> {
  const out: R2Object[] = [];
  let token = "";
  do {
    const u = new URL(`${endpoint()}/${bucket}`);
    u.searchParams.set("list-type", "2");
    if (prefix) u.searchParams.set("prefix", prefix);
    if (token) u.searchParams.set("continuation-token", token);
    const xml = await (await check(await aws().fetch(u.toString()), `listing of ${bucket}/${prefix}`)).text();
    for (const m of xml.matchAll(/<Contents>([\s\S]*?)<\/Contents>/g)) {
      const c = m[1];
      out.push({
        key: decodeXml(c.match(/<Key>([^<]+)<\/Key>/)?.[1] ?? ""),
        size: Number(c.match(/<Size>(\d+)<\/Size>/)?.[1] ?? 0),
        modified: c.match(/<LastModified>([^<]+)<\/LastModified>/)?.[1] ?? "",
      });
    }
    token = /<IsTruncated>true<\/IsTruncated>/.test(xml) ? decodeXml(xml.match(/<NextContinuationToken>([^<]+)</)?.[1] ?? "") : "";
  } while (token);
  return out.filter((o) => o.key);
}

export async function r2Delete(bucket: string, key: string) {
  await check(await aws().fetch(objUrl(bucket, key), { method: "DELETE" }), `delete of ${key}`);
}

/** Delete every object under a prefix. */
export async function r2DeletePrefix(bucket: string, prefix: string) {
  for (const o of await r2List(bucket, prefix)) await r2Delete(bucket, o.key);
}

const decodeXml = (s: string) =>
  s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&amp;/g, "&");
