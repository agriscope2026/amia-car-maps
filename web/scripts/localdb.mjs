// Local development database: a project-local PostgreSQL 17 + PostGIS cluster in <repo>/.localdb.
// It does not touch any installed PostgreSQL service and needs no admin rights or password.
//
//   node scripts/localdb.mjs setup                 copy PostgreSQL binaries, add PostGIS, initdb
//   node scripts/localdb.mjs start | stop | status
//   node scripts/localdb.mjs reset [--no-demo]     recreate the database: compat + migrations + seed (+ demo data + admin)
//   node scripts/localdb.mjs demo                  refresh only the demo products (keeps your own work)
//   node scripts/localdb.mjs migrate               apply new migrations to an existing database (keeps your data)
//   node scripts/localdb.mjs add-user <email> <password> [editor|admin]
//   node scripts/localdb.mjs psql                  print the psql command line
//
// Env: PG_HOME (default C:/Program Files/PostgreSQL/17), LOCALDB_PORT (54329),
//      LOCALDB_ADMIN_EMAIL / LOCALDB_ADMIN_PASSWORD (default admin@example.com / admin-local-123).
import { spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, readdirSync, readFileSync, rmSync, writeFileSync, createWriteStream } from "node:fs";
import { join, resolve } from "node:path";
import { Readable } from "node:stream";
import { pipeline } from "node:stream/promises";
import crypto from "node:crypto";
import pg from "pg";

const REPO = resolve(import.meta.dirname, "..", "..");
const HOME = join(REPO, ".localdb");
const PGSQL = join(HOME, "pgsql");
const DATA = join(HOME, "data");
const LOG = join(HOME, "postgres.log");
const PORT = Number(process.env.LOCALDB_PORT ?? 54329);
const DB = process.env.LOCALDB_NAME ?? "agriclimate"; // e.g. agriclimate_test for test runs
const PG_HOME = process.env.PG_HOME ?? "C:/Program Files/PostgreSQL/17";
const POSTGIS_URL = process.env.POSTGIS_URL ?? "https://download.osgeo.org/postgis/windows/pg17/postgis-bundle-pg17-3.6.2x64.zip";
const exe = (n) => join(PGSQL, "bin", process.platform === "win32" ? `${n}.exe` : n);
export const DATABASE_URL = `postgres://postgres@localhost:${PORT}/${DB}`;

function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, { stdio: opts.quiet ? "pipe" : "inherit", encoding: "utf-8", ...opts });
  if (r.status !== 0 && !opts.allowFail) {
    throw new Error(`${cmd} ${args.join(" ")} failed (${r.status})\n${r.stderr ?? ""}`);
  }
  return r;
}

async function setup() {
  mkdirSync(HOME, { recursive: true });
  if (!existsSync(exe("postgres"))) {
    if (!existsSync(join(PG_HOME, "bin"))) throw new Error(`PostgreSQL not found at ${PG_HOME}. Set PG_HOME.`);
    console.log(`Copying PostgreSQL binaries from ${PG_HOME} …`);
    for (const d of ["bin", "lib", "share"]) cpSync(join(PG_HOME, d), join(PGSQL, d), { recursive: true });
  }
  if (!existsSync(join(PGSQL, "share", "extension", "postgis.control"))) {
    const zip = join(HOME, "postgis.zip");
    if (!existsSync(zip)) {
      console.log(`Downloading PostGIS: ${POSTGIS_URL}`);
      const res = await fetch(POSTGIS_URL);
      if (!res.ok) throw new Error(`PostGIS download failed: ${res.status}`);
      await pipeline(Readable.fromWeb(res.body), createWriteStream(zip));
    }
    const tmp = join(HOME, "postgis-extract");
    rmSync(tmp, { recursive: true, force: true });
    mkdirSync(tmp);
    const tar = process.platform === "win32" ? join(process.env.SystemRoot ?? "C:/Windows", "System32", "tar.exe") : "tar";
    run(tar, ["-xf", zip, "-C", tmp]);
    const root = join(tmp, readdirSync(tmp)[0]);
    for (const d of readdirSync(root)) {
      const src = join(root, d);
      // never overwrite PostgreSQL's own DLLs (e.g. OpenSSL): pgcrypto breaks if the bundle's versions replace them
      if (["bin", "lib", "share"].includes(d)) cpSync(src, join(PGSQL, d), { recursive: true, force: false });
      else if (d === "gdal-data" || d === "utils") cpSync(src, join(PGSQL, d), { recursive: true, force: true });
    }
    rmSync(tmp, { recursive: true, force: true });
    console.log("PostGIS installed into the local copy.");
  }
  if (!existsSync(join(DATA, "PG_VERSION"))) {
    console.log("Creating the database cluster …");
    run(exe("initdb"), ["-D", DATA, "-U", "postgres", "-A", "trust", "-E", "UTF8", "--no-locale"], { quiet: true });
    writeFileSync(join(DATA, "postgresql.auto.conf"), `listen_addresses = 'localhost'\nport = ${PORT}\ntimezone = 'Asia/Manila'\n`);
  }
  console.log(`Setup done. Next: npm run db:start && npm run db:reset`);
}

