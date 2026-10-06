// End-to-end test, one run per product: upload (or feed) → validate → draft → edit text → export →
// publish → appears on the public dashboard API → export downloads work.
// Needs the web app (BASE, default http://localhost:3000) and the worker running, plus admin credentials.
// Usage: E2E_EMAIL=… E2E_PASSWORD=… node scripts/e2e.mjs [envi rainfall_dekad rainfall_seasonal drought feed]
import { readFileSync } from "node:fs";
import { basename, join } from "node:path";

const BASE = process.env.BASE ?? "http://localhost:3000";
const ROOT = join(import.meta.dirname, "..", "..");
const SAMPLE = join(ROOT, "sample data", "sample input");
const DEMO = join(ROOT, "worker", "data", "sample");
let cookie = "";

async function call(path, { method = "GET", json, form } = {}) {
  const headers = { Origin: BASE, Cookie: cookie };
  let body;
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  } else if (form) body = form;
  const r = await fetch(BASE + path, { method, headers, body, redirect: "manual" });
  const set = r.headers.getSetCookie?.() ?? [];
  if (set.length) cookie = set.map((c) => c.split(";")[0]).join("; ");
  const data = r.headers.get("content-type")?.includes("json") ? await r.json() : await r.arrayBuffer();
  if (!r.ok) throw new Error(`${method} ${path} → ${r.status}: ${JSON.stringify(data.error ?? data).slice(0, 400)}`);
  return data;
}

const file = (p) => new File([readFileSync(p)], basename(p));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function assert(cond, msg) {
  if (!cond) throw new Error(`Assertion failed: ${msg}`);
}

const CASES = {
  envi: {
    settings: { issue_date: "2026-09-15", period_start: "2026-10", period_end: "2027-03", weights: { hazard: 1 / 3, damage: 1 / 3, crops: 1 / 3 }, classification: "equal" },
    files: { drought: join(SAMPLE, "drought forecast.csv"), damage: join(SAMPLE, "historical damage.xlsx"), crops: join(SAMPLE, "standing crops ao sept 15 2026.xlsx") },
    check: (p) => {
      const top = p.summary.top10[0];
      assert(top.area === "Tabuk City" && top.envi.toFixed(3) === "0.806" && top.class === "Very High", "ENVI top area Tabuk City 0.806 Very High");
      const c = p.summary.class_counts;
      assert([c["Very Low"], c.Low, c.Moderate, c.High, c["Very High"]].join("/") === "14/44/11/7/1", "ENVI class counts 14/44/11/7/1");
    },
  },
  rainfall_dekad: {
    settings: { issue_date: "2026-09-30", period_start: "2026-10-01", period_end: "2026-10-10" },
    files: { file: join(DEMO, "DEMO_rainfall_10day_2026-10-01.xlsx") },
    check: (p) => {
      assert(p.layers.length === 11 && p.layers[0].id === "d_2026-10-01" && p.layers[10].id === "total", "10 daily maps + 10-day total");
      assert(p.layers[0].unit === "mm" && p.layers[0].legend.classes[1].desc === "Very Light Rain", "DA daily rainfall legend");
    },
  },
  rainfall_seasonal: {
    settings: { issue_date: "2026-09-30", period_start: "2026-10", period_end: "2027-03" },
    files: { file: join(DEMO, "DEMO_rainfall_seasonal_2026-10_2027-03.xlsx") },
    check: (p) => assert(p.layers.length === 8 && p.layers.some((l) => l.id === "season_total"), "6 months + total + % normal"),
  },
  drought: {
    settings: { issue_date: "2026-09-15", period_start: "2026-10" },
    files: { file: join(SAMPLE, "drought forecast.csv") },
    check: (p) => assert(p.layers.length === 6 && p.layers[3].values["ABRA|BANGUED"].class === "Drought", "6 monthly maps, CAR only"),
  },
};

