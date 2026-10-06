import { promises as fs } from "fs";
import path from "path";
import { currentUser, errorResponse, HttpError } from "@/lib/server/auth";
import { getVersion, LOCAL_EXPORTS_DIR } from "@/lib/server/repo";
import { supabaseAdmin, supabaseConfigured } from "@/lib/server/supabase";

const TYPES: Record<string, string> = {
  ".png": "image/png",
  ".pdf": "application/pdf",
  ".csv": "text/csv; charset=utf-8",
  ".json": "application/json",
  ".geojson": "application/geo+json",
  ".gpkg": "application/geopackage+sqlite3",
  ".zip": "application/zip",
  ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
};

/** Export files: published → public; drafts → signed-in staff only (a short-lived signed URL in Supabase mode). */
export async function GET(_req: Request, ctx: { params: Promise<{ version: string; file: string[] }> }) {
  try {
    const { version, file } = await ctx.params;
    const name = path.basename(decodeURIComponent(file.join("/")));
    const v = await getVersion(version);
    if (!v) throw new HttpError(404, "Not found");
    if (v.status !== "published" && !(await currentUser())) throw new HttpError(401, "Sign in to download draft exports.");
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