function status() {
  const r = run(exe("pg_ctl"), ["-D", DATA, "status"], { quiet: true, allowFail: true });
  return r.status === 0;
}

function start() {
  if (status()) return console.log(`Already running on port ${PORT}.`);
  // stdio must not be piped: the server inherits the handles and spawnSync would wait for it to exit
  run(exe("pg_ctl"), ["-D", DATA, "-l", LOG, "-w", "start"], { stdio: "ignore" });
  console.log(`Local database running: ${DATABASE_URL}`);
}

function stop() {
  if (!status()) return console.log("Not running.");
  run(exe("pg_ctl"), ["-D", DATA, "-m", "fast", "-w", "stop"], { quiet: true });
  console.log("Stopped.");
}

// ------------------------------------------------------------------ users ---
export function hashPassword(pw) {
  const salt = crypto.randomBytes(16);
  const N = 16384, r = 8, p = 1;
  const hash = crypto.scryptSync(pw, salt, 64, { N, r, p });
  return `scrypt$${N}$${r}$${p}$${salt.toString("base64")}$${hash.toString("base64")}`;
}

async function addUser(client, email, password, role = "editor") {
  if (!email || !password || password.length < 8) throw new Error("Usage: add-user <email> <password (8+ chars)> [editor|admin]");
  if (!["editor", "admin"].includes(role)) throw new Error("Role must be editor or admin");
  const { rows } = await client.query(
    `insert into auth.users (email, encrypted_password) values (lower($1), $2)
     on conflict (email) do update set encrypted_password = excluded.encrypted_password returning id`,
    [email, hashPassword(password)],
  );
  await client.query(
    `insert into profiles (id, email, role) values ($1, lower($2), $3)
     on conflict (id) do update set role = excluded.role, active = true`,
    [rows[0].id, email, role],
  );
  console.log(`User ${email} (${role}) ready.`);
}

// ------------------------------------------------------------------ reset ---
async function connect(db = DB) {
  const c = new pg.Client({ connectionString: `postgres://postgres@localhost:${PORT}/${db}` });
  await c.connect();
  return c;
}

