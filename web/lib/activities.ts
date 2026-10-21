/** Activities (interventions) in the municipalities, linked to the map they respond to, and the pure helpers of the
 * activities page: which areas of a map are vulnerable and how the activities cover them. Shared by the browser and
 * the server (no server-only imports). */
import { z } from "zod";
import type { Layer, ProductType } from "./types";

export const ACTIVITY_STATUSES = [
  { id: "to_conduct", label: "To conduct", color: "#1565c0" },
  { id: "ongoing", label: "Ongoing", color: "#e08a00" },
  { id: "completed", label: "Completed", color: "#2e7d32" },
  { id: "postponed", label: "Postponed", color: "#757575" },
] as const;
export type ActivityStatus = (typeof ACTIVITY_STATUSES)[number]["id"];

/** The map an activity responds to; "general" applies to every map. */
export const ACTIVITY_HAZARDS = [
  { id: "general", label: "All maps (general)" },
  { id: "envi", label: "El Niño (ENVI)" },
  { id: "drought", label: "Drought forecast" },
  { id: "rainfall_dekad", label: "10-day rainfall" },
  { id: "rainfall_seasonal", label: "Seasonal rainfall" },
  { id: "tc_advisory", label: "Tropical cyclone (typhoon)" },
] as const;
export type ActivityHazard = (typeof ACTIVITY_HAZARDS)[number]["id"];

/** Who benefits: individual farmers or farmer groups (farmer cooperatives and associations, FCA); `beneficiaries`
 * is the count of farmers or of FCAs. */
export const BENEFICIARY_TYPES = [
  { id: "individual", label: "Individual farmers", unit: "farmers", one: "farmer" },
  { id: "fca", label: "Farmer group (FCA)", unit: "FCAs", one: "FCA" },
] as const;
export type BeneficiaryType = (typeof BENEFICIARY_TYPES)[number]["id"];

/** "250 farmers", "3 FCAs", "1 FCA", or "250 beneficiaries" when the type is not given. */
export function beneficiariesText(n: number | null, type: BeneficiaryType | null): string {
  if (n == null) return "";
  const t = BENEFICIARY_TYPES.find((b) => b.id === type);
  const word = t ? (n === 1 ? t.one : t.unit) : n === 1 ? "beneficiary" : "beneficiaries";
  return `${n.toLocaleString("en-PH")} ${word}`;
}

export const statusLabel = (s: string) => ACTIVITY_STATUSES.find((x) => x.id === s)?.label ?? s;
export const hazardLabel = (h: string) => ACTIVITY_HAZARDS.find((x) => x.id === h)?.label ?? h;

export interface Activity {
  id: string;
  area_keys: string[]; // the municipalities it takes place in, e.g. ["ABRA|BANGUED", "ABRA|TAYUM"]
  title: string;
  category: string | null; // e.g. Training, Distribution of inputs, Infrastructure
  status: ActivityStatus;
  hazard: ActivityHazard;
  start_date: string | null; // YYYY-MM-DD
  end_date: string | null;
  units: number | null; // units delivered, e.g. 3 (PISOS), 1 (solar-powered irrigation system)
  beneficiary_type: BeneficiaryType | null; // individual farmers or farmer groups (FCA)
  beneficiaries: number | null; // count of farmers, or of FCAs
  budget: number | null; // PHP
  office: string | null; // implementing office / unit
  remarks: string | null;
  source: string | null; // "manual" or the uploaded file name
  created_by: string | null; // email
  created_at: string;
  updated_at: string;
}

const text = (max: number) =>
  z
    .string()
    .trim()
    .max(max)
    .nullish()
    .transform((s) => (s ? s : null));
const date = z
  .string()
  .regex(/^\d{4}-\d{2}-\d{2}$/, "Use the date format YYYY-MM-DD.")
  .nullish()
  .or(z.literal(""))
  .transform((s) => s || null);
const amount = z
  .number()
  .finite()
  .min(0, "must be 0 or more")
  .nullish()
  .transform((n) => (n === undefined ? null : n));

/** What an admin enters (by hand or one row of an Excel import). */
export const activityInput = z
  .object({
    area_keys: z
      .array(z.string().regex(/^[A-Z ]+\|[A-Z ]+$/, "Unknown municipality."))
      .min(1, "Choose at least one municipality.")
      .max(500)
      .transform((ks) => [...new Set(ks)].sort()), // checked against the gazetteer on save
    title: z.string().trim().min(1, "Enter the activity.").max(300),
    category: text(100),
    status: z.enum(ACTIVITY_STATUSES.map((s) => s.id) as [ActivityStatus, ...ActivityStatus[]]),
    hazard: z.enum(ACTIVITY_HAZARDS.map((h) => h.id) as [ActivityHazard, ...ActivityHazard[]]).default("general"),
    start_date: date,
    end_date: date,
    units: amount,
    beneficiary_type: z
      .enum(BENEFICIARY_TYPES.map((b) => b.id) as [BeneficiaryType, ...BeneficiaryType[]])
      .nullish()
      .transform((t) => t ?? null),
    beneficiaries: amount.transform((n) => (n === null ? null : Math.round(n))),
    budget: amount,
    office: text(200),
    remarks: text(1000),
  })
  .refine((a) => !a.start_date || !a.end_date || a.start_date <= a.end_date, {
    message: "The end date is before the start date.",
    path: ["end_date"],
  });
export type ActivityInput = z.output<typeof activityInput>;

