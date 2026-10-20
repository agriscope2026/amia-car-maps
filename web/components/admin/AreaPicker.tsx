"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { placesSummary } from "@/lib/activities";
import type { Gazetteer } from "@/lib/types";

type Town = Gazetteer["gazetteer"][number];

/** Tick box that can also show "some" (part of a province chosen). */
function TriBox({ checked, some, onChange, label }: { checked: boolean; some: boolean; onChange: (on: boolean) => void; label: string }) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = some && !checked;
  }, [some, checked]);
  return <input ref={ref} type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} aria-label={label} />;
}

/** Choose the municipalities of an activity: grouped by province, a tick box per province selects all of its
 * municipalities, search narrows the list, "Whole CAR" and "Clear" for the extremes. */
export default function AreaPicker({ towns, value, onChange }: { towns: Town[]; value: string[]; onChange: (keys: string[]) => void }) {
  const [q, setQ] = useState("");
  const [open, setOpen] = useState<Set<string>>(new Set());
  const chosen = useMemo(() => new Set(value), [value]);
  const groups = useMemo(() => {
    const m = new Map<string, Town[]>();
    for (const t of [...towns].sort((a, b) => a.name.localeCompare(b.name))) m.set(t.province, [...(m.get(t.province) ?? []), t]);
    return [...m.entries()].sort((a, b) => a[0].localeCompare(b[0]));
  }, [towns]);
  const s = q.trim().toLowerCase();
  const match = (t: Town) => !s || t.name.toLowerCase().includes(s) || t.province.toLowerCase().includes(s);

  const set = (keys: string[], on: boolean) => {
    const next = new Set(chosen);
    for (const k of keys) (on ? next.add(k) : next.delete(k));
    onChange([...next].sort());
  };
  const toggleOpen = (p: string) => setOpen((o) => {
    const n = new Set(o);
    if (n.has(p)) n.delete(p);
    else n.add(p);
    return n;
  });

  return (
    <div className="ap">
      <div className="ap-tools">
        <input type="search" placeholder="Search a municipality or province…" value={q} onChange={(e) => setQ(e.target.value)}
          aria-label="Search municipalities" />
        <button type="button" className="btn secondary small" onClick={() => onChange(towns.map((t) => t.area_key).sort())}>
          Whole CAR
        </button>
        <button type="button" className="btn secondary small" disabled={!value.length} onClick={() => onChange([])}>
          Clear
        </button>
        <span className="ap-count">{value.length ? `${value.length} selected` : "None selected"}</span>
      </div>
      <div className="ap-groups">
        {groups.map(([prov, list]) => {
          const shown = list.filter(match);
          if (!shown.length) return null;
          const n = list.filter((t) => chosen.has(t.area_key)).length;
          const isOpen = !!s || open.has(prov);
          return (
            <div key={prov} className={`ap-group${n ? " has" : ""}`}>
              <div className="ap-head">
                <label className="ap-prov">
                  <TriBox checked={n === list.length} some={n > 0} label={`All of ${prov}`}
                    onChange={(on) => set(list.map((t) => t.area_key), on)} />
                  <strong>{prov}</strong>
                  <span className="ap-n">{n ? `${n} of ${list.length}` : `${list.length} municipalities`}</span>
                </label>
                {!s && (
                  <button type="button" className="ap-toggle" onClick={() => toggleOpen(prov)} aria-expanded={isOpen}>
                    {isOpen ? "Hide" : "Choose municipalities"} <span aria-hidden>{isOpen ? "▴" : "▾"}</span>
                  </button>
                )}
              </div>
              {isOpen && (
                <div className="ap-towns">
                  {shown.map((t) => (
                    <label key={t.area_key} className={chosen.has(t.area_key) ? "on" : ""}>
                      <input type="checkbox" checked={chosen.has(t.area_key)} onChange={(e) => set([t.area_key], e.target.checked)} />
                      {t.name}
                    </label>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
      <p className={`ap-summary${value.length ? "" : " empty"}`}>
        {value.length ? placesSummary(value, towns, 12) : "Tick a province for all of its municipalities, or open it to choose some."}
      </p>
    </div>
  );
}
