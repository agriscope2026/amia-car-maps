import type { CatalogEntry, CropsLayer, Payload, ProductType, Status } from "@/lib/types";

export interface Actor {
  id?: string;
  email: string;
}

export interface VersionRecord {
  id: string;
  product_id: string;
  type: ProductType;
  version: number;
  status: Status;
  title: string;
  period: Payload["period"];
  issued: string;
  settings: Record<string, any>;
  payload: Payload | null;
  exports: {
    job_id?: string;
    manifest?: any;
    downloads?: Payload["downloads"];
    pending_job?: string; // a regeneration running for a published version (current files stay live meanwhile)
    stale?: boolean; // published texts were edited after these files were made
  } | null;
  author: string;
  created_at: string;
  published_at?: string | null;
  published_by?: string | null;
}

export interface AuditEntry {
  at: string;
  actor: string;
  action: string;
  entity?: string;
  entity_id?: string;
  details?: any;
}

export interface DraftPatch {
  texts?: Partial<Payload["texts"]>;
  settings?: Record<string, any>; // merged into the version settings
  exports?: VersionRecord["exports"];
}

/** One data back end (Supabase, PostgreSQL or the local file store). */
export interface Repo {
  listPublished(): Promise<CatalogEntry[]>;
  getPublishedPayload(id: string): Promise<Payload | null>;
  getCrops(): Promise<CropsLayer | null>;
  getIrrigation(): Promise<any>;
  listVersions(): Promise<VersionRecord[]>;
  getVersion(id: string): Promise<VersionRecord | null>;
  createDraft(payload: Payload, settings: Record<string, any>, actor: Actor): Promise<VersionRecord>;
  /** Edit a draft – or, with allowPublished, a published version (texts go live immediately). */
  updateDraft(id: string, patch: DraftPatch, allowPublished?: boolean): Promise<void>;
  publish(id: string, actor: Actor): Promise<void>;
  unpublish(id: string): Promise<void>;
  /** Permanently delete an archived (or draft) version; the product goes too when it has no versions left. */
  deleteVersion(id: string): Promise<void>;
  saveCrops(c: CropsLayer, actor: Actor): Promise<void>;
  setCropColors(colors: Record<string, string>): Promise<void>;
  saveIrrigation(fc: any, serviceAreas: any | null): Promise<void>;
  audit(actor: Actor, action: string, entity?: string, entity_id?: string, details?: any): Promise<void>;
  listAudit(limit: number): Promise<AuditEntry[]>;
}

export function slugFor(type: ProductType, periodStart: string) {
  return `${type}-${periodStart}`;
}

/** Rows for product_values: municipality × layer, with unit, class and colour. */
export function valueRows(payload: Payload) {
  return payload.layers.flatMap((l) =>
    Object.entries(l.values).map(([area_key, v]) => {
      const { value, class: cls, color, ...extra } = v;
      const month = l.id.match(/^m_(\d{4}-\d{2})$/)?.[1];
      const day = l.id.match(/^d_(\d{4}-\d{2}-\d{2})$/)?.[1];
      return {
        layer_id: l.id,
        period_start: day ?? (month ? `${month}-01` : payload.period.start),
        period_end: day ?? (month ? null : payload.period.end),
        area_key,
        variable: l.variable,
        value: typeof value === "number" ? value : null,
        value_text: typeof value === "string" ? value : null,
        unit: l.unit,
        class_label: cls,
        class_color: color,
        extra: Object.keys(extra).length ? extra : null,
      };
    }),
  );
}

export const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
