"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CatalogEntry, CropsLayer, Gazetteer, Layer, Payload, ProductType } from "@/lib/types";
import { PRODUCT_TYPES } from "@/lib/types";
import { DEFAULT_STATE, parseState, serializeState, type ViewState } from "@/lib/share";
import { IRRIGATION_TYPES, defaultLayer, fmtDate, latestOf, sortIssues } from "@/lib/format";
import { Legend, CropLegend, IrrigationLegend } from "./Legend";
import { Summary } from "./Summary";
import { Downloads } from "./Downloads";
import PhotoMode, { photosOf } from "./PhotoMode";
import { FarmAdvice } from "./FarmAdvice";
import AreaDialog from "./AreaDialog";

const MapView = dynamic(() => import("./MapView"), { ssr: false, loading: () => <div className="map map-loading">Loading map…</div> });

const ALL_IRR = Object.keys(IRRIGATION_TYPES);

export default function Dashboard({ geo }: { geo: Gazetteer }) {
  const [catalog, setCatalog] = useState<CatalogEntry[] | null>(null);
  const [state, setState] = useState<ViewState>(DEFAULT_STATE);
  const [payload, setPayload] = useState<Payload | null>(null);
  const [crops, setCrops] = useState<CropsLayer | null>(null);
  const [irrigation, setIrrigation] = useState<any | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [copied, setCopied] = useState(false);
  const [area, setArea] = useState<string | null>(null);
  const initial = useRef<ViewState | null>(null);

  // initial state from the URL (share links)
  useEffect(() => {
    const s = parseState(new URLSearchParams(window.location.search));
    initial.current = s;
    setState(s);
    fetch("/api/public/catalog")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`Catalog: HTTP ${r.status}`))))
      .then((d) => setCatalog(d.products))
      .catch((e) => setError(String(e.message ?? e)));
  }, []);

  const available = useMemo(() => PRODUCT_TYPES.filter((t) => catalog?.some((p) => p.type === t.id)), [catalog]);
  const type: ProductType | undefined = (state.type as ProductType) ?? available[0]?.id;
  const issues = useMemo(() => sortIssues((catalog ?? []).filter((p) => p.type === type)), [catalog, type]);
  const entry = issues.find((p) => p.id === state.product) ?? (type && catalog ? latestOf(catalog, type) : undefined);
  const layer: Layer | null = useMemo(() => {
    if (!payload) return null;
    return payload.layers.find((l) => l.id === state.layer) ?? payload.layers.find((l) => l.id === defaultLayer(payload.type, payload.layers)) ?? null;
  }, [payload, state.layer]);

  // load the selected product
  useEffect(() => {
    if (!entry) return;
    let cancelled = false;
    setPayload((p) => (p?.id === entry.id ? p : null));
    fetch(`/api/public/products/${encodeURIComponent(entry.id)}`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`Product: HTTP ${r.status}`))))
      .then((p: Payload) => !cancelled && setPayload({ ...p, id: entry.id }))
      .catch((e) => !cancelled && setError(String(e.message ?? e)));
    return () => {
      cancelled = true;
    };
  }, [entry?.id]);

  // overlays are loaded on demand
  useEffect(() => {
    if ((state.crops || payload || area) && !crops)
      fetch("/api/public/crops").then((r) => r.json()).then((c) => c && setCrops(c)).catch(() => undefined);
  }, [state.crops, payload, area, crops]);
  useEffect(() => {
    if (state.irrigation && !irrigation)
      fetch("/api/public/irrigation").then((r) => r.json()).then(setIrrigation).catch(() => undefined);
  }, [state.irrigation, irrigation]);
  useEffect(() => {
    if (crops && !state.cropSel?.length) setState((s) => ({ ...s, cropSel: [crops.crops.includes("Rice") ? "Rice" : crops.crops[0]] }));
  }, [crops, state.cropSel]);

  // keep the URL in sync (share links)
  useEffect(() => {
    if (!catalog) return;
    const qs = serializeState({ ...state, type, product: entry?.id, layer: layer?.id });
    window.history.replaceState(null, "", qs ? `?${qs}` : window.location.pathname);
  }, [state, catalog, type, entry?.id, layer?.id]);

  // month player
  // daily (10-day forecast) or monthly (seasonal, drought) maps get a player
  const monthLayers = useMemo(() => payload?.layers.filter((l) => /^(m_\d{4}-\d{2}|d_\d{4}-\d{2}-\d{2})$/.test(l.id)) ?? [], [payload]);
  const isDaily = monthLayers.some((l) => l.id.startsWith("d_"));
  const photos = useMemo(() => photosOf(payload), [payload]);
  useEffect(() => {
    if (!playing || monthLayers.length < 2) return;
    const t = setInterval(() => {
      setState((s) => {
        const i = monthLayers.findIndex((l) => l.id === (s.layer ?? layer?.id));
        return { ...s, layer: monthLayers[(i + 1) % monthLayers.length].id };
      });
    }, 1600);
    return () => clearInterval(t);
  }, [playing, monthLayers, layer?.id]);

  const set = useCallback((patch: Partial<ViewState>) => setState((s) => ({ ...s, ...patch })), []);
  const onView = useCallback((v: ViewState["view"]) => setState((s) => ({ ...s, view: v })), []);
  const irrTypes = state.irrTypes ?? ALL_IRR;
  const names = useMemo(() => Object.fromEntries(geo.gazetteer.map((g) => [g.area_key, `${g.name} (${g.province})`])), [geo]);

  const share = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      window.prompt("Copy this link", window.location.href);
    }
  };

  const typeLabel = PRODUCT_TYPES.find((t) => t.id === type)?.label ?? "";

  return (
    <div className={`app theme-${payload?.type ?? "none"}`}>
      <header className="topbar">
        <div className="logos">
          <img src="/logos/da-car.webp" alt="Department of Agriculture – Cordillera Administrative Region" width={44} height={44} />
          <img src="/logos/bagong-pilipinas.webp" alt="Bagong Pilipinas" width={47} height={44} />
          <img src="/logos/amia.webp" alt="AMIA – Adaptation and Mitigation Initiative in Agriculture" width={44} height={44} />
        </div>
        <div className="titles">
          <h1>{payload?.texts.title ?? "AMIA CAR MAPS"}</h1>
          <p>{payload ? `${payload.period.label} · as of ${fmtDate(payload.issued)}` : "DA-RFO-CAR · AMIA Program"}</p>
        </div>
        <nav className="toplinks">
          <Link href="/about">About &amp; methodology</Link>
        </nav>
      </header>

      <main className="body">
        <section className="mapwrap" aria-label="Map">
          {payload?.synthetic && (
            <div className="banner" role="note">
              Demo data – synthetic values for testing, not an official forecast.
            </div>
          )}
          <MapView
            bounds={geo.bounds}
            payload={payload}
            layer={layer}
            crops={crops}
            showCrops={state.crops}
            cropSel={state.cropSel ?? []}
            onSelectArea={(k) => setArea(k)}
            cropMode={state.cropMode}
            irrigation={irrigation}
            showIrrigation={state.irrigation}
            irrTypes={irrTypes}
            basemap={state.basemap}
            initialView={initial.current?.view}
            onViewChange={onView}
          />
          {photos.length > 0 && (
            <button className="photo-open" onClick={() => set({ photo: true })} title="See the finished map images with the recommendations">
              🖼 Photo mode{payload?.type === "envi" ? " – presentation & recommendations" : ""}
            </button>
          )}
          {layer && (
            <div className="map-legend" aria-hidden={sheetOpen}>
              <Legend layer={layer} compact />
            </div>
          )}
        </section>

        <aside className={`panel ${sheetOpen ? "open" : ""}`} aria-label="Map controls and information">
          <button className="sheet-handle" onClick={() => setSheetOpen((o) => !o)} aria-expanded={sheetOpen}>
            <span className="grip" aria-hidden />
            {sheetOpen ? "Hide panel" : `${PRODUCT_TYPES.find((t) => t.id === type)?.short ?? "Map"} · ${layer?.label ?? ""} – show controls`}
          </button>

          {error && <p className="error" role="alert">{error}</p>}
          {catalog && !catalog.length && <p className="muted">No products have been published yet.</p>}

          <fieldset className="group">
            <legend>Map type</legend>
            <div className="seg" role="radiogroup">
              {PRODUCT_TYPES.map((t) => {
                const has = available.some((a) => a.id === t.id);
                return (
                  <button
                    key={t.id}
                    role="radio"
                    aria-checked={type === t.id}
                    disabled={!has}
                    className={type === t.id ? "on" : ""}
                    onClick={() => {
                      setPlaying(false);
                      set({ type: t.id, product: undefined, layer: undefined });
                    }}
                  >
                    {t.short}
                  </button>
                );
              })}
            </div>
          </fieldset>

          {issues.length > 0 && (
            <div className="group">
              <label htmlFor="issue">Issue / period</label>
              <select
                id="issue"
                value={entry?.id ?? ""}
                onChange={(e) => {
                  setPlaying(false);
                  set({ product: e.target.value, layer: undefined });
                }}
              >
                {issues.map((p, i) => (
                  <option key={p.id} value={p.id}>
                    {p.period.label} (as of {fmtDate(p.issued)}){i === 0 ? " – latest" : ""}
                  </option>
                ))}
              </select>
              {issues.length > 1 && <p className="hint">Older issues are in the archive above.</p>}
            </div>
          )}

          {payload && payload.layers.length > 1 && (
            <div className="group">
              <label htmlFor="layer">{isDaily ? "Day" : monthLayers.length ? "Month" : "Layer"}</label>
              <select id="layer" value={layer?.id ?? ""} onChange={(e) => set({ layer: e.target.value })}>
                {payload.layers.map((l) => (
                  <option key={l.id} value={l.id}>
                    {l.label}
                  </option>
                ))}
              </select>
              {monthLayers.length > 1 && (
                <div className="player">
                  <button onClick={() => setPlaying((p) => !p)} aria-pressed={playing} aria-label={playing ? "Pause" : "Play through the maps"}>
                    {playing ? "❚❚" : "▶"}
                  </button>
                  <input
                    type="range"
                    min={0}
                    max={monthLayers.length - 1}
                    value={Math.max(0, monthLayers.findIndex((l) => l.id === layer?.id))}
                    onChange={(e) => set({ layer: monthLayers[Number(e.target.value)].id })}
                    aria-label={isDaily ? "Day" : "Month"}
                    aria-valuetext={layer?.label}
                  />
                </div>
              )}
            </div>
          )}

          {layer && (
            <div className="group">
              <h2>Legend</h2>
              <Legend layer={layer} />
            </div>
          )}

          <fieldset className="group">
            <legend>Overlays</legend>
            <label className="check">
              <input type="checkbox" checked={state.crops} onChange={(e) => set({ crops: e.target.checked })} /> Standing crops (ha)
            </label>
            {state.crops && crops && (
              <div className="sub">
                <div className="seg small" role="radiogroup" aria-label="Crop display">
                  {(["circles", "choropleth"] as const).map((m) => (
                    <button
                      key={m}
                      role="radio"
                      aria-checked={state.cropMode === m}
                      className={state.cropMode === m ? "on" : ""}
                      onClick={() => set({ cropMode: m, cropSel: m === "choropleth" ? (state.cropSel ?? []).slice(0, 1) : state.cropSel })}
                    >
                      {m === "circles" ? "Proportional circles" : "Choropleth"}
                    </button>
                  ))}
                </div>
                <CropLegend crops={crops} sel={state.cropSel ?? []} mode={state.cropMode} onChange={(cropSel) => set({ cropSel })} />
              </div>
            )}
            <label className="check">
              <input type="checkbox" checked={state.irrigation} onChange={(e) => set({ irrigation: e.target.checked })} /> Irrigation sources &amp; dams
            </label>
            {state.irrigation && (
              <div className="sub">
                <IrrigationLegend
                  types={irrTypes}
                  data={irrigation}
                  onToggle={(t) => set({ irrTypes: irrTypes.includes(t) ? irrTypes.filter((x) => x !== t) : [...irrTypes, t] })}
                />
              </div>
            )}
            <label htmlFor="basemap">Basemap</label>
            <select id="basemap" value={state.basemap} onChange={(e) => set({ basemap: e.target.value as ViewState["basemap"] })}>
              <option value="light">Light grey</option>
              <option value="terrain">Terrain</option>
              <option value="satellite">Satellite</option>
            </select>
          </fieldset>

          {payload && layer && (
            <div className="group">
              <h2>Summary</h2>
              <Summary payload={payload} layer={layer} crops={crops} names={names} />
            </div>
          )}

          {payload?.downloads && payload.downloads.length > 0 && (
            <div className="group">
              <h2>Downloads</h2>
              <Downloads items={payload.downloads} currentLayer={layer?.id} />
            </div>
          )}

          {payload && (
            <>
              <div className="group" id="notes">
                <h2>Notes</h2>
                {payload.texts.notes && <p className="prose">{payload.texts.notes}</p>}
                <p className="prose small">
                  <strong>Sources:</strong> {payload.texts.sources}
                </p>
                <p className="prose small muted">{payload.texts.disclaimer}</p>
              </div>
              <FarmAdvice texts={payload.texts} />
              {payload.texts.recommendations && (
                <div className="group" id="recommendations">
                  <h2>Agricultural recommendations</h2>
                  <div className="prose recs">
                    {payload.texts.recommendations.split("\n").map((line, i) => (
                      <p key={i} className={/^\s*[-•\d]/.test(line) ? "li" : ""}>
                        {line.replace(/^\s*[-•]\s*/, "")}
                      </p>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}

          <div className="group actions">
            {photos.length > 0 && <button onClick={() => set({ photo: true })}>Photo mode</button>}
            <button onClick={share}>{copied ? "Link copied" : "Copy share link"}</button>
            <Link href={`/about${type ? `#${type}` : ""}`}>About {typeLabel ? `“${PRODUCT_TYPES.find((t) => t.id === type)?.short}”` : "the maps"}</Link>
          </div>
          <footer className="foot">
            Department of Agriculture – Regional Field Office, Cordillera Administrative Region · AMIA Program
          </footer>
        </aside>
      </main>
      {area && (
        <AreaDialog
          areaKey={area}
          geo={geo}
          payload={payload}
          layer={layer}
          crops={crops}
          onLayer={(id) => set({ layer: id })}
          onPhoto={payload && photos.length ? () => { setArea(null); set({ photo: true }); } : undefined}
          onClose={() => setArea(null)}
        />
      )}
      {state.photo && payload && (
        <PhotoMode payload={payload} layerId={layer?.id} onLayer={(id) => set({ layer: id })} onClose={() => set({ photo: false })} />
      )}
    </div>
  );
}