async function publishFlow(name, preview, settings, check) {
  assert(preview.payload.ok, `${name}: validation ok – ${JSON.stringify(preview.payload.report).slice(0, 300)}`);
  check?.(preview.payload);
  const draft = await call("/api/admin/drafts", { method: "POST", json: { ...preview, settings } });
  // tampering is refused
  let refused = false;
  try {
    await call("/api/admin/drafts", { method: "POST", json: { ...preview, payload: { ...preview.payload, title: "x" }, settings } });
  } catch {
    refused = true;
  }
  assert(refused, "tampered preview refused");
  await call(`/api/admin/versions/${draft.id}`, { method: "PATCH", json: { texts: { notes: `E2E test note (${name})` } } });
  const { job } = await call(`/api/admin/versions/${draft.id}/export`, { method: "POST" });
  let st;
  for (let i = 0; i < 300; i++) {
    st = await call(`/api/admin/jobs/${job}?version=${draft.id}`);
    if (st.status === "done" || st.status === "error") break;
    await sleep(2000);
  }
  assert(st.status === "done", `${name}: export finished (${st.error ?? st.status})`);
  assert(st.labels_ok, `${name}: label report 83 labels, 0 overlaps`);
  await call(`/api/admin/versions/${draft.id}/publish`, { method: "POST" });
  const saved = cookie;
  cookie = ""; // public, signed out
  const cat = await call("/api/public/catalog");
  const entry = cat.products.find((p) => p.id === draft.id);
  assert(entry, `${name}: on the public catalog`);
  const pub = await call(`/api/public/products/${draft.id}`);
  assert(pub.texts.notes === `E2E test note (${name})`, "edited text published");
  // exports = map images and PDFs only: one PNG + one PDF per map, one ZIP
  const real = pub.downloads.filter((d) => !d.preview);
  assert(real.filter((d) => d.kind === "png").length === pub.layers.length, "one PNG per map");
  assert(real.filter((d) => d.kind === "pdf").length === pub.layers.length, "one PDF per map");
  assert(real.every((d) => ["png", "pdf", "zip", "presentation", "presentation_pdf", "poster", "poster_pdf"].includes(d.kind)), "only map images, PDFs and the ZIP");
  const pdf = real.find((d) => d.kind === "pdf");
  const bytes = new Uint8Array(await call(pdf.url));
  assert(String.fromCharCode(...bytes.slice(0, 4)) === "%PDF", "public PDF download");
  const zipD = real.find((d) => d.kind === "zip");
  const zip = new Uint8Array(await call(zipD.url));
  assert(zip[0] === 0x50 && zip[1] === 0x4b, "ZIP of all maps");
  if (pub.type === "envi") {
    const pres = real.find((d) => d.kind === "presentation");
    assert(pres && real.find((d) => d.kind === "poster"), "ENVI presentation and poster");
    const png = new Uint8Array(await call(pres.url));
    assert(png[1] === 0x50 && png[2] === 0x4e && png[3] === 0x47, "presentation is a PNG");
    for (const k of ["presentation_pdf", "poster_pdf"]) {
      const d = real.find((x) => x.kind === k);
      assert(d, `ENVI ${k}`);
      const b = new Uint8Array(await call(d.url));
      assert(String.fromCharCode(...b.slice(0, 4)) === "%PDF", `${k} is a PDF`);
    }
  }
  cookie = saved;

  // a published version stays editable: new recommendations go live at once, exports can be regenerated
  if (name === "drought") {
    const recs = "- E2E edited recommendation on a published version.";
    const rice = "E2E rice advice: drain paddies before heavy rain.";
    assert(preview.payload.texts.advice_rice && preview.payload.texts.advice_corn && preview.payload.texts.advice_hvc,
      "farm recommendations drafted for rice, corn and HVC");
    await call(`/api/admin/versions/${draft.id}`, { method: "PATCH", json: { texts: { recommendations: recs, advice_rice: rice } } });
    cookie = "";
    const live = await call(`/api/public/products/${draft.id}`);
    cookie = saved;
    assert(live.texts.recommendations === recs, "edited recommendations are live on the dashboard");
    assert(live.texts.advice_rice === rice, "edited rice farm recommendation is live");
    assert(live.downloads.length >= 3, "published files stay available while out of date");
    const v1 = await call(`/api/admin/versions/${draft.id}`);
    assert(v1.status === "published" && v1.exports.stale === true, "published exports marked out of date");
    const { job: job2 } = await call(`/api/admin/versions/${draft.id}/export`, { method: "POST" });
    let st2;
    for (let i = 0; i < 300; i++) {
      st2 = await call(`/api/admin/jobs/${job2}?version=${draft.id}`);
      if (st2.status === "done" || st2.status === "error") break;
      await sleep(2000);
    }
    assert(st2.status === "done", "published exports regenerated");
    const v2 = await call(`/api/admin/versions/${draft.id}`);
    assert(v2.status === "published" && !v2.exports.stale && v2.exports.job_id === job2, "new files attached, no longer stale");
    console.log(`  ✓ edited the published version and regenerated its exports`);
    // archived versions can be deleted by admins; published ones cannot
    let refusedPub = false;
    try {
      await call(`/api/admin/versions/${draft.id}`, { method: "DELETE" });
    } catch {
      refusedPub = true;
    }
    assert(refusedPub, "a published version cannot be deleted");
    await call(`/api/admin/versions/${draft.id}/unpublish`, { method: "POST" });
    await call(`/api/admin/versions/${draft.id}`, { method: "DELETE" });
    let gone = false;
    try {
      await call(`/api/admin/versions/${draft.id}`);
    } catch {
      gone = true;
    }
    assert(gone, "archived version deleted");
    console.log(`  ✓ unpublished and deleted the version`);
  }
  console.log(`✓ ${name}: ${pub.period.label} published as ${draft.id} (${pub.downloads.length} downloads)`);
  return draft.id;
}

const which = process.argv.slice(2).length ? process.argv.slice(2) : [...Object.keys(CASES), "feed"];
// unauthenticated admin calls are refused
try {
  await call("/api/admin/drafts", { method: "POST", json: {} });
  throw new Error("unauthenticated call was accepted");
} catch (e) {
  assert(/401/.test(e.message), "admin API needs a session");
}
await call("/api/auth/login", { method: "POST", json: { email: process.env.E2E_EMAIL, password: process.env.E2E_PASSWORD } });
for (const name of which) {
  if (name === "pagasa") {
    const preview = await call("/api/admin/feed", { method: "POST", json: { type: "rainfall_seasonal" } });
    await publishFlow("PAGASA seasonal (live)", preview, { source: "pagasa" }, (p) => {
      assert(p.type === "rainfall_seasonal" && p.report.n_matched === 77, "PAGASA: 77 municipalities");
      assert(p.pagasa?.table?.length >= 6 * 3 && p.pagasa.images?.mm, "PAGASA: values table + image link for checking");
    });
    continue;
  }
  if (name === "feed") {
    const preview = await call("/api/admin/feed", { method: "POST" });
    await publishFlow("feed (10-day rainfall)", preview, { source: "feed" }, (p) => assert(p.report.n_matched === 77, "feed: 77 municipalities"));
    continue;
  }
  const c = CASES[name];
  const form = new FormData();
  form.set("settings", JSON.stringify(c.settings));
  for (const [k, p] of Object.entries(c.files)) form.set(k, file(p));
  const preview = await call(`/api/admin/preview/${name}`, { method: "POST", form });
  await publishFlow(name, preview, c.settings, c.check);
}
console.log("all end-to-end checks passed");
