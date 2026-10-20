"use client";

import { useEffect, useMemo, useState } from "react";
import { api } from "@/lib/client";
import { ACTIVITY_HAZARDS, ACTIVITY_STATUSES, hazardLabel, placesSummary, type Activity } from "@/lib/activities";
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
  beneficiaries: string;
  budget: string;
  office: string;
  remarks: string;
};

const EMPTY: Form = {
  area_keys: [], title: "", category: "", status: "to_conduct", hazard: "general", start_date: "",
  end_date: "", beneficiaries: "", budget: "", office: "", remarks: "",
};

const num = (s: string) => (s.trim() === "" ? null : Number(s.replace(/,/g, "")));
const toInput = (f: Form) => ({
  area_keys: f.area_keys, title: f.title, category: f.category, status: f.status, hazard: f.hazard,
  start_date: f.start_date, end_date: f.end_date, beneficiaries: num(f.beneficiaries), budget: num(f.budget),
  office: f.office, remarks: f.remarks,
});
const fromActivity = (a: Activity): Form => ({
  area_keys: a.area_keys, title: a.title, category: a.category ?? "", status: a.status, hazard: a.hazard,
  start_date: a.start_date ?? "", end_date: a.end_date ?? "", beneficiaries: a.beneficiaries?.toString() ?? "",
  budget: a.budget?.toString() ?? "", office: a.office ?? "", remarks: a.remarks ?? "",
});

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
      if (save && r.saved) onSaved();
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
        One row per activity: MUNICIPALITY, ACTIVITY and STATUS (To conduct, Ongoing, Completed, Postponed), plus optional
        PROVINCE, CATEGORY, MAP (ENVI, Drought, 10-day rainfall, Seasonal rainfall or General), START_DATE, END_DATE,
        BENEFICIARIES, BUDGET_PHP, OFFICE and REMARKS. For several places, separate them with “;” (e.g. Bangued; Tayum), or
        write All in MUNICIPALITY for every municipality of the PROVINCE(s) given (All in both for the whole CAR). Names are
        matched like the map inputs. Validate first, then save.
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
        <button className="btn" disabled={!file || busy || !res?.ok || res?.saved > 0} onClick={() => send(true)}>
          {replace ? "Save and replace" : "Save"}
        </button>
      </div>
      {error && <p className="msg err">{error}</p>}
      {rep && (
        <div style={{ marginTop: 8 }}>
          {(rep.errors ?? []).map((m: string, i: number) => (
            <p key={i} className="msg err">{m}</p>
          ))}
          {(rep.warnings ?? []).map((m: string, i: number) => (
            <p key={i} className="msg warn">{m}</p>
          ))}
          {res.ok && (
            <p className="msg ok">
              {res.saved ? `Saved ${res.saved} activities.` : `Valid: ${res.count} activities in ${rep.municipalities} municipalities`}
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
                    <th>Map</th>
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
                      <td>{hazardLabel(r.hazard)}</td>
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
              <label htmlFor="a-map">Responds to map</label>
              <select id="a-map" value={form.hazard} onChange={(e) => set("hazard", e.target.value)}>
                {ACTIVITY_HAZARDS.map((h) => (
                  <option key={h.id} value={h.id}>{h.label}</option>
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
              <label htmlFor="a-ben">Beneficiaries (farmers)</label>
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

      <Importer onSaved={load} />

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
          <a href="/activities">View the public activities page →</a>
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
                  <th>Map</th>
                  <th>Dates</th>
                  <th>Farmers</th>
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
                      <td className="small">{hazardLabel(a.hazard)}</td>
                      <td className="small">{dateRange(a)}</td>
                      <td>{a.beneficiaries != null ? fmtNumber(a.beneficiaries, 0) : ""}</td>
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
