import "server-only";
import { promises as fs } from "fs";
import path from "path";
import crypto from "crypto";
import type { CatalogEntry, CropsLayer, Payload } from "@/lib/types";
import { slugFor, type AuditEntry, type Repo, type VersionRecord } from "./types";

/** File back end: the bundled demo data (public/demo, read-only) + web/.data/db.json. No database needed. */

const DEMO_DIR = path.join(process.cwd(), "public", "demo");
const DATA_DIR = path.join(process.cwd(), ".data");
const DB_FILE = path.join(DATA_DIR, "db.json");

interface LocalDb {
  versions: VersionRecord[];
  audit: AuditEntry[];
  crops: CropsLayer | null;
  irrigation: any | null;
  unpublishedDemo: string[];
}

async function readJson<T>(file: string, fallback: T): Promise<T> {
  try {
    return JSON.parse(await fs.readFile(file, "utf-8")) as T;
  } catch {
    return fallback;
  }
}

const loadDb = () => readJson<LocalDb>(DB_FILE, { versions: [], audit: [], crops: null, irrigation: null, unpublishedDemo: [] });

let writeChain: Promise<void> = Promise.resolve();
async function saveDb(mutate: (db: LocalDb) => void | Promise<void>) {
  const next = writeChain.then(async () => {
    const db = await loadDb();
    await mutate(db);
    await fs.mkdir(DATA_DIR, { recursive: true });
    await fs.writeFile(DB_FILE + ".tmp", JSON.stringify(db));
    await fs.rename(DB_FILE + ".tmp", DB_FILE);
  });
  writeChain = next.catch(() => undefined);
  await next;
}

function toCatalog(v: VersionRecord): CatalogEntry {
  return {
    id: v.id,
    type: v.type,
    title: v.payload?.title ?? v.title,
    issued: v.issued,
    period: v.period,
    status: v.status,
    version: v.version,
    synthetic: v.payload?.synthetic,
    layers: (v.payload?.layers ?? []).map((l) => ({ id: l.id, label: l.label })),
  };
}

export const fileRepo: Repo = {
  async listPublished() {
    const demo = await readJson<{ products: CatalogEntry[] }>(path.join(DEMO_DIR, "catalog.json"), { products: [] });
    const db = await loadDb();
    const local = db.versions.filter((v) => v.status === "published").map(toCatalog);
    return [...demo.products.filter((p) => !db.unpublishedDemo.includes(p.id)), ...local];
  },

  async getPublishedPayload(id) {
    if (!/^[\w.-]+$/.test(id)) return null;
    const db = await loadDb();
    const v = db.versions.find((x) => x.id === id && x.status === "published");
    if (v?.payload) return { ...v.payload, id, downloads: v.exports?.downloads ?? [] };
    if (db.unpublishedDemo.includes(id)) return null;
    const demo = await readJson<Payload | null>(path.join(DEMO_DIR, "products", `${id}.json`), null);
    if (demo) demo.downloads = (demo.downloads ?? []).map((d) => ({ ...d, url: d.path ? `/demo/${d.path}` : d.url }));
    return demo;
  },

  async getCrops() {
    const db = await loadDb();
    return db.crops ?? readJson<CropsLayer | null>(path.join(DEMO_DIR, "crops.json"), null);
  },

  async getIrrigation() {
    const db = await loadDb();
    return db.irrigation ?? readJson(path.join(DEMO_DIR, "irrigation.geojson"), { type: "FeatureCollection", features: [] });
  },

  async listVersions() {
    const db = await loadDb();
    return [...db.versions].sort((a, b) => b.created_at.localeCompare(a.created_at)).map((v) => ({ ...v, payload: null }));
  },

  async getVersion(id) {
    return (await loadDb()).versions.find((v) => v.id === id) ?? null;
  },

  async createDraft(payload, settings, actor) {
    const slug = slugFor(payload.type, payload.period.start);
    let rec!: VersionRecord;
    await saveDb((db) => {
      const same = db.versions.filter((v) => slugFor(v.type, v.period.start) === slug);
      rec = {
        id: crypto.randomUUID(),
        product_id: slug,
        type: payload.type,
        version: same.reduce((m, v) => Math.max(m, v.version), 0) + 1,
        status: "draft",
        title: payload.texts.title,
        period: payload.period,
        issued: payload.issued,
        settings,
        payload,
        exports: null,
        author: actor.email,
        created_at: new Date().toISOString(),
      };
      db.versions.push(rec);
    });
    return rec;
  },

  async updateDraft(id, patch, allowPublished = false) {
    await saveDb((db) => {
      const v = db.versions.find((x) => x.id === id);
      const published = v?.status === "published";
      if (!v || (v.status !== "draft" && !(allowPublished && published))) throw new Error("Only drafts can be edited");
      if (patch.texts && v.payload) {
        v.payload.texts = { ...v.payload.texts, ...patch.texts };
        v.title = v.payload.texts.title;
        v.exports = published ? { ...(v.exports ?? {}), stale: true } : null;
      }
      if (patch.settings) v.settings = { ...(v.settings ?? {}), ...patch.settings };
      if (patch.exports) v.exports = patch.exports;
    });
  },

  async publish(id, actor) {
    const v = await this.getVersion(id);
    if (!v) throw new Error("Version not found");
    if (!v.exports?.downloads?.length) throw new Error("Generate the exports before publishing.");
    await saveDb((db) => {
      for (const x of db.versions) if (x.product_id === v.product_id && x.status === "published") x.status = "archived";
      const t = db.versions.find((x) => x.id === id)!;
      t.status = "published";
      t.published_at = new Date().toISOString();
      t.published_by = actor.email;
      // a newer local version of a demo product replaces the demo entry
      const demoId = slugFor(t.type, t.period.start).replace(/-(\d{4}-\d{2})-01$/, "-$1");
      if (!db.unpublishedDemo.includes(demoId)) db.unpublishedDemo.push(demoId);
    });
  },

  async unpublish(id) {
    await saveDb((db) => {
      const v = db.versions.find((x) => x.id === id);
      if (v) v.status = "archived";
      else if (!db.unpublishedDemo.includes(id)) db.unpublishedDemo.push(id); // demo product
    });
  },

  async deleteVersion(id) {
    await saveDb((db) => {
      const v = db.versions.find((x) => x.id === id);
      if (!v) throw new Error("Version not found");
      if (v.status === "published") throw new Error("Unpublish this version before deleting it.");
      db.versions = db.versions.filter((x) => x.id !== id);
    });
  },

  async saveCrops(c) {
    await saveDb((db) => {
      db.crops = { ...c, colors: { ...(db.crops?.colors ?? {}), ...(c.colors ?? {}) } };
    });
  },

  async setCropColors(colors) {
    const current = await this.getCrops();
    if (!current) throw new Error("Upload a standing crops table first.");
    await saveDb((db) => {
      db.crops = { ...(db.crops ?? current), colors: { ...(db.crops?.colors ?? current.colors ?? {}), ...colors } };
    });
  },

  async saveIrrigation(fc) {
    await saveDb((db) => {
      db.irrigation = fc;
    });
  },

  async audit(actor, action, entity, entity_id, details) {
    await saveDb((db) => {
      db.audit.unshift({ at: new Date().toISOString(), actor: actor.email, action, entity, entity_id, details });
      db.audit = db.audit.slice(0, 2000);
    });
  },

  async listAudit(limit) {
    return (await loadDb()).audit.slice(0, limit);
  },
};
