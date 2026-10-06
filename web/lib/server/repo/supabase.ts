import "server-only";
import type { CropsLayer, Payload } from "@/lib/types";
import { supabaseAdmin, supabasePublic } from "../supabase";
import { slugFor, UUID_RE, valueRows, type Actor, type Repo, type VersionRecord } from "./types";

/** Supabase back end: public reads with the anon key (RLS: published only), writes with the service role. */

const uid = (a: Actor) => (a.id && UUID_RE.test(a.id) ? a.id : null);
const VERSION_SELECT =
  "id, product_id, version, status, title, settings, exports, created_at, published_at, period:payload->period, issued:payload->>issued, products!inner(type), author_p:profiles!product_versions_author_fkey(email), pub_p:profiles!product_versions_published_by_fkey(email)";

function toVersion(r: any): VersionRecord {
  return {
    ...r,
    type: r.products.type,
    author: r.author_p?.email ?? r.settings?.author_email ?? "system",
    published_by: r.pub_p?.email ?? null,
    payload: r.payload ?? null,
  };
}

export const supabaseRepo: Repo = {
  async listPublished() {
    const { data, error } = await supabasePublic()
      .from("product_versions")
      .select("id, version, title, period:payload->period, issued:payload->>issued, synthetic:payload->synthetic, layers:payload->layers, products!inner(type)")
      .eq("status", "published");
    if (error) throw error;
    return (data ?? []).map((r: any) => ({
      id: r.id,
      type: r.products.type,
      title: r.title,
      issued: r.issued,
      period: r.period,
      status: "published" as const,
      version: r.version,
      synthetic: r.synthetic ?? false,
      layers: (r.layers ?? []).map((l: any) => ({ id: l.id, label: l.label })),
    }));
  },

  async getPublishedPayload(id) {
    if (!UUID_RE.test(id)) return null;
    const { data } = await supabasePublic().from("product_versions").select("payload, exports").eq("id", id).eq("status", "published").maybeSingle();
    if (!data?.payload) return null;
    return { ...(data.payload as Payload), id, downloads: (data.exports as any)?.downloads ?? [] };
  },

  async getCrops() {
    const sb = supabasePublic();
    const { data: t } = await sb.from("crops_tables").select("id, as_of, crops, colors").order("as_of", { ascending: false }).limit(1).maybeSingle();
    if (!t) return null;
    const { data: rows } = await sb.from("crop_values").select("area_key, crop, area_ha").eq("table_id", t.id);
    const values: CropsLayer["values"] = {};
    for (const r of rows ?? []) (values[r.area_key] ??= {})[r.crop] = Number(r.area_ha);
    return { as_of: t.as_of, crops: t.crops, colors: t.colors ?? {}, unit: "ha", values };
  },

  async setCropColors(colors) {
    const sb = supabaseAdmin();
    const { data: t } = await sb.from("crops_tables").select("id, colors").order("as_of", { ascending: false }).limit(1).maybeSingle();
    if (!t) throw new Error("Upload a standing crops table first.");
    const { error } = await sb.from("crops_tables").update({ colors: { ...(t.colors ?? {}), ...colors } }).eq("id", t.id);
    if (error) throw error;
  },

  async getIrrigation() {
    const { data, error } = await supabasePublic().from("irrigation_public").select("feature");
    if (error) throw error;
    return { type: "FeatureCollection", features: (data ?? []).map((r: any) => r.feature) };
  },

  async listVersions() {
    const { data, error } = await supabaseAdmin().from("product_versions").select(VERSION_SELECT).order("created_at", { ascending: false }).limit(200);
    if (error) throw error;
    return (data ?? []).map(toVersion);
  },

  async getVersion(id) {
    if (!UUID_RE.test(id)) return null;
    const { data } = await supabaseAdmin().from("product_versions").select(`${VERSION_SELECT}, payload`).eq("id", id).maybeSingle();
    return data ? toVersion(data) : null;
  },

  async createDraft(payload, settings, actor) {
    const sb = supabaseAdmin();
    const slug = slugFor(payload.type, payload.period.start);
    let { data: prod } = await sb.from("products").select("id, current_version").eq("slug", slug).maybeSingle();
    if (!prod) {
      const ins = await sb
        .from("products")
        .insert({ type: payload.type, slug, period_kind: payload.period.kind, period_start: payload.period.start, period_end: payload.period.end, issue_date: payload.issued, created_by: uid(actor) })
        .select("id, current_version")
        .single();
      if (ins.error) throw ins.error;
      prod = ins.data;
    }
    const version = (prod.current_version ?? 0) + 1;
    const t = payload.texts;
    const { data, error } = await sb
      .from("product_versions")
      .insert({
        product_id: prod.id, version, status: "draft", title: t.title, subtitle: t.subtitle, notes: t.notes, disclaimer: t.disclaimer,
        sources: t.sources, recommendations: t.recommendations, recommendations_source: "auto",
        settings: { ...settings, author_email: actor.email }, method: payload.method ?? {}, summary: payload.summary, payload,
        validation: payload.report ?? {}, author: uid(actor),
      })
      .select("id")
      .single();
    if (error) throw error;
    await sb.from("products").update({ current_version: version, issue_date: payload.issued }).eq("id", prod.id);
    const rows = valueRows(payload).map((r) => ({ ...r, version_id: data.id }));
    for (let i = 0; i < rows.length; i += 500) {
      const ins = await sb.from("product_values").insert(rows.slice(i, i + 500));
      if (ins.error) throw ins.error;
    }
    return (await this.getVersion(data.id))!;
  },

  async updateDraft(id, patch, allowPublished = false) {
    const v = await this.getVersion(id);
    if (!v) throw new Error("Version not found");
    const published = v.status === "published";
    if (v.status !== "draft" && !(allowPublished && published)) throw new Error("Only drafts can be edited");
    const update: Record<string, any> = {};
    if (patch.texts && v.payload) {
      const payload = { ...v.payload, texts: { ...v.payload.texts, ...patch.texts } };
      const t = payload.texts;
      Object.assign(update, {
        payload, title: t.title, subtitle: t.subtitle, notes: t.notes, disclaimer: t.disclaimer, sources: t.sources,
        recommendations: t.recommendations, recommendations_source: "edited",
        exports: published ? { ...(v.exports ?? {}), stale: true } : {},
      });
    }
    if (patch.exports) update.exports = patch.exports;
    if (patch.settings) update.settings = { ...(v.settings ?? {}), ...patch.settings };
    const { error } = await supabaseAdmin().from("product_versions").update(update).eq("id", id)
      .in("status", allowPublished ? ["draft", "published"] : ["draft"]);
    if (error) throw error;
  },

  async publish(id, actor) {
    const v = await this.getVersion(id);
    if (!v) throw new Error("Version not found");
    if (!v.exports?.downloads?.length) throw new Error("Generate the exports before publishing.");
    const sb = supabaseAdmin();
    await sb.from("product_versions").update({ status: "archived" }).eq("product_id", v.product_id).eq("status", "published");
    const { error } = await sb.from("product_versions").update({ status: "published", published_at: new Date().toISOString(), published_by: uid(actor) }).eq("id", id);
    if (error) throw error;
    await sb.from("products").update({ published_version: v.version }).eq("id", v.product_id);
  },

  async unpublish(id) {
    const v = await this.getVersion(id);
    if (!v) throw new Error("Version not found");
    const sb = supabaseAdmin();
    await sb.from("product_versions").update({ status: "archived" }).eq("id", id);
    await sb.from("products").update({ published_version: null }).eq("id", v.product_id);
  },

  async deleteVersion(id) {
    const v = await this.getVersion(id);
    if (!v) throw new Error("Version not found");
    if (v.status === "published") throw new Error("Unpublish this version before deleting it.");
    const sb = supabaseAdmin();
    const { error } = await sb.from("product_versions").delete().eq("id", id);
    if (error) throw error;
    const { count } = await sb.from("product_versions").select("id", { count: "exact", head: true }).eq("product_id", v.product_id);
    if (!count) await sb.from("products").delete().eq("id", v.product_id);
    // export files of the version
    for (const bucket of ["exports", "public-exports"]) {
      const { data } = await sb.storage.from(bucket).list(id, { limit: 1000 });
      if (data?.length) await sb.storage.from(bucket).remove(data.map((f) => `${id}/${f.name}`));
    }
  },

  async saveCrops(c, actor) {
    const sb = supabaseAdmin();
    const { data, error } = await sb.from("crops_tables").upsert({ as_of: c.as_of, crops: c.crops, colors: c.colors ?? {}, created_by: uid(actor) }, { onConflict: "as_of" }).select("id").single();
    if (error) throw error;
    await sb.from("crop_values").delete().eq("table_id", data.id);
    const rows = Object.entries(c.values).flatMap(([area_key, crops]) => Object.entries(crops).map(([crop, area_ha]) => ({ table_id: data.id, area_key, crop, area_ha })));
    const ins = await sb.from("crop_values").insert(rows);
    if (ins.error) throw ins.error;
  },

  async saveIrrigation(fc, serviceAreas) {
    const { error } = await supabaseAdmin().rpc("replace_irrigation_sources", { p_features: fc.features, p_service_areas: serviceAreas?.features ?? [] });
    if (error) throw error;
  },

  async audit(actor, action, entity, entity_id, details) {
    await supabaseAdmin().from("audit_log").insert({ actor: uid(actor), actor_email: actor.email, action, entity, entity_id, details });
  },

  async listAudit(limit) {
    const { data } = await supabaseAdmin().from("audit_log").select("at, actor_email, action, entity, entity_id, details").order("at", { ascending: false }).limit(limit);
    return (data ?? []).map((r: any) => ({ ...r, actor: r.actor_email }));
  },
};