const FIELD_NAMES: Record<string, string> = {
  area_keys: "Places", title: "Activity", category: "Category", status: "Status", hazard: "Map", start_date: "Start date",
  end_date: "End date", units: "No. of units", beneficiary_type: "Beneficiary type", beneficiaries: "Beneficiaries", budget: "Budget", office: "Office", remarks: "Remarks",
};

/** First validation message of a zod error, e.g. "title: Enter the activity." */
export function firstIssue(e: z.ZodError): string {
  const i = e.issues[0];
  if (!i) return "Invalid activity.";
  const field = String(i.path[0] ?? "");
  const name = FIELD_NAMES[field] ?? field;
  return name ? `${name}: ${i.message}` : i.message;
}

// ------------------------------------------------------------ vulnerability ---

/** Classes of a map that count as vulnerable by default: the top two of a categorical legend (ENVI High / Very High,
 * drought Dry spell / Drought) and the upper half of a graduated one (heavy rainfall and above). */
export function defaultVulnerableClasses(layer: Pick<Layer, "legend">): string[] {
  const cls = layer.legend.classes.map((c) => c.label);
  if (layer.legend.id === "tcws") return cls.slice(1); // tropical cyclone: every wind signal
  const from = layer.legend.kind === "categorical" ? Math.max(0, cls.length - 2) : Math.ceil(cls.length / 2);
  return cls.slice(from);
}

/** Class of every area on one map – or, with several maps (e.g. the months of an outlook), the highest class an
 * area reaches in any of them. */
export function worstClasses(layers: Layer[]): Record<string, { class: string; color: string; rank: number; layer: string }> {
  const out: Record<string, { class: string; color: string; rank: number; layer: string }> = {};
  for (const l of layers) {
    const rank = new Map(l.legend.classes.map((c, i) => [c.label, i]));
    for (const [k, v] of Object.entries(l.values)) {
      const r = rank.get(v.class);
      if (r === undefined) continue; // no data
      if (!out[k] || r > out[k].rank) out[k] = { class: v.class, color: v.color, rank: r, layer: l.label };
    }
  }
  return out;
}

export interface StatusCounts {
  to_conduct: number;
  ongoing: number;
  completed: number;
  postponed: number;
}
export const emptyCounts = (): StatusCounts => ({ to_conduct: 0, ongoing: 0, completed: 0, postponed: 0 });

type Town = { area_key: string; name: string; province: string };

/** Places in words, by province: "Whole CAR", "Abra (all 27) · Benguet: La Trinidad, Tublay". `max` names at most that
 * many municipalities in total, then "+ n more". */
export function placesSummary(keys: string[], towns: Town[], max = 6): string {
  const set = new Set(keys);
  if (!set.size) return "";
  if (towns.length && towns.every((t) => set.has(t.area_key))) return `Whole CAR (all ${towns.length} municipalities)`;
  const byProv = new Map<string, { all: number; picked: string[] }>();
  for (const t of towns) {
    const p = byProv.get(t.province) ?? { all: 0, picked: [] };
    p.all += 1;
    if (set.has(t.area_key)) p.picked.push(t.name);
    byProv.set(t.province, p);
  }
  const parts: string[] = [];
  let named = 0;
  let more = 0;
  for (const [prov, p] of [...byProv.entries()].sort((x, y) => x[0].localeCompare(y[0]))) {
    if (!p.picked.length) continue;
    if (p.picked.length === p.all && p.all > 1) {
      parts.push(`${prov} (all ${p.all})`);
      continue;
    }
    const names = [...p.picked].sort();
    const room = Math.max(0, max - named);
    const show = names.slice(0, room);
    named += show.length;
    more += names.length - show.length;
    if (show.length) parts.push(`${prov}: ${show.join(", ")}`);
  }
  return parts.join(" · ") + (more ? ` + ${more} more` : "");
}

/** Does an activity take place in any of these municipalities? */
export const inAny = (a: Pick<Activity, "area_keys">, keys: Set<string>) => a.area_keys.some((k) => keys.has(k));

/** Activities that answer a map: those for that map and the general ones. */
export function activitiesFor(all: Activity[], type: ProductType | "all"): Activity[] {
  return type === "all" ? all : all.filter((a) => a.hazard === type || a.hazard === "general");
}

export interface Coverage {
  vulnerable: number; // vulnerable areas
  covered: number; // … with at least one activity that is not postponed
  gaps: string[]; // vulnerable areas without one
  counts: StatusCounts; // activities in (at least one of) the vulnerable areas, each counted once
  beneficiaries: number; // of those activities (an activity in several places counts once, in full)
  farmers: number; // … of which individual farmers (and beneficiaries of unknown type)
  fcas: number; // … of which farmer groups (FCA)
  budget: number;
}

export function coverage(vulnerable: string[], acts: Activity[]): Coverage {
  const set = new Set(vulnerable);
  const counts = emptyCounts();
  const active = new Set<string>();
  let beneficiaries = 0;
  let farmers = 0;
  let fcas = 0;
  let budget = 0;
  for (const a of acts) {
    const here = a.area_keys.filter((k) => set.has(k));
    if (!here.length) continue;
    counts[a.status] += 1;
    if (a.status !== "postponed") for (const k of here) active.add(k);
    beneficiaries += a.beneficiaries ?? 0;
    if (a.beneficiary_type === "fca") fcas += a.beneficiaries ?? 0;
    else farmers += a.beneficiaries ?? 0;
    budget += a.budget ?? 0;
  }
  return {
    vulnerable: set.size,
    covered: active.size,
    gaps: vulnerable.filter((k) => !active.has(k)),
    counts,
    beneficiaries,
    farmers,
    fcas,
    budget,
  };
}
