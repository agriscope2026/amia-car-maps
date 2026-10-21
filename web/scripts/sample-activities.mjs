// Sample activities for local development only (never in the migrations or seed.sql that production uses).
// They follow the published maps: most at-risk municipalities get one to three activities, a few are left without
// one (so the "no activity yet" list is not empty), and some other places get one too. Dates and statuses fit
// today's date: done before, ongoing now, to conduct later, a few postponed. Rows are tagged SOURCE so
// `node scripts/localdb.mjs activities-demo --clear` removes exactly them.
import { readFileSync } from "node:fs";
import { join } from "node:path";

export const SOURCE = "sample (dev)";

const ACTIVITIES = [
  // [title, category, map]
  ["Distribution of drought-tolerant rice seeds", "Distribution of inputs", "envi"],
  ["Distribution of early-maturing corn seeds", "Distribution of inputs", "envi"],
  ["Pre-positioning of vegetable seeds and fertilizer", "Distribution of inputs", "envi"],
  ["Climate-resilient farming training (AMIA village)", "Training", "envi"],
  ["Water-saving irrigation (AWD) demonstration", "Training", "drought"],
  ["El Niño farm advisory briefing for farmers", "Advisory", "general"],
  ["Farm weather outlook briefing with the MDRRMO", "Advisory", "general"],
  ["Repair of small water impounding project (SWIP)", "Water management", "drought"],
  ["Desilting of communal irrigation canals", "Water management", "drought"],
  ["Rainwater harvesting facilities for vegetable farms", "Water management", "envi"],
  ["Installation of solar-powered irrigation pump", "Infrastructure", "drought"],
  ["PCIC crop insurance enrolment drive", "Insurance enrolment", "envi"],
  ["Forage and water reserves for livestock", "Livestock support", "drought"],
  ["Clearing of farm drainage before heavy rain", "Infrastructure", "rainfall_seasonal"],
  ["Heavy-rain preparedness briefing", "Advisory", "rainfall_dekad"],
];