async function loadDemo(c) {
  const demo = join(REPO, "web", "public", "demo");
  const catalog = JSON.parse(readFileSync(join(demo, "catalog.json"), "utf-8")).products;
  for (const entry of catalog) {
    const p = JSON.parse(readFileSync(join(demo, "products", `${entry.id}.json`), "utf-8"));
    const downloads = (p.downloads ?? []).map((d) => ({ ...d, url: d.path ? `/demo/${d.path}` : d.url }));
    const slug = `${p.type}-${p.period.start}`;
    await c.query(
      `insert into products (type, slug, period_kind, period_start, period_end, issue_date)
       values ($1, $2, $3, $4, $5, $6) on conflict (slug) do nothing`,
      [p.type, slug, p.period.kind, p.period.start, p.period.end, p.issued],
    );
    const prod = (await c.query(`select id, current_version, published_version from products where slug = $1`, [slug])).rows[0];
    // the demo version is published only if nobody published a real version of this product
    const publish = prod.published_version === null;
    const version = (prod.current_version ?? 0) + 1;
    const t = p.texts;
    // ENVI exports are made from the three input files: keep the sample inputs with the demo version
    const inputFiles = [];
    if (p.type === "envi") {
      const src = join(REPO, "sample data", "sample input");
      const names = { drought: "drought forecast.csv", damage: "historical damage.xlsx", crops: "standing crops ao sept 15 2026.xlsx" };
      for (const [field, name] of Object.entries(names)) {
        const rel = `demo-envi/${field}__${name}`;
        mkdirSync(join(REPO, "web", ".data", "uploads", "demo-envi"), { recursive: true });
        cpSync(join(src, name), join(REPO, "web", ".data", "uploads", rel));
        inputFiles.push({ field, filename: name, path: rel });
      }
    }
    const v = await c.query(
      `insert into product_versions (product_id, version, status, title, subtitle, notes, disclaimer, sources, recommendations,
         recommendations_source, settings, method, summary, payload, exports, published_at)
       values ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'auto', $10, $11, $12, $13, $14, now()) returning id`,
      [prod.id, version, publish ? "published" : "archived", t.title, t.subtitle, t.notes, t.disclaimer, t.sources, t.recommendations,
        { demo: true, recommendations_draft: t.recommendations, crop_advice_draft: p.crop_advice_draft ?? null,
          input_files: inputFiles, issue_date: p.issued,
          period_start: p.period.start, period_end: p.period.end }, p.method ?? {}, p.summary, p, { downloads, demo: true }],
    );
    await c.query(`update products set current_version = $2, published_version = coalesce(published_version, $3) where id = $1`,
      [prod.id, version, publish ? version : null]);
    await insertValues(c, v.rows[0].id, p);
    console.log(`  demo product ${slug}${p.synthetic ? " (synthetic)" : ""}`);
  }
  const crops = JSON.parse(readFileSync(join(demo, "crops.json"), "utf-8"));
  const own = await c.query(`select 1 from crops_tables where as_of = $1 and source is distinct from 'demo'`, [crops.as_of]);
  if (own.rowCount) {
    console.log("  crops: kept your uploaded table for this date");
  } else {
  await c.query(`delete from crops_tables where source = 'demo'`);
  const ct = await c.query(`insert into crops_tables (as_of, crops, source) values ($1, $2, 'demo') returning id`, [crops.as_of, crops.crops]);
  const rows = Object.entries(crops.values).flatMap(([area_key, v]) => Object.entries(v).map(([crop, ha]) => ({ area_key, crop, ha })));
  await c.query(
    `insert into crop_values (table_id, area_key, crop, area_ha) select $1, area_key, crop, ha from jsonb_to_recordset($2::jsonb) as x(area_key text, crop text, ha numeric)`,
    [ct.rows[0].id, JSON.stringify(rows)],
  );
  console.log(`  crops (${crops.as_of})`);
  }
  const irr = JSON.parse(readFileSync(join(demo, "irrigation.geojson"), "utf-8"));
  const real = await c.query(`select 1 from irrigation_sources where name not like 'DEMO %' limit 1`);
  if (real.rowCount) console.log("  irrigation: kept your uploaded layer");
  else {
    await c.query(`select replace_irrigation_sources($1::jsonb, '[]'::jsonb)`, [JSON.stringify(irr.features)]);
    console.log(`  ${irr.features.length} irrigation sources (synthetic demo records)`);
  }
}

export async function insertValues(c, versionId, p) {
  const rows = p.layers.flatMap((l) =>
    Object.entries(l.values).map(([area_key, v]) => {
      const { value, class: cls, color, ...extra } = v;
      const month = l.id.match(/^m_(\d{4}-\d{2})$/)?.[1];
      const day = l.id.match(/^d_(\d{4}-\d{2}-\d{2})$/)?.[1];
      return {
        layer_id: l.id, area_key, variable: l.variable, unit: l.unit, class_label: cls, class_color: color,
        value: typeof value === "number" ? value : null, value_text: typeof value === "string" ? value : null,
        period_start: day ?? (month ? `${month}-01` : p.period.start), period_end: day ?? (month ? null : p.period.end),
        extra: Object.keys(extra).length ? extra : null,
      };
    }),
  );
  await c.query(
    `insert into product_values (version_id, layer_id, period_start, period_end, area_key, variable, value, value_text, unit, class_label, class_color, extra)
     select $1, layer_id, period_start, period_end, area_key, variable, value, value_text, unit, class_label, class_color, extra
     from jsonb_to_recordset($2::jsonb) as x(layer_id text, period_start date, period_end date, area_key text, variable text,
       value numeric, value_text text, unit text, class_label text, class_color text, extra jsonb)`,
    [versionId, JSON.stringify(rows)],
  );
}

