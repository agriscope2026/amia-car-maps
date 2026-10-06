import "server-only";
import type { CatalogEntry, CropsLayer, Payload } from "@/lib/types";
import { q, tx } from "../db";
import { slugFor, UUID_RE, valueRows, type Actor, type AuditEntry, type Repo, type VersionRecord } from "./types";

/** PostgreSQL + PostGIS back end (the local development database, or a self-hosted server). */

const VERSION_COLS = `v.id, v.product_id, p.type, v.version, v.status, v.title, v.settings, v.exports,
  coalesce(a.email, v.settings->>'author_email', 'system') as author, v.created_at, v.published_at,
  pb.email as published_by, v.payload->'period' as period, v.payload->>'issued' as issued`;
const VERSION_FROM = `product_versions v join products p on p.id = v.product_id
  left join profiles a on a.id = v.author left join profiles pb on pb.id = v.published_by`;

const uid = (a: Actor) => (a.id && UUID_RE.test(a.id) ? a.id : null);

async function insertValues(c: { query: (t: string, p: unknown[]) => Promise<unknown> }, versionId: string, payload: Payload) {
  await c.query("delete from product_values where version_id = $1", [versionId]);
  await c.query(
    `insert into product_values (version_id, layer_id, period_start, period_end, area_key, variable, value, value_text,
       unit, class_label, class_color, extra)
     select $1, layer_id, period_start, period_end, area_key, variable, value, value_text, unit, class_label, class_color, extra
     from jsonb_to_recordset($2::jsonb) as x(layer_id text, period_start date, period_end date, area_key text, variable text,
       value numeric, value_text text, unit text, class_label text, class_color text, extra jsonb)`,
    [versionId, JSON.stringify(valueRows(payload))],
  );
}

