"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CatalogEntry, CropsLayer, Gazetteer, Layer, Payload, ProductType } from "@/lib/types";
import { PRODUCT_TYPES } from "@/lib/types";
import { DEFAULT_STATE, parseState, serializeState, type ViewState } from "@/lib/share";
import { defaultLayer, fmtDate, latestOf, sortIssues, irrigationTypes } from "@/lib/format";
import { Legend, CropLegend, IrrigationLegend } from "./Legend";
import { Summary } from "./Summary";
import { Downloads } from "./Downloads";
import PhotoMode, { photosOf } from "./PhotoMode";
import { FarmAdvice } from "./FarmAdvice";
import AreaDialog from "./AreaDialog";
import { useSheetSwipe } from "./useSheetSwipe";
import GuideTour, { guideSeen, type GuideStep } from "./GuideTour";

const MapView = dynamic(() => import("./MapView"), { ssr: false, loading: () => <div className="map map-loading">Loading map…</div> });


export default function Dashboard({ geo }: { geo: Gazetteer }) {
  const [catalog, setCatalog] = useState<CatalogEntry[] | null>(null);
  const [state, setState] = useState<ViewState>(DEFAULT_STATE);
  const [payload, setPayload] = useState<Payload | null>(null);
  const [crops, setCrops] = useState<CropsLayer | null>(null);
  const [irrigation, setIrrigation] = useState<any | null>(null);
  // why an overlay shows nothing: no data published yet, or it failed to load
  const [overlayMsg, setOverlayMsg] = useState<{ crops?: string; irrigation?: string }>({});
  const [error, setError] = useState<string | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [copied, setCopied] = useState(false);
  const [area, setArea] = useState<string | null>(null);
  const [tour, setTour] = useState(false);
  const [legendOpen, setLegendOpen] = useState(true);
  const initial = useRef<ViewState | null>(null);
  const panelRef = useRef<HTMLElement>(null);
  useSheetSwipe(panelRef, sheetOpen, setSheetOpen);

  // initial state from the URL (share links)
  useEffect(() => {
    // small screens: start with the on-map legend folded so it doesn't cover the map
    if (window.matchMedia("(max-width: 820px), (max-height: 520px)").matches) setLegendOpen(false);
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
      fetch("/api/public/crops")
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
        .then((c) => {
          if (c?.crops?.length) setCrops(c);
          else setOverlayMsg((m) => ({ ...m, crops: "No standing crops table has been published yet." }));
        })
        .catch(() => setOverlayMsg((m) => ({ ...m, crops: "Standing crops could not be loaded. Please try again later." })));
  }, [state.crops, payload, area, crops]);
  useEffect(() => {
    if (state.irrigation && !irrigation)
      fetch("/api/public/irrigation")
        .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
        .then((g) => {
          setIrrigation(g);
          if (!g?.features?.length) setOverlayMsg((m) => ({ ...m, irrigation: "No irrigation sources or dams have been published yet." }));
        })
        .catch(() => setOverlayMsg((m) => ({ ...m, irrigation: "Irrigation sources could not be loaded. Please try again later." })));
  }, [state.irrigation, irrigation]);
  useEffect(() => {
    if (crops && !state.cropSel?.length) setState((s) => ({ ...s, cropSel: [crops.crops.includes("Rice") ? "Rice" : crops.crops[0]] }));
  }, [crops, state.cropSel]);

  // first visit: start the guide once the map and its panels are on the page (not over a shared photo-mode link)
  const ready = catalog !== null && (payload !== null || error !== null || catalog.length === 0);
  useEffect(() => {
    if (!ready || guideSeen() || initial.current?.photo) return;
    const t = setTimeout(() => setTour(true), 600);
    return () => clearTimeout(t);
  }, [ready]);
  // example municipality for the guide: one in the top class of the map on screen
  const demoArea = useMemo(() => {
    if (!layer) return null;
    const order = layer.legend.classes.map((c) => c.label);
    const keys = Object.keys(layer.values).filter((k) => order.includes(layer.values[k]?.class));
    keys.sort((a, b) => order.indexOf(layer.values[b].class) - order.indexOf(layer.values[a].class));
    return keys[0] ?? null;
  }, [layer]);
  const demoTargets = demoArea ? ["area-value", ...(payload?.texts.recommendations ? ["area-recs"] : [])] : [];
  const onTourStep = useCallback((s: GuideStep, inPanel: boolean) => {
    setSheetOpen(inPanel);
    setArea(s.demo ? demoArea : null);
  }, [demoArea]);
  const closeTour = useCallback(() => {
    setTour(false);
    setSheetOpen(false);
    setArea(null);
  }, []);
  const openTour = () => {
    setArea(null);
    set({ photo: false });
    setTour(true);
  };

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
  // irrigation types come from the data (any type an admin uploads); all are shown until the viewer filters
  const irrList = useMemo(() => irrigationTypes(irrigation), [irrigation]);
  const irrTypes = state.irrTypes ?? irrList.map((t) => t.code);
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

  const pickType = (id: ProductType) => {
    setPlaying(false);
    set({ type: id, product: undefined, layer: undefined });
  };
  const typeButtons = PRODUCT_TYPES.map((t) => {
    const has = available.some((a) => a.id === t.id);
    return (
      <button
        key={t.id}
        role="radio"
        aria-checked={type === t.id}
        disabled={!has}
        className={type === t.id ? "on" : ""}
        onClick={() => pickType(t.id)}
      >
        {t.short}
      </button>
    );
  });

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
        <button className="guide-btn" data-tour="help" onClick={openTour} aria-label="How to use this site">
          <span aria-hidden>?</span>
          <span className="guide-label">How to use</span>
        </button>
        <nav className="toplinks">
          <Link href="/about">About &amp; methodology</Link>
        </nav>
      </header>

      <main className="body">
        <section className="mapwrap" aria-label="Map" data-tour="map">
          {/* phones: the panel is a closed bottom sheet, so the map type gets a dropdown on the map itself */}
          <label className="type-select" data-tour="maptype">
            <span className="type-select-k">Map</span>
            <select value={type ?? ""} onChange={(e) => pickType(e.target.value as ProductType)} aria-label="Map type">
              {PRODUCT_TYPES.map((t) => {
                const has = available.some((a) => a.id === t.id);
                return (
                  <option key={t.id} value={t.id} disabled={!has}>
                    {t.label}{has ? "" : " – not available yet"}
                  </option>
                );
              })}
            </select>
          </label>
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
            showHydro={state.hydro}
            irrTypes={irrTypes}
            basemap={state.basemap}
            initialView={initial.current?.view}
            onViewChange={onView}
          />
          {photos.length > 0 && (
            <button className="photo-open" data-tour="photo" onClick={() => set({ photo: true })} title="See the finished map images with the recommendations">
              🖼 Photo mode{payload?.type === "envi" && <span className="photo-open-more"> – presentation &amp; recommendations</span>}
            </button>
          )}
          {layer && (
            <div className={`map-legend ${legendOpen ? "" : "folded"}`} aria-hidden={sheetOpen}>
              <button className="map-legend-toggle" onClick={() => setLegendOpen((o) => !o)} aria-expanded={legendOpen}>
                {legendOpen ? "Hide legend ▾" : "Legend ▸"}
              </button>
              {legendOpen && <Legend layer={layer} compact />}
            </div>
          )}
        </section>

        <aside ref={panelRef} className={`panel ${sheetOpen ? "open" : ""}`} aria-label="Map controls and information">
          <button className="sheet-handle" onClick={() => setSheetOpen((o) => !o)} aria-expanded={sheetOpen}>
            <span className="grip" aria-hidden />
            {sheetOpen ? "Swipe down or tap to hide" : `${PRODUCT_TYPES.find((t) => t.id === type)?.short ?? "Map"} · ${layer?.label ?? ""} – swipe up for controls`}
          </button>

          {error && <p className="error" role="alert">{error}</p>}
          {catalog && !catalog.length && <p className="muted">No products have been published yet.</p>}

          <fieldset className="group" data-tour="maptype">
            <legend>Map type</legend>
            <div className="seg" role="radiogroup">
              {typeButtons}
            </div>
          </fieldset>

          {issues.length > 0 && (
            <div className="group" data-tour="period">
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
            {state.crops && !crops && overlayMsg.crops && <p className="hint warn">{overlayMsg.crops}</p>}
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
            {state.irrigation && overlayMsg.irrigation && <p className="hint warn">{overlayMsg.irrigation}</p>}
            {state.irrigation && !overlayMsg.irrigation && (
              <div className="sub">
                <IrrigationLegend
                  types={irrTypes}
                  list={irrList}
                  data={irrigation}
                  onToggle={(t) => set({ irrTypes: irrTypes.includes(t) ? irrTypes.filter((x) => x !== t) : [...irrTypes, t] })}
                />
              </div>
            )}
            <label className="check">
              <input type="checkbox" checked={state.hydro} onChange={(e) => set({ hydro: e.target.checked })} /> Rivers &amp; water bodies
            </label>
            {state.hydro && (
              <div className="sub">
                <ul className="hydro-legend">
                  <li><span className="hydro-sw river" aria-hidden /> River</li>
                  <li><span className="hydro-sw water" aria-hidden /> Lake / reservoir</li>
                </ul>
                <p className="hint">Names appear when you zoom in. Source: OpenStreetMap.</p>
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
            <div className="group" data-tour="downloads">
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
                <div className="group" id="recommendations" data-tour="recs">
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
      {tour && <GuideTour onStep={onTourStep} onClose={closeTour} demoTargets={demoTargets} />}
      {state.photo && payload && (
        <PhotoMode payload={payload} layerId={layer?.id} onLayer={(id) => set({ layer: id })} onClose={() => set({ photo: false })} />
      )}
    </div>
  );
}
