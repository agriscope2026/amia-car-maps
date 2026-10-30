"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/client";
import {
  ACTIVITY_STATUSES, BENEFICIARY_TYPES, beneficiariesText, placesSummary, SSL_CROPS,
  type Activity, type SslCropId, type SslData,
} from "@/lib/activities";
import { fmtNumber } from "@/lib/format";
import { dateRange, StatusChip } from "@/components/ActivityBits";
import AreaPicker from "./AreaPicker";
import type { Gazetteer } from "@/lib/types";

type Form = {
  area_keys: string[];
  title: string;
  category: string;
  status: string;
  hazard: string;
  start_date: string;
  end_date: string;
  units: string;
  beneficiary_type: string;
  beneficiaries: string;
  budget: string;
  office: string;
  remarks: string;
};

// every activity is part of the El Niño action plan (hazard "envi")
const EMPTY: Form = {
  area_keys: [], title: "", category: "", status: "to_conduct", hazard: "envi", start_date: "",
  end_date: "", units: "", beneficiary_type: "", beneficiaries: "", budget: "", office: "", remarks: "",
};

const num = (s: string) => (s.trim() === "" ? null : Number(s.replace(/,/g, "")));
const toInput = (f: Form) => ({
  area_keys: f.area_keys, title: f.title, category: f.category, status: f.status, hazard: f.hazard,
  start_date: f.start_date, end_date: f.end_date, units: num(f.units), beneficiary_type: f.beneficiary_type || null,
  beneficiaries: num(f.beneficiaries), budget: num(f.budget),
  office: f.office, remarks: f.remarks,
});
const fromActivity = (a: Activity): Form => ({
  area_keys: a.area_keys, title: a.title, category: a.category ?? "", status: a.status, hazard: a.hazard,
  start_date: a.start_date ?? "", end_date: a.end_date ?? "", units: a.units?.toString() ?? "",
  beneficiary_type: a.beneficiary_type ?? "", beneficiaries: a.beneficiaries?.toString() ?? "",
  budget: a.budget?.toString() ?? "", office: a.office ?? "", remarks: a.remarks ?? "",
});

/** The self-sufficiency (SSL) part of the workbook: SSL per province, rice and corn (and the projected loss when the
 * file has it), with its warnings. */