async function reset(withDemo) {
  if (!status()) start();
  const admin = await connect("postgres");
  await admin.query(`drop database if exists ${DB} with (force)`);
  await admin.query(`create database ${DB}`);
  await admin.end();
  const c = await connect();
  const sql = (p) => readFileSync(join(REPO, p), "utf-8");
  console.log("Applying compat.sql, migrations and seed …");
  await c.query(sql("supabase/local/compat.sql"));
  for (const f of readdirSync(join(REPO, "supabase", "migrations")).sort()) await c.query(sql(`supabase/migrations/${f}`));
  await c.query(`create table if not exists local_migrations (name text primary key, applied_at timestamptz default now())`);
  for (const f of readdirSync(join(REPO, "supabase", "migrations")).sort())
    await c.query(`insert into local_migrations (name) values ($1) on conflict do nothing`, [f]);
  await c.query(sql("supabase/seed.sql"));
  const n = (await c.query("select (select count(*) from gazetteer) g, (select count(*) from boundaries) b, (select postgis_lib_version()) v")).rows[0];
  console.log(`  gazetteer ${n.g} municipalities, ${n.b} boundaries, PostGIS ${n.v}`);
  if (withDemo) await loadDemo(c);
  await addUser(c, process.env.LOCALDB_ADMIN_EMAIL ?? "admin@example.com", process.env.LOCALDB_ADMIN_PASSWORD ?? "admin-local-123", "admin");
  await c.end();
  console.log(`\nDatabase ready. In web/.env.local set:\n  DATABASE_URL=${DATABASE_URL}`);
}

const [cmd, ...args] = process.argv.slice(2);
try {
  if (cmd === "setup") await setup();
  else if (cmd === "start") start();
  else if (cmd === "stop") stop();
  else if (cmd === "status") console.log(status() ? `running on port ${PORT} – ${DATABASE_URL}` : "stopped");
  else if (cmd === "reset") await reset(!args.includes("--no-demo"));
  else if (cmd === "migrate") {
    // apply new files from supabase/migrations to an existing database (keeps your data)
    const c = await connect();
    const has = (await c.query(`select to_regclass('public.local_migrations') is not null as t, to_regclass('public.products') is not null as p`)).rows[0];
    await c.query(`create table if not exists local_migrations (name text primary key, applied_at timestamptz default now())`);
    if (!has.t && has.p) await c.query(`insert into local_migrations (name) values ('0001_init.sql') on conflict do nothing`);
    const done = new Set((await c.query(`select name from local_migrations`)).rows.map((r) => r.name));
    for (const f of readdirSync(join(REPO, "supabase", "migrations")).sort()) {
      if (done.has(f)) continue;
      await c.query(readFileSync(join(REPO, "supabase", "migrations", f), "utf-8"));
      await c.query(`insert into local_migrations (name) values ($1)`, [f]);
      console.log(`applied ${f}`);
    }
    console.log("Database is up to date.");
    await c.end();
  }
  else if (cmd === "demo") {
    // refresh the demo products only (after scripts.build_demo) – your own products and versions are kept
    const c = await connect();
    const del = await c.query(`delete from product_versions where settings->>'demo' = 'true' returning product_id`);
    await c.query(`update products p set published_version = null
                   where published_version is not null and not exists (select 1 from product_versions v
                     where v.product_id = p.id and v.version = p.published_version)`);
    await c.query(`delete from products p where not exists (select 1 from product_versions v where v.product_id = p.id)`);
    console.log(`Removed ${del.rowCount} old demo versions.`);
    await loadDemo(c);
    await c.end();
  }
  else if (cmd === "add-user") {
    const c = await connect();
    await addUser(c, args[0], args[1], args[2]);
    await c.end();
  } else if (cmd === "psql") console.log(`"${exe("psql")}" -p ${PORT} -U postgres ${DB}`);
  else console.log("Commands: setup | start | stop | status | reset [--no-demo] | demo | add-user <email> <password> [role] | psql");
} catch (e) {
  console.error(e.message);
  process.exit(1);
}
