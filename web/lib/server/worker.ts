import "server-only";
import crypto from "crypto";
import { promises as fs } from "fs";
import path from "path";
import { HttpError } from "./auth";
import { supabaseAdmin, supabaseConfigured } from "./supabase";

/** Client for the private render worker + storage of uploaded input files. */

const WORKER_URL = (process.env.WORKER_URL ?? "http://127.0.0.1:8001").replace(/\/$/, "");
const WORKER_TOKEN = process.env.WORKER_TOKEN ?? "";
const DATA_DIR = path.join(process.cwd(), ".data");

export async function worker(pathname: string, init: RequestInit = {}, timeoutMs = 120_000): Promise<any> {
  let res: Response;
  try {
    res = await fetch(`${WORKER_URL}${pathname}`, {
      ...init,
      headers: { ...(init.headers ?? {}), Authorization: `Bearer ${WORKER_TOKEN}` },
      signal: AbortSignal.timeout(timeoutMs),
      cache: "no-store",
    });
  } catch (e) {
    throw new HttpError(502, `The render worker is not reachable at ${WORKER_URL} (${(e as Error).message}).`);
  }
  if (!res.ok) {
    let msg = `Worker error ${res.status}`;
    try {
      msg = (await res.json()).detail ?? msg;
    } catch {}
    throw new HttpError(res.status === 401 ? 502 : res.status, String(msg));
  }
  return res.headers.get("content-type")?.includes("json") ? res.json() : res;
}

export async function workerRaw(pathname: string): Promise<Response> {
  return fetch(`${WORKER_URL}${pathname}`, { headers: { Authorization: `Bearer ${WORKER_TOKEN}` }, cache: "no-store" });
}

// ------------------------------------------------- signed preview tokens ---
// The preview payload travels through the browser between "validate" and "save draft"; an HMAC over
// its content stops a client from saving a payload the worker did not produce.

function key() {
  const s = process.env.SESSION_SECRET || process.env.WORKER_TOKEN || "";
  if (s.length < 16) throw new HttpError(500, "Set SESSION_SECRET (32+ characters).");
  return s;
}

export function signPayload(payload: unknown, uploadId: string): string {
  return crypto.createHmac("sha256", key()).update(uploadId).update(JSON.stringify(payload)).digest("base64url");
}

export function verifyPayload(payload: unknown, uploadId: string, sig: string): boolean {
  const expected = signPayload(payload, uploadId);
  return expected.length === sig.length && crypto.timingSafeEqual(Buffer.from(expected), Buffer.from(sig));
}

// ------------------------------------------------------ uploaded inputs ---

export interface StoredFile {
  field: string;
  filename: string;
  path: string;
  sha256: string;
}

const safeName = (s: string) => s.replace(/[^\w.\- ]+/g, "_").slice(0, 120);

export async function storeUploads(uploadId: string, files: { field: string; file: File }[]): Promise<StoredFile[]> {
  const out: StoredFile[] = [];
  for (const { field, file } of files) {
    const buf = Buffer.from(await file.arrayBuffer());
    const rel = `${uploadId}/${field}__${safeName(file.name)}`;
    const sha256 = crypto.createHash("sha256").update(buf).digest("hex");
    if (supabaseConfigured()) {
      const { error } = await supabaseAdmin().storage.from("uploads").upload(rel, buf, { upsert: true, contentType: file.type || undefined });
      if (error) throw error;
    } else {
      const p = path.join(DATA_DIR, "uploads", rel);
      await fs.mkdir(path.dirname(p), { recursive: true });
      await fs.writeFile(p, buf);
    }
    out.push({ field, filename: file.name, path: rel, sha256 });
  }
  return out;
}

export async function loadUpload(f: StoredFile): Promise<Blob> {
  if (supabaseConfigured()) {
    const { data, error } = await supabaseAdmin().storage.from("uploads").download(f.path);
    if (error) throw error;
    return data;
  }
  return new Blob([await fs.readFile(path.join(DATA_DIR, "uploads", f.path))]);
}

export const MAX_UPLOAD_BYTES = 4 * 1024 * 1024; // stay under Vercel's 4.5 MB request body limit