function SslReport({ ssl }: { ssl: any }) {
  const crops = ["rice", "corn"].filter((c) => ssl.crops?.[c]);
  const provs: string[] = [...new Set<string>(crops.flatMap((c) => Object.keys(ssl.crops[c].provinces)))].sort();
  const pct = (v: number | null | undefined) => (v == null ? "–" : `${fmtNumber(v, 1)}%`);
  return (
    <div style={{ marginTop: 10 }}>
      <h3 style={{ margin: "6px 0" }}>Self-sufficiency (sheet “{ssl.sheet}”)</h3>
      {(ssl.warnings ?? []).map((m: string, i: number) => <p key={i} className="msg warn">{m}</p>)}
      {ssl.ok ? (
        <p className="msg ok">
          SSL figures read: {crops.filter((c) => ssl.crops[c].ok).join(" and ")}. Saving updates the Self-sufficiency (SSL) map
          of the action plan.
        </p>
      ) : (
        <p className="msg err">No SSL could be read – the SSL map keeps its current figures.</p>
      )}
      {provs.length > 0 && (
        <div className="table-scroll" style={{ marginTop: 6 }}>
          <table className="data">
            <thead>
              <tr>
                <th>Province</th>
                {crops.map((c) => <th key={c}>{c === "rice" ? "Rice" : "Corn"} SSL (after the projected loss)</th>)}
              </tr>
            </thead>
            <tbody>
              {provs.map((p) => (
                <tr key={p}>
                  <td>{ssl.crops[crops[0]].provinces[p]?.label ?? p}</td>
                  {crops.map((c) => {
                    const r = ssl.crops[c].provinces[p];
                    return (
                      <td key={c}>
                        {r ? (r.ssl == null ? "no data" : r.final_ssl == null
                          ? `${pct(r.ssl)} (loss not computed${r.effect_error ? `: ${r.effect_error}` : ""})`
                          : `${pct(r.ssl)} (${pct(r.final_ssl)})`) : "–"}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

type SslField = "ssl" | "final_ssl" | "standing_ha" | "yield_loss_mt";
const SSL_FIELDS: { id: SslField; label: string; hint: string }[] = [
  { id: "ssl", label: "SSL (%)", hint: "Self-sufficiency level of the base year – the figure on the map" },
  { id: "final_ssl", label: "SSL after the projected loss (%)", hint: "Final SSL" },
  { id: "standing_ha", label: "Standing crop (ha)", hint: "Reproductive stage, at risk" },
  { id: "yield_loss_mt", label: "Potential yield loss (MT)", hint: "Estimated" },
];
type SslForm = Record<SslCropId, { ssl_year: string; standing_as_of: string; rows: Record<string, Record<SslField, string>> }>;

const sslFormOf = (data: SslData | null, provinces: string[]): SslForm =>
  Object.fromEntries(SSL_CROPS.map(({ id }) => {
    const c = data?.crops[id];
    const rows = Object.fromEntries(provinces.map((p) => {
      const r = c?.provinces[p.toUpperCase()];
      return [p.toUpperCase(), Object.fromEntries(SSL_FIELDS.map((f) => [f.id, r?.[f.id] == null ? "" : String(r[f.id])]))];
    }));
    return [id, { ssl_year: c?.ssl_year ?? "", standing_as_of: c?.standing_as_of ?? "", rows }];
  })) as SslForm;

/** The rice / corn self-sufficiency figures behind the action plan's SSL map, editable in place. An import of the
 * workbook replaces them; an edit here is kept until the next import. */
function SslEditor({ geo, refresh }: { geo: Gazetteer; refresh: number }) {
  const provinces = useMemo(() => [...new Set(geo.gazetteer.map((g) => g.province))].sort(), [geo]);
  const [data, setData] = useState<SslData | null | undefined>(undefined);
  const [form, setForm] = useState<SslForm>(() => sslFormOf(null, provinces));
  const [crop, setCrop] = useState<SslCropId>("rice");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    api<{ ssl: SslData | null }>("/api/admin/ssl")
      .then((r) => { setData(r.ssl); setForm(sslFormOf(r.ssl, provinces)); })
      .catch((e) => setMsg({ ok: false, text: (e as Error).message }));
  }, [refresh, provinces]);

  const initial = useMemo(() => JSON.stringify(sslFormOf(data ?? null, provinces)), [data, provinces]);
  const dirty = data !== undefined && JSON.stringify(form) !== initial;
  const f = form[crop];
  const setCell = (key: string, field: SslField, v: string) =>
    setForm((x) => ({ ...x, [crop]: { ...x[crop], rows: { ...x[crop].rows, [key]: { ...x[crop].rows[key], [field]: v } } } }));
  const setMeta = (k: "ssl_year" | "standing_as_of", v: string) => setForm((x) => ({ ...x, [crop]: { ...x[crop], [k]: v } }));
  const n = (v: string) => (v.trim() === "" ? null : Number(v.replace(/,/g, "")));

  const save = async () => {
    setMsg(null);
    const crops: Record<string, unknown> = {};
    for (const { id, label } of SSL_CROPS) {
      const c = form[id];
      const rows: Record<string, unknown> = {};
      for (const [key, r] of Object.entries(c.rows)) {
        const out = Object.fromEntries(SSL_FIELDS.map((fl) => [fl.id, n(r[fl.id])]));
        const bad = SSL_FIELDS.find((fl) => out[fl.id] !== null && !Number.isFinite(out[fl.id] as number));
        if (bad) {
          setCrop(id);
          return setMsg({ ok: false, text: `${label}, ${key.toLowerCase().replace(/\b\w/g, (m) => m.toUpperCase())}: ${bad.label} is not a number.` });
        }
        rows[key] = out;
      }
      crops[id] = { ssl_year: c.ssl_year, standing_as_of: c.standing_as_of, provinces: rows };
    }
    setBusy(true);
    try {
      const r = await api<{ ssl: SslData }>("/api/admin/ssl", { method: "PUT", json: { crops } });
      setData(r.ssl);
      setForm(sslFormOf(r.ssl, provinces));
      setMsg({ ok: true, text: "Saved – the Self-sufficiency (SSL) map of the action plan is updated." });
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const when = (iso?: string) => (iso ? new Date(iso).toLocaleString("en-PH", { dateStyle: "medium", timeStyle: "short" }) : "");
  return (
    <section id="ssl">
      <h2>Self-sufficiency (SSL) figures</h2>
      <p className="muted small">
        The figures behind the <em>Self-sufficiency (SSL)</em> map of the action plan, per province. They come from the sheet
        “PROJECTED PDN LOSS AND SSL” of the imported workbook; correct them here and click <strong>Save</strong>. The next
        import of the workbook replaces them.
        {data?.file ? ` Last import: ${data.file}${data.saved_at ? ` (${when(data.saved_at)})` : ""}.` : ""}
        {data?.edited_at ? ` Last edited here ${when(data.edited_at)}${data.edited_by ? ` by ${data.edited_by}` : ""}.` : ""}
      </p>
      {data === null && <p className="msg warn">No SSL figures yet – import the workbook above, or type them in and save.</p>}
      <div className="row" style={{ alignItems: "flex-end", gap: 16, flexWrap: "wrap" }}>
        <div className="seg" role="radiogroup" aria-label="Crop" style={{ minWidth: 200 }}>
          {SSL_CROPS.map((c) => (
            <button key={c.id} type="button" role="radio" aria-checked={crop === c.id}
              className={crop === c.id ? "on" : ""} onClick={() => setCrop(c.id)}>
              {c.label}
            </button>
          ))}
        </div>
        <label className="ssl-meta">
          <span className="small muted">SSL year</span>
          <input id={`ssl-year-${crop}`} value={f.ssl_year} onChange={(e) => setMeta("ssl_year", e.target.value)}
            placeholder="2024" style={{ width: 90 }} inputMode="numeric" />
        </label>
        <label className="ssl-meta">
          <span className="small muted">Standing crop as of</span>
          <input id={`ssl-asof-${crop}`} value={f.standing_as_of} onChange={(e) => setMeta("standing_as_of", e.target.value)}
            placeholder="October 15" style={{ width: 150 }} />
        </label>
      </div>
      <div className="table-scroll" style={{ marginTop: 10 }}>
        <table className="data ssl-edit">
          <thead>
            <tr>
              <th>Province</th>
              {SSL_FIELDS.map((fl) => <th key={fl.id} title={fl.hint}>{fl.label}</th>)}
              <th title="SSL minus the SSL after the projected loss">Reduction (points)</th>
            </tr>
          </thead>
          <tbody>
            {provinces.map((p) => {
              const key = p.toUpperCase();
              const r = f.rows[key];
              const ssl = n(r.ssl), fin = n(r.final_ssl);
              const red = ssl != null && fin != null && Number.isFinite(ssl) && Number.isFinite(fin) ? ssl - fin : null;
              return (
                <tr key={key}>
                  <th scope="row">{p}</th>
                  {SSL_FIELDS.map((fl) => (
                    <td key={fl.id}>
                      <input id={`ssl-${crop}-${key}-${fl.id}`} aria-label={`${p} ${fl.label}`} inputMode="decimal"
                        value={r[fl.id]} onChange={(e) => setCell(key, fl.id, e.target.value)} style={{ width: 110 }} />
                    </td>
                  ))}
                  <td className={ssl != null && ssl < 100 ? "neg" : ""}>
                    {red == null ? "–" : fmtNumber(red, 2)}
                    {ssl != null && Number.isFinite(ssl) && <span className="small muted"> · {ssl >= 100 ? "self-sufficient" : "deficit"}</span>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div className="row" style={{ marginTop: 10 }}>
        <button className="btn" disabled={busy || !dirty} onClick={save}>{busy ? "Saving…" : "Save"}</button>
        <button className="btn secondary" disabled={busy || !dirty} onClick={() => { setForm(JSON.parse(initial)); setMsg(null); }}>
          Discard changes
        </button>
        {dirty && <span className="small muted">Unsaved changes</span>}
      </div>
      {msg && <p className={`msg ${msg.ok ? "ok" : "err"}`}>{msg.text}</p>}
    </section>
  );
}

function Importer({ onSaved }: { onSaved: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [replace, setReplace] = useState(false);
  const [res, setRes] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const send = async (save: boolean) => {
    if (!file) return;
    if (save && replace && !confirm("Replace ALL current activities with this file? The current list will be removed.")) return;
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.set("file", file, file.name);
      if (replace) form.set("replace", "1");
      const r = await api(`/api/admin/activities/import${save ? "?save=1" : ""}`, { method: "POST", body: form });
      setRes(r);
      if (save && (r.saved || r.ssl_saved)) onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const rep = res?.report;
  return (
    <section>
      <h2>Import from Excel</h2>
      <p className="muted small">
        The action plan workbook: its first sheet lists the activities, and a sheet “PROJECTED PDN LOSS AND SSL” (if present)
        gives the rice and corn self-sufficiency per province for the SSL map – both are read from the same file. Activities:
        one row per activity: MUNICIPALITY, ACTIVITY and STATUS (To conduct, Ongoing, Completed, Postponed), plus optional
        PROVINCE, CATEGORY, START_DATE, END_DATE,
        BENEFICIARIES, BUDGET_PHP, OFFICE and REMARKS. For several places, separate them with “;” (e.g. Bangued; Tayum), or
        write All in MUNICIPALITY for every municipality of the PROVINCE(s) given (All in both for the whole CAR). Names are
        matched like the map inputs. Validate first, then save. Missing or unreadable details are warnings (named by row): the
        row is still imported with that detail empty; only rows without an activity or a place are skipped.
      </p>
      <div className="row">
        <input
          type="file"
          accept=".xlsx,.xls,.xlsm,.csv"
          aria-label="Activities file"
          onChange={(e) => {
            setFile(e.target.files?.[0] ?? null);
            setRes(null);
          }}
        />
        <a href="/api/templates/activities">Download template</a>
      </div>
      <label className="check" style={{ marginTop: 8 }}>
        <input type="checkbox" checked={replace} onChange={(e) => setReplace(e.target.checked)} />
        <span>Replace all current activities with this file (otherwise the rows are added to the list)</span>
      </label>
      <div className="row" style={{ marginTop: 10 }}>
        <button className="btn secondary" disabled={!file || busy} onClick={() => send(false)}>
          Validate
        </button>
        <button className="btn" disabled={!file || busy || !(res?.ok || res?.ssl?.ok) || res?.saved > 0 || res?.ssl_saved}
          onClick={() => send(true)}>
          {replace ? "Save and replace" : "Save"}
        </button>
      </div>
      {error && <p className="msg err">{error}</p>}
      {res && (res.saved > 0 || res.ssl_saved) && (
        <p className="msg ok">
          Saved{res.saved > 0 ? ` ${res.saved} activities` : ""}{res.saved > 0 && res.ssl_saved ? " and" : ""}
          {res.ssl_saved ? " the self-sufficiency (SSL) figures – the SSL map of the action plan is updated" : ""}.
          {!res.ok && res.ssl_saved ? " The activity rows were not saved: fix the errors below and import again." : ""}
          {res.ok && res.ssl && !res.ssl.ok ? " The SSL sheet was not saved (see below)." : ""}
        </p>
      )}
      {res?.ssl && <SslReport ssl={res.ssl} />}
      {rep && (
        <div style={{ marginTop: 8 }}>
          {(rep.errors ?? []).map((m: string, i: number) => (
            <p key={i} className="msg err">{m}</p>
          ))}
          {(rep.warnings ?? []).map((m: string, i: number) => (
            <p key={i} className="msg warn">{m}</p>
          ))}
          {res.ok && !res.saved && (
            <p className="msg ok">
              {`Activities valid: ${res.count} activities in ${rep.municipalities} municipalities`}
              {!res.saved &&
                ` (${ACTIVITY_STATUSES.map((s) => `${rep.by_status?.[s.id] ?? 0} ${s.label.toLowerCase()}`).join(", ")}).`}
            </p>
          )}
          {res.ok && !res.saved && res.rows?.length > 0 && (
            <div className="table-scroll" style={{ maxHeight: 320, marginTop: 6 }}>
              <table className="data">
                <thead>
                  <tr>
                    <th>Row</th>
                    <th>Places</th>
                    <th>Activity</th>
                    <th>Status</th>
                    <th>Dates</th>
                  </tr>
                </thead>
                <tbody>
                  {res.rows.slice(0, 200).map((r: any, i: number) => (
                    <tr key={i}>
                      <td>{r.row}</td>
                      <td>{(r.area_labels ?? []).join(", ")}</td>
                      <td>{r.title}</td>
                      <td><StatusChip status={r.status} /></td>
                      <td>{dateRange(r)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

export default function ActivitiesAdmin({ geo }: { geo: Gazetteer }) {
  const [sslKey, setSslKey] = useState(0); // reloads the SSL table after an import
  const [list, setList] = useState<Activity[] | null>(null);
  const [form, setForm] = useState<Form>(EMPTY);
  const [editing, setEditing] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [q, setQ] = useState("");
  const [fProv, setFProv] = useState("");
  const [fStatus, setFStatus] = useState("");

  const byKey = useMemo(() => new Map(geo.gazetteer.map((g) => [g.area_key, g])), [geo]);
  const provinces = useMemo(() => [...new Set(geo.gazetteer.map((g) => g.province))].sort(), [geo]);
  const categories = useMemo(() => [...new Set((list ?? []).map((a) => a.category).filter(Boolean) as string[])].sort(), [list]);
  const offices = useMemo(() => [...new Set((list ?? []).map((a) => a.office).filter(Boolean) as string[])].sort(), [list]);

  const load = () =>
    api<{ activities: Activity[] }>("/api/admin/activities")
      .then((r) => setList(r.activities))
      .catch((e) => setMsg({ kind: "err", text: (e as Error).message }));
  useEffect(() => {
    load();
  }, []);

  const set = (k: Exclude<keyof Form, "area_keys">, v: string) => setForm((f) => ({ ...f, [k]: v }));

  const save = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setMsg(null);
    try {
      if (editing) await api(`/api/admin/activities/${editing}`, { method: "PUT", json: toInput(form) });
      else await api("/api/admin/activities", { method: "POST", json: toInput(form) });
      setMsg({ kind: "ok", text: editing ? "Activity updated." : `Added: ${form.title}.` });
      // keep the place and status for the next entry, clear the rest
      setForm(editing ? EMPTY : { ...EMPTY, area_keys: form.area_keys, status: form.status, hazard: form.hazard });
      setEditing(null);
      load();
    } catch (err) {
      setMsg({ kind: "err", text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const quickStatus = async (a: Activity, status: string) => {
    try {
      const { id, source: _s, created_by: _c, created_at: _ca, updated_at: _u, ...rest } = a;
      await api(`/api/admin/activities/${id}`, { method: "PUT", json: { ...rest, status } });
      load();
    } catch (err) {
      setMsg({ kind: "err", text: (err as Error).message });
    }
  };

  const remove = async (a: Activity) => {
    if (!confirm(`Delete “${a.title}” (${placesSummary(a.area_keys, geo.gazetteer, 3)})?`)) return;
    try {
      await api(`/api/admin/activities/${a.id}`, { method: "DELETE" });
      load();
    } catch (err) {
      setMsg({ kind: "err", text: (err as Error).message });
    }
  };

  const shown = useMemo(() => {
    const s = q.trim().toLowerCase();
    return (list ?? []).filter((a) => {
      const towns = a.area_keys.map((k) => byKey.get(k));
      if (fProv && !towns.some((g) => g?.province === fProv)) return false;
      if (fStatus && a.status !== fStatus) return false;
      return !s || [a.title, a.category, a.office, a.remarks, ...towns.map((g) => g?.name)].some((x) => x?.toLowerCase().includes(s));
    });
  }, [list, q, fProv, fStatus, byKey]);

  return (
    <>
      <section id="encode">
        <h2>{editing ? "Edit activity" : "Add an activity"}</h2>
        <form onSubmit={save}>
          <div className="form-grid">
            <div className="field" style={{ gridColumn: "1 / -1" }}>
              <label>Where does it take place? *</label>
              <AreaPicker towns={geo.gazetteer} value={form.area_keys} onChange={(keys) => setForm((f) => ({ ...f, area_keys: keys }))} />
            </div>
            <div className="field" style={{ gridColumn: "1 / -1" }}>
              <label htmlFor="a-title">Activity *</label>
              <input id="a-title" required maxLength={300} value={form.title} onChange={(e) => set("title", e.target.value)}
                placeholder="e.g. Distribution of drought-tolerant rice seeds" />
            </div>
            <div className="field">
              <label htmlFor="a-status">Status *</label>
              <select id="a-status" value={form.status} onChange={(e) => set("status", e.target.value)}>
                {ACTIVITY_STATUSES.map((s) => (
                  <option key={s.id} value={s.id}>{s.label}</option>
                ))}
              </select>
            </div>
            <div className="field">
              <label htmlFor="a-cat">Category</label>
              <input id="a-cat" list="a-cats" maxLength={100} value={form.category} onChange={(e) => set("category", e.target.value)}
                placeholder="e.g. Training" />
              <datalist id="a-cats">
                {["Training", "Distribution of inputs", "Infrastructure", "Advisory", "Insurance enrolment", "Water management", ...categories]
                  .filter((c, i, all) => all.indexOf(c) === i)
                  .map((c) => <option key={c} value={c} />)}
              </datalist>
            </div>
            <div className="field">
              <label htmlFor="a-office">Implementing office</label>
              <input id="a-office" list="a-offices" maxLength={200} value={form.office} onChange={(e) => set("office", e.target.value)}
                placeholder="e.g. DA-RFO-CAR AMIA" />
              <datalist id="a-offices">
                {offices.map((c) => <option key={c} value={c} />)}
              </datalist>
            </div>
            <div className="field">
              <label htmlFor="a-start">Start date</label>
              <input id="a-start" type="date" value={form.start_date} onChange={(e) => set("start_date", e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="a-end">End date</label>
              <input id="a-end" type="date" min={form.start_date || undefined} value={form.end_date} onChange={(e) => set("end_date", e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="a-units">No. of units</label>
              <input id="a-units" type="number" min={0} step="any" value={form.units} onChange={(e) => set("units", e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="a-bentype">Beneficiaries are</label>
              <select id="a-bentype" value={form.beneficiary_type} onChange={(e) => set("beneficiary_type", e.target.value)}>
                <option value="">– not specified –</option>
                {BENEFICIARY_TYPES.map((b) => <option key={b.id} value={b.id}>{b.label}</option>)}
              </select>
            </div>
            <div className="field">
              <label htmlFor="a-ben">
                {form.beneficiary_type === "fca" ? "Number of FCAs" : form.beneficiary_type === "individual" ? "Number of farmers" : "Number of beneficiaries"}
              </label>
              <input id="a-ben" type="number" min={0} step={1} value={form.beneficiaries} onChange={(e) => set("beneficiaries", e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="a-budget">Budget (PHP)</label>
              <input id="a-budget" type="number" min={0} step="0.01" value={form.budget} onChange={(e) => set("budget", e.target.value)} />
            </div>
            <div className="field" style={{ gridColumn: "1 / -1" }}>
              <label htmlFor="a-rem">Remarks</label>
              <input id="a-rem" maxLength={1000} value={form.remarks} onChange={(e) => set("remarks", e.target.value)} />
            </div>
          </div>
          <div className="row" style={{ marginTop: 12 }}>
            <button className="btn" disabled={busy || !form.area_keys.length}>{editing ? "Save changes" : "Add activity"}</button>
            {editing && (
              <button type="button" className="btn secondary" onClick={() => { setEditing(null); setForm(EMPTY); }}>
                Cancel
              </button>
            )}
          </div>
          {msg && <p className={`msg ${msg.kind}`}>{msg.text}</p>}
        </form>
      </section>

      <Importer onSaved={() => { load(); setSslKey((k) => k + 1); }} />

      <SslEditor geo={geo} refresh={sslKey} />

      <section>
        <h2>Activities {list ? `(${list.length})` : ""}</h2>
        <div className="row act-filters" style={{ marginBottom: 10 }}>
          <input className="act-search" type="search" placeholder="Search activity, office, municipality…" value={q}
            onChange={(e) => setQ(e.target.value)} aria-label="Search activities" />
          <select value={fProv} onChange={(e) => setFProv(e.target.value)} aria-label="Province">
            <option value="">All provinces</option>
            {provinces.map((p) => <option key={p}>{p}</option>)}
          </select>
          <select value={fStatus} onChange={(e) => setFStatus(e.target.value)} aria-label="Status">
            <option value="">All statuses</option>
            {ACTIVITY_STATUSES.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
          </select>
          <a href="/activities">View the El Niño Action Plan Dashboard →</a>
        </div>
        {list === null ? (
          <p className="muted">Loading…</p>
        ) : shown.length === 0 ? (
          <p className="muted">{list.length ? "No activities match the filters." : "No activities yet. Add one above or import an Excel list."}</p>
        ) : (
          <div className="table-scroll">
            <table className="data">
              <thead>
                <tr>
                  <th>Places</th>
                  <th>Activity</th>
                  <th>Status</th>
                  <th>Dates</th>
                  <th>Units</th>
                  <th>Beneficiaries</th>
                  <th>Budget (PHP)</th>
                  <th>Office</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {shown.map((a) => {
                  return (
                    <tr key={a.id}>
                      <td className="act-places">
                        {placesSummary(a.area_keys, geo.gazetteer, 3)}
                        {a.area_keys.length > 1 && <div className="small muted">{a.area_keys.length} municipalities</div>}
                      </td>
                      <td>
                        {a.title}
                        {a.category && <div className="small muted">{a.category}</div>}
                      </td>
                      <td>
                        <select className="act-quick" value={a.status} onChange={(e) => quickStatus(a, e.target.value)}
                          aria-label={`Status of ${a.title}`}>
                          {ACTIVITY_STATUSES.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
                        </select>
                      </td>
                      <td className="small">{dateRange(a)}</td>
                      <td>{a.units != null ? fmtNumber(a.units, 0) : ""}</td>
                      <td>{beneficiariesText(a.beneficiaries, a.beneficiary_type)}</td>
                      <td>{a.budget != null ? fmtNumber(a.budget, 2) : ""}</td>
                      <td className="small">{a.office}</td>
                      <td>
                        <div className="row" style={{ flexWrap: "nowrap", gap: 6 }}>
                          <button className="btn secondary small" onClick={() => {
                            setEditing(a.id);
                            setForm(fromActivity(a));
                            document.getElementById("encode")?.scrollIntoView({ behavior: "smooth" });
                          }}>
                            Edit
                          </button>
                          <button className="btn danger small" onClick={() => remove(a)}>Delete</button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
