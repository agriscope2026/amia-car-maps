"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/client";

function Uploader({ kind, title, help, template, needsDate }: { kind: string; title: string; help: string; template: string; needsDate?: boolean }) {
  const [file, setFile] = useState<File | null>(null);
  const [asOf, setAsOf] = useState("");
  const [res, setRes] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const send = async (save: boolean) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.set("file", file, file.name);
      form.set("settings", JSON.stringify({ as_of: asOf }));
      setRes(await api(`/api/admin/reference/${kind}${save ? "?save=1" : ""}`, { method: "POST", body: form }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const rep = res?.report;
  return (
    <section>
      <h2>{title}</h2>
      <p className="muted small">{help}</p>
      <div className="row">
        <input type="file" accept=".csv,.xlsx,.geojson,.json" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setRes(null); }} aria-label={`${title} file`} />
        {needsDate && (
          <label className="row">
            As of <input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
          </label>
        )}
        <a href={`/api/templates/${template}`}>Download template</a>
      </div>
      <div className="row" style={{ marginTop: 10 }}>
        <button className="btn secondary" disabled={!file || busy} onClick={() => send(false)}>Validate</button>
        <button className="btn" disabled={!file || busy || !res?.ok} onClick={() => send(true)}>Save</button>
      </div>
      {error && <p className="msg err">{error}</p>}
      {rep && (
        <div style={{ marginTop: 8 }}>
          {(rep.errors ?? []).map((m: string, i: number) => <p key={i} className="msg err">{m}</p>)}
          {(rep.warnings ?? []).map((m: string, i: number) => <p key={i} className="msg warn">{m}</p>)}
          {res.ok && (
            <p className="msg ok">
              {res.saved ? "Saved. " : "Valid. "}
              {kind === "crops" ? `Crops: ${res.crops.join(", ")} for ${Object.keys(res.values).length} municipalities.` : `${res.geojson.features.length} irrigation sources.`}
            </p>
          )}
        </div>
      )}
    </section>
  );
}

function CropColors() {
  const [info, setInfo] = useState<{ crops: string[]; colors: Record<string, string>; as_of: string } | null>(null);
  const [colors, setColors] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<string | null>(null);
  const load = () =>
    fetch("/api/public/crops")
      .then((r) => r.json())
      .then((c) => {
        setInfo(c);
        setColors(c?.colors ?? {});
      })
      .catch(() => undefined);
  useEffect(() => {
    load();
  }, []);
  if (!info?.crops?.length) return null;
  return (
    <section>
      <h2>Crop colours</h2>
      <p className="muted small">
        Used for the crop circles and the choropleth on the dashboard, and for the crop circles on exported maps (standing crops as
        of {info.as_of}).
      </p>
      <div className="color-grid">
        {info.crops.map((c) => (
          <label key={c} className="color-pick">
            <input type="color" value={colors[c] ?? "#2e7d32"} onChange={(e) => setColors({ ...colors, [c]: e.target.value })} />
            <span>{c}</span>
            <code>{colors[c]}</code>
          </label>
        ))}
      </div>
      <div className="row" style={{ marginTop: 10 }}>
        <button
          className="btn"
          onClick={async () => {
            setMsg(null);
            try {
              await api("/api/admin/crop-colors", { method: "POST", json: { colors } });
              setMsg("Saved.");
              load();
            } catch (e) {
              setMsg((e as Error).message);
            }
          }}
        >
          Save colours
        </button>
        {msg && <span className="small muted">{msg}</span>}
      </div>
    </section>
  );
}

export default function ReferenceUploads() {
  return (
    <>
      <CropColors />
      <Uploader
        kind="crops"
        title="Standing crops (crop overlay)"
        template="envi_crops"
        needsDate
        help="PSGC, AREA (municipality), then one column per crop in hectares – as many crops as you have (Rice, Corn, Coffee, Cabbage, …). Title rows above the header are fine; a plain “Total” column is ignored. Every crop becomes a choice in the dashboard's crop overlay."
      />
      <Uploader
        kind="irrigation"
        title="Irrigation sources and dams"
        template="irrigation"
        help="CSV/XLSX with NAME, TYPE (NIS, CIS, SWIP, SSIP, DAM, OTHER), LAT, LON, MUNICIPALITY, RIVER, SERVICE_AREA_HA, STATUS, SOURCE – or a GeoJSON with points (and optional service-area polygons). Saving replaces the whole layer."
      />
    </>
  );
}
