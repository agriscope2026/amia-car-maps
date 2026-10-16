import "server-only";
import { listVersions } from "./repo";
import type { StoredFile } from "./worker";

export interface ReusedInput {
  file: StoredFile;
  version_id: string;
  issue: string; // period label of the issue the file comes from
  issued: string;
  status: string;
  settings: Record<string, any>; // settings of that issue (e.g. livestock_as_of)
}

/** The input file of the most recent ENVI issue for one dataset (historical damage, livestock – they change rarely):
 * published issues first (latest period), then drafts (newest). Null when no ENVI issue has that file. */
export async function latestEnviInput(field: string): Promise<ReusedInput | null> {
  const withFile = (await listVersions()).filter(
    (v) => v.type === "envi" && (v.settings?.input_files ?? []).some((f: StoredFile) => f.field === field),
  );
  const rank = (s: string) => (s === "published" ? 0 : s === "draft" ? 1 : 2);
  withFile.sort(
    (a, b) => rank(a.status) - rank(b.status) || b.period.start.localeCompare(a.period.start) || b.created_at.localeCompare(a.created_at),
  );
  const v = withFile[0];
  if (!v) return null;
  const file = (v.settings.input_files as StoredFile[]).find((f) => f.field === field)!;
  return { file, version_id: v.id, issue: v.period.label, issued: v.issued, status: v.status, settings: v.settings };
}
