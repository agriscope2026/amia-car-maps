import { assertSameOrigin, errorResponse, HttpError, requireRole } from "@/lib/server/auth";
import { cleanActivity } from "@/lib/server/activities";
import { addActivities, audit } from "@/lib/server/repo";
import { MAX_UPLOAD_BYTES, worker } from "@/lib/server/worker";

/** Staff: activities from an Excel/CSV list. The worker reads and checks the file; `?save=1` stores a valid list
 * (added to the current activities, or – with replace=1 – instead of them). */
export async function POST(req: Request) {
  try {
    await assertSameOrigin();
    const user = await requireRole("editor");
    const form = await req.formData();
    const file = form.get("file");
    if (!(file instanceof File) || !file.size) throw new HttpError(400, "Choose a file.");
    if (file.size > MAX_UPLOAD_BYTES) throw new HttpError(413, "File larger than 4 MB.");
    if (!/\.(xlsx|xlsm|xls|csv)$/i.test(file.name)) throw new HttpError(400, `${file.name}: upload a .xlsx or .csv file.`);
    const fwd = new FormData();
    fwd.set("file", file, file.name);
    const res = await worker("/activities/parse", { method: "POST", body: fwd });
    const save = new URL(req.url).searchParams.get("save") === "1";
    const replace = form.get("replace") === "1";
    let saved = 0;
    if (save && res.ok) {
      const rows = [];
      for (const r of res.rows as any[]) {
        const { row, area_labels: _labels, ...a } = r;
        rows.push(await cleanActivity(a, `Row ${row}`));
      }
      saved = await addActivities(rows, user, file.name, replace);
      await audit(user, replace ? "activity_import_replace" : "activity_import", "activities", file.name, {
        count: saved, municipalities: res.report?.municipalities,
      });
    }
    return Response.json({ ...res, saved });
  } catch (e) {
    return errorResponse(e);
  }
}
