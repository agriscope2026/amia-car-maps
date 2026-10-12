/** "New update" notice on the dashboard: which map types have a newer issue than this browser has seen. */
import type { CatalogEntry, ProductType } from "./types";
import { latestOf } from "./format";

export const NEW_DAYS = 30; // an issue counts as new for this long after it was published
const STORAGE_KEY = "amia-seen-updates-v1";

export type Seen = Partial<Record<ProductType, string>>;

/** Identifies one published version (a republished version counts as a new update). */
export const updateKey = (e: CatalogEntry) => `${e.id}:${e.version}`;

/** When the issue went live (publish date, else its issue date), as YYYY-MM-DD. */
export const updatedOn = (e: CatalogEntry) => (e.published_at ?? e.issued ?? "").slice(0, 10);

/** The latest issue of each map type that is recent and not yet seen in this browser, newest first. */
export function newUpdates(catalog: CatalogEntry[], seen: Seen, now: Date = new Date()): CatalogEntry[] {
  const types = [...new Set(catalog.map((p) => p.type))];
  const out: CatalogEntry[] = [];
  for (const t of types) {
    const e = latestOf(catalog, t);
    if (!e || seen[t] === updateKey(e)) continue;
    const day = updatedOn(e);
    const age = (now.getTime() - new Date(`${day}T00:00:00`).getTime()) / 86_400_000;
    if (day && age <= NEW_DAYS) out.push(e);
  }
  return out.sort((a, b) => updatedOn(b).localeCompare(updatedOn(a)));
}

/** Seen issues are remembered per browser only (no login); storage may be unavailable (private mode). */
export function loadSeen(): Seen {
  try {
    return JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}") as Seen;
  } catch {
    return {};
  }
}

export function saveSeen(seen: Seen): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(seen));
  } catch {
    /* storage blocked: the notice simply shows again next visit */
  }
}
