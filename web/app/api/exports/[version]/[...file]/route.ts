import { promises as fs } from "fs";
import path from "path";
import { currentUser, errorResponse, HttpError } from "@/lib/server/auth";
import { getVersion, LOCAL_EXPORTS_DIR } from "@/lib/server/repo";
import { R2_BUCKET, r2Configured, r2Get, r2SignedUrl } from "@/lib/server/r2";
import { supabaseAdmin, supabaseConfigured } from "@/lib/server/supabase";

const TYPES: Record<string, string> = {
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".pdf": "application/pdf",
  ".csv": "text/csv; charset=utf-8",
  ".json": "application/json",
  ".geojson": "application/geo+json",
  ".gpkg": "application/geopackage+sqlite3",
  ".zip": "application/zip",
  ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
};

const STREAM_MAX = 4_000_000; // Vercel functions return at most ~4.5 MB

/** Export files: published → public; drafts → signed-in staff only.
 * R2: photo-mode previews (JPG) are streamed from here, so they load from the app's own address (Cloudflare's r2.dev
 * is blocked on some networks) and are cached by the CDN; big files (PNG, ZIP) redirect to a 5-minute signed link. */
export async function GET(_req: Request, ctx: { params: Promise<{ version: string; file: string[] }> }) {
  try {
    const { version, file } = await ctx.params;
    const name = path.basename(decodeURIComponent(file.join("/")));
    const v = await getVersion(version);
    if (!v) throw new HttpError(404, "Not found");
    if (v.status !== "published" && !(await currentUser())) throw new HttpError(401, "Sign in to download draft exports.");
    if (r2Configured()) {
      const key = `exports/${version}/${name}`;
      if (/\.jpe?g$/i.test(name)) {
        const blob = await r2Get(R2_BUCKET, key).catch(() => null);
        if (!blob) throw new HttpError(404, "File not found");
        if (blob.size <= STREAM_MAX)
          return new Response(blob, {
            headers: {
              "Content-Type": "image/jpeg",
              "Cache-Control":
                v.status === "published" ? "public, max-age=3600, s-maxage=604800, stale-while-revalidate=86400" : "private, no-store",
            },
          });
      }
      return Response.redirect(await r2SignedUrl(R2_BUCKET, key, 300, name), 302);
    }
    if (supabaseConfigured()) {
      const { data, error } = await supabaseAdmin().storage.from("exports").createSignedUrl(`${version}/${name}`, 300, { download: name });
      if (error || !data) throw new HttpError(404, "File not found");
      return Response.redirect(data.signedUrl, 302);
    }
    const buf = await fs.readFile(path.join(LOCAL_EXPORTS_DIR, version, name)).catch(() => null);
    if (!buf) throw new HttpError(404, "File not found");
    return new Response(new Uint8Array(buf), {
      headers: {
        "Content-Type": TYPES[path.extname(name).toLowerCase()] ?? "application/octet-stream",
        "Content-Disposition": `attachment; filename="${name}"`,
        "Cache-Control": v.status === "published" ? "public, max-age=3600" : "private, no-store",
      },
    });
  } catch (e) {
    return errorResponse(e);
  }
}