export const postgresRepo: Repo = {
  async listPublished() {
    return q<CatalogEntry>(
      `select v.id, p.type, v.title, v.payload->>'issued' as issued, v.payload->'period' as period, 'published' as status,
         v.version, coalesce((v.payload->>'synthetic')::boolean, false) as synthetic,
         coalesce((select jsonb_agg(jsonb_build_object('id', l->>'id', 'label', l->>'label'))
                   from jsonb_array_elements(v.payload->'layers') l), '[]') as layers
       from product_versions v join products p on p.id = v.product_id
       where v.status = 'published'`,
    );
  },

  async getPublishedPayload(id) {
    if (!UUID_RE.test(id)) return null;
    const [r] = await q(`select payload, exports from product_versions where id = $1 and status = 'published'`, [id]);
    if (!r?.payload) return null;
    return { ...(r.payload as Payload), id, downloads: r.exports?.downloads ?? [] };
  },

  async getCrops() {
    const [t] = await q(`select id, as_of, crops, colors from crops_tables order by as_of desc limit 1`);
    if (!t) return null;
    const rows = await q(`select area_key, crop, area_ha from crop_values where table_id = $1`, [t.id]);
    const values: CropsLayer["values"] = {};
    for (const r of rows) (values[r.area_key] ??= {})[r.crop] = Number(r.area_ha);
    return { as_of: t.as_of, crops: t.crops, colors: t.colors ?? {}, unit: "ha", values };
  },

  async setCropColors(colors) {
    await q(`update crops_tables set colors = colors || $1::jsonb
             where id = (select id from crops_tables order by as_of desc limit 1)`, [JSON.stringify(colors)]);
  },

  async getIrrigation() {
    const rows = await q(`select feature from irrigation_public`);
    return { type: "FeatureCollection", features: rows.map((r) => r.feature) };
  },

  async listVersions() {
    const rows = await q<VersionRecord>(`select ${VERSION_COLS} from ${VERSION_FROM} order by v.created_at desc limit 200`);
    return rows.map((r) => ({ ...r, payload: null }));
  },

  async getVersion(id) {
    if (!UUID_RE.test(id)) return null;
    const [r] = await q<VersionRecord>(`select ${VERSION_COLS}, v.payload from ${VERSION_FROM} where v.id = $1`, [id]);
    return r ?? null;
  },

  async createDraft(payload, settings, actor) {
    const slug = slugFor(payload.type, payload.period.start);
    const id = await tx(async (c) => {
      await c.query(
        `insert into products (type, slug, period_kind, period_start, period_end, issue_date, created_by)
         values ($1, $2, $3, $4, $5, $6, $7) on conflict (slug) do nothing`,
        [payload.type, slug, payload.period.kind, payload.period.start, payload.period.end, payload.issued, uid(actor)],
      );
      const prod = (await c.query(`select id, current_version from products where slug = $1 for update`, [slug])).rows[0];
      const version = (prod.current_version ?? 0) + 1;
      const t = payload.texts;
      const v = await c.query(
        `insert into product_versions (product_id, version, status, title, subtitle, notes, disclaimer, sources,
           recommendations, recommendations_source, settings, method, summary, payload, validation, author)
         values ($1, $2, 'draft', $3, $4, $5, $6, $7, $8, 'auto', $9, $10, $11, $12, $13, $14) returning id`,
        [prod.id, version, t.title, t.subtitle, t.notes, t.disclaimer, t.sources, t.recommendations,
          { ...settings, author_email: actor.email }, payload.method ?? {}, payload.summary, payload, payload.report ?? {}, uid(actor)],
      );
      await c.query(`update products set current_version = $2, issue_date = $3 where id = $1`, [prod.id, version, payload.issued]);
      await insertValues(c, v.rows[0].id, payload);
      return v.rows[0].id as string;
    });
    return (await this.getVersion(id))!;
  },

  async updateDraft(id, patch, allowPublished = false) {
    await tx(async (c) => {
      const v = (await c.query(`select status, payload, exports from product_versions where id = $1 for update`, [id])).rows[0];
      if (!v) throw new Error("Version not found");
      const published = v.status === "published";
      if (v.status !== "draft" && !(allowPublished && published)) throw new Error("Only drafts can be edited");
      if (patch.texts && v.payload) {
        const payload = { ...v.payload, texts: { ...v.payload.texts, ...patch.texts } };
        const t = payload.texts;
        // drafts: old exports are discarded; published: files stay live until regenerated, marked out of date
        const exports = published ? { ...(v.exports ?? {}), stale: true } : {};
        await c.query(
          `update product_versions set payload = $2, title = $3, subtitle = $4, notes = $5, disclaimer = $6, sources = $7,
             recommendations = $8, recommendations_source = 'edited', exports = $9 where id = $1`,
          [id, payload, t.title, t.subtitle, t.notes, t.disclaimer, t.sources, t.recommendations, exports],
        );
      }
      if (patch.settings) {
        await c.query(`update product_versions set settings = settings || $2::jsonb where id = $1`, [
          id, JSON.stringify(patch.settings),
        ]);
      }
      if (patch.exports) {
        await c.query(`update product_versions set exports = $2, label_report = $3 where id = $1`, [
          id, patch.exports, patch.exports.manifest ? { labels_ok: patch.exports.manifest.labels_ok } : null,
        ]);
      }
    });
  },

  async publish(id, actor) {
    await tx(async (c) => {
      const v = (await c.query(`select product_id, version, status, exports from product_versions where id = $1 for update`, [id])).rows[0];
      if (!v) throw new Error("Version not found");
      if (!v.exports?.downloads?.length) throw new Error("Generate the exports before publishing.");
      await c.query(`update product_versions set status = 'archived' where product_id = $1 and status = 'published'`, [v.product_id]);
      await c.query(`update product_versions set status = 'published', published_at = now(), published_by = $2 where id = $1`, [id, uid(actor)]);
      await c.query(`update products set published_version = $2 where id = $1`, [v.product_id, v.version]);
    });
  },

  async unpublish(id) {
    await tx(async (c) => {
      const v = (await c.query(`select product_id from product_versions where id = $1`, [id])).rows[0];
      if (!v) throw new Error("Version not found");
      await c.query(`update product_versions set status = 'archived' where id = $1`, [id]);
      await c.query(`update products set published_version = null where id = $1`, [v.product_id]);
    });
  },

  async deleteVersion(id) {
    await tx(async (c) => {
      const v = (await c.query(`select product_id, status from product_versions where id = $1 for update`, [id])).rows[0];
      if (!v) throw new Error("Version not found");
      if (v.status === "published") throw new Error("Unpublish this version before deleting it.");
      await c.query(`delete from product_versions where id = $1`, [id]);           // values cascade
      await c.query(`delete from products p where id = $1 and not exists
                       (select 1 from product_versions x where x.product_id = p.id)`, [v.product_id]);
    });
  },

  async saveCrops(cr, actor) {
    await tx(async (c) => {
      const t = await c.query(
        `insert into crops_tables (as_of, crops, colors, created_by) values ($1, $2, $3, $4)
         on conflict (as_of) do update set crops = excluded.crops, colors = crops_tables.colors || excluded.colors
         returning id`,
        [cr.as_of, cr.crops, JSON.stringify(cr.colors ?? {}), uid(actor)],
      );
      const tid = t.rows[0].id;
      await c.query(`delete from crop_values where table_id = $1`, [tid]);
      const rows = Object.entries(cr.values).flatMap(([area_key, v]) => Object.entries(v).map(([crop, ha]) => ({ area_key, crop, ha })));
      await c.query(
        `insert into crop_values (table_id, area_key, crop, area_ha)
         select $1, area_key, crop, ha from jsonb_to_recordset($2::jsonb) as x(area_key text, crop text, ha numeric)`,
        [tid, JSON.stringify(rows)],
      );
    });
  },

  async saveIrrigation(fc, serviceAreas) {
    await q(`select replace_irrigation_sources($1::jsonb, $2::jsonb)`, [
      JSON.stringify(fc.features ?? []),
      JSON.stringify(serviceAreas?.features ?? []),
    ]);
  },

  async audit(actor, action, entity, entity_id, details) {
    await q(`insert into audit_log (actor, actor_email, action, entity, entity_id, details) values ($1, $2, $3, $4, $5, $6)`, [
      uid(actor), actor.email, action, entity ?? null, entity_id ?? null, details ?? null,
    ]);
  },

  async listAudit(limit) {
    return q<AuditEntry>(
      `select at, actor_email as actor, action, entity, entity_id, details from audit_log order by at desc limit $1`,
      [limit],
    );
  },
};