/** Small deterministic random generator, so every reset gives the same sample. */
function rng(seed) {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const iso = (d) => d.toISOString().slice(0, 10);
const keys0 = (risk) => [...risk.entries()].filter(([, v]) => v === "envi").map(([k]) => k).sort();
const addDays = (d, n) => new Date(d.getTime() + n * 86400000);

/** Insert the sample (replacing an earlier one). Returns the number of activities. */
export async function seedSampleActivities(client, repo) {
  const geo = JSON.parse(readFileSync(join(repo, "web", "public", "geo", "car.json"), "utf-8"));
  const towns = new Map(geo.gazetteer.map((g) => [g.area_key, g]));
  // class of each municipality on the latest published ENVI season map and its worst drought month
  const risk = new Map();
  const rows = (await client.query(`
    select pv.area_key, p.type, pv.class_label
    from product_values pv join product_versions v on v.id = pv.version_id join products p on p.id = v.product_id
    where v.status = 'published' and (
      (p.type = 'envi' and pv.layer_id = 'envi') or (p.type = 'drought' and pv.layer_id like 'm\\_%'))`)).rows;
  for (const r of rows) {
    if (r.type === "envi" && ["High", "Very High"].includes(r.class_label)) risk.set(r.area_key, "envi");
    else if (r.type === "drought" && ["Dry spell", "Drought"].includes(r.class_label) && !risk.has(r.area_key)) risk.set(r.area_key, "drought");
  }
  const rand = rng(20261020);
  const pick = (xs) => xs[Math.floor(rand() * xs.length)];
  const today = new Date();
  const acts = [];
  const keys = [...towns.keys()].sort();
  for (const k of keys) {
    const atRisk = risk.get(k) === "envi"; // High or Very High on the ENVI season map
    // at risk: one to four activities, about one in four places none yet; elsewhere about one in three gets one or two
    const n = atRisk ? (rand() < 0.25 ? 0 : 1 + Math.floor(rand() * 4)) : rand() < 0.3 ? 1 + Math.floor(rand() * 2) : 0;
    const g = towns.get(k);
    for (let i = 0; i < n; i++) {
      const [title, category, hazard] = pick(ACTIVITIES);
      // start between 90 days ago and 120 days ahead; status from the dates
      const start = addDays(today, Math.round(-90 + rand() * 210));
      const days = pick([1, 3, 14, 30, 60, 90, 120]);
      const end = addDays(start, days - 1);
      let status = end < today ? "completed" : start > today ? "to_conduct" : "ongoing";
      if (rand() < 0.07) status = "postponed";
      const farmers = pick([25, 40, 60, 80, 120, 150, 200, 300]);
      const budget = category === "Infrastructure" || category === "Water management"
        ? pick([350000, 600000, 1200000, 2500000])
        : category === "Distribution of inputs" ? pick([75000, 150000, 280000]) : pick([15000, 25000, 40000, null]);
      const office = pick(["DA-RFO-CAR AMIA", "DA-RFO-CAR Rice Program", `PAO ${g.province}`, `MAO ${g.name}`, "NIA-CAR", "BSWM"]);
      acts.push({
        area_keys: [k], title, category, status, hazard, start_date: iso(start), end_date: days > 1 ? iso(end) : null,
        beneficiaries: farmers, budget, office: category === "Insurance enrolment" ? "PCIC with DA-RFO-CAR" : office,
        remarks: status === "postponed" ? "Moved to next quarter – waiting for funds" : null,
      });
    }
  }
  // activities that cover several places: neighbouring towns of a province, and whole provinces
  const provinces = [...new Set(geo.gazetteer.map((g) => g.province))].sort();
  const multi = [
    ["Province-wide El Niño preparedness forum", "Advisory", "envi", 1, 0, 1, 30000, "DA-RFO-CAR AMIA"],
    ["Cluster training on water-saving rice farming", "Training", "drought", 0, 3, 14, 180000, "DA-RFO-CAR Rice Program"],
    ["PCIC crop insurance enrolment caravan", "Insurance enrolment", "envi", 1, 0, 45, 450000, "PCIC with DA-RFO-CAR"],
    ["Seed buffer stock for the upland towns", "Distribution of inputs", "envi", 0, 4, 30, 520000, "DA-RFO-CAR AMIA"],
  ];
  for (const [title, category, hazard, nProv, nTowns, days, budget, office] of multi) {
    let keys;
    if (nProv) {
      // province-wide activities go to the provinces with the fewest places at risk, so the sample keeps some gaps
      const atRisk = (p) => keys0(risk).filter((k) => towns.get(k)?.province === p).length;
      const ps = [...provinces].sort((a, b) => atRisk(a) - atRisk(b) || rand() - 0.5).slice(0, nProv);
      keys = geo.gazetteer.filter((g) => ps.includes(g.province)).map((g) => g.area_key);
    } else {
      // neighbouring at-risk towns of one province
      const risky = keys0(risk).filter((k) => towns.get(k));
      const prov = towns.get(pick(risky))?.province;
      keys = risky.filter((k) => towns.get(k).province === prov).slice(0, nTowns);
    }
    const start = addDays(today, Math.round(-30 + rand() * 90));
    const end = addDays(start, days - 1);
    const status = end < today ? "completed" : start > today ? "to_conduct" : "ongoing";
    acts.push({ area_keys: keys.sort(), title, category, status, hazard, start_date: iso(start), end_date: days > 1 ? iso(end) : null,
      beneficiaries: keys.length * pick([40, 60, 90]), budget, office, remarks: null });
  }

  await client.query("begin");
  try {
    await client.query("delete from activities where source = $1", [SOURCE]);
    await client.query(
      `insert into activities (area_keys, title, category, status, hazard, start_date, end_date, beneficiaries, budget,
         office, remarks, source, created_by_email)
       select area_keys, title, category, status, hazard, start_date, end_date, beneficiaries, budget, office, remarks,
         $2, 'sample@localhost'
       from jsonb_to_recordset($1::jsonb) as x(area_keys text[], title text, category text, status text, hazard text,
         start_date date, end_date date, beneficiaries int, budget numeric, office text, remarks text)`,
      [JSON.stringify(acts), SOURCE],
    );
    await client.query("commit");
  } catch (e) {
    await client.query("rollback");
    throw e;
  }
  return { count: acts.length, places: new Set(acts.flatMap((a) => a.area_keys)).size, atRisk: [...risk.values()].filter((v) => v === "envi").length };
}

export async function clearSampleActivities(client) {
  return (await client.query("delete from activities where source = $1", [SOURCE])).rowCount;
}
