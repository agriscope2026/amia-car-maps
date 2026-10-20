import "server-only";
import { promises as fs } from "fs";
import path from "path";
import { activityInput, firstIssue, type ActivityInput } from "@/lib/activities";
import type { Gazetteer } from "@/lib/types";
import { HttpError } from "./auth";

let areas: Promise<Set<string>> | null = null;

/** The 77 municipality keys of the dashboard's gazetteer. */
function areaKeys(): Promise<Set<string>> {
  areas ??= fs
    .readFile(path.join(process.cwd(), "public", "geo", "car.json"), "utf-8")
    .then((t) => new Set((JSON.parse(t) as Gazetteer).gazetteer.map((g) => g.area_key)));
  return areas;
}

/** Validate one activity (manual entry or an import row); `where` prefixes the error, e.g. "Row 5". */
export async function cleanActivity(raw: unknown, where?: string): Promise<ActivityInput> {
  const r = activityInput.safeParse(raw);
  const at = where ? `${where}: ` : "";
  if (!r.success) throw new HttpError(400, at + firstIssue(r.error));
  const known = await areaKeys();
  const bad = r.data.area_keys.find((k) => !known.has(k));
  if (bad) throw new HttpError(400, `${at}unknown municipality ${bad}.`);
  return r.data;
}
