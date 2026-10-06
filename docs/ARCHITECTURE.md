# CAR Agri-Climate Portal — architecture, decisions and plan

This document covers milestone 1 of the build prompt ([PROMPT_CAR_AgriClimate_Portal.md](../PROMPT_CAR_AgriClimate_Portal.md)):
the architecture, the schema, the screen layouts, the answers to the open questions in §12 (or the assumptions used
until DA-RFO-CAR confirms them), and the milestone plan with its current status.

## 1. Architecture

```
                 Browser (public dashboard, admin workspace)
                         │  HTTPS
                         ▼
 ┌────────────────────────────────────────────────────┐      ┌──────────────────────────────┐
 │ web/  Next.js 15 (TypeScript) on Vercel             │      │ Supabase                      │
 │  • public pages + /api/public/*  (read-only, cached)│─────▶│  Postgres + PostGIS (RLS)     │
 │  • /admin + /api/admin/* (role check, CSRF check)   │      │  Auth (email + password)      │
 │  • MapLibre GL JS, static CAR boundaries (162 KB)   │      │  Storage: uploads, exports,   │
 │  • Vercel Cron → /api/cron/rainfall-feed (daily)    │      │  public-exports, templates    │
 └───────────────┬────────────────────────────────────┘      └──────────────▲───────────────┘
                 │ private HTTPS + WORKER_TOKEN                               │ service role
                 ▼                                                            │ (uploads exports)
 ┌────────────────────────────────────────────────────┐                       │
 │ worker/  Python FastAPI in Docker (python:3.13-slim)│───────────────────────┘
 │  • validation + name matching (ported prototype)   │
 │  • ENVI, 10-day rainfall, seasonal, drought        │──▶ Cordillera weather API (10-day rainfall feed)
 │  • exports: PNG 400 dpi, PDF, slide, poster, XLSX,  │──▶ DroughtCaster source (when confirmed)
 │    CSV, GeoJSON, GPKG, ZIP; label verification      │
 │  • job queue with progress                          │
 └────────────────────────────────────────────────────┘
```

**Why this split.** It matches §7 of the brief, with these specifics:

- **Vercel cannot run QGIS** and limits request bodies to 4.5 MB. All rendering therefore happens in the worker.
  Input templates for 77 municipalities are only tens of kilobytes, so uploads go through the Next.js server
  (with a 4 MB limit) to the worker and into Storage. Direct-to-Storage uploads are only needed if large rasters
  are ever accepted.
- **The worker is private.** Only the Next.js server calls it, with a shared token. The browser never sees the
  token or the Supabase service key.
- **The worker owns all data logic.** Validation, matching, classification and exports run in the worker, so
  numbers and labels are identical in the preview, the dashboard and the print files. The dashboard reads a
  *payload* JSON (layers × 77 municipalities with value, class and colour) stored with each product version.
  The same values are also written to the `product_values` table for SQL queries.
- **Three data back ends behind one interface** (`web/lib/server/repo/`):
  - Supabase in production.
  - PostgreSQL + PostGIS through `DATABASE_URL`. This is the local development database (`npm run db:setup`),
    and it also works for a self-hosted server. It runs the same migration and seed as Supabase, with stand-ins
    for the `auth`/`storage` schemas.
  - A JSON file store with the bundled demo data, for a quick look without any database.
- **Rendering.**
  - ENVI runs the prototype pipeline unchanged. That pipeline uses PyQGIS with the `.qgz` layout when QGIS is
    present (it is in the Docker image) and falls back to matplotlib otherwise.
  - Rainfall and drought maps use a matplotlib renderer that reproduces the DA layout: title box, logos,
    legend with unit, north arrow, scale bar, graticule, CRS note, notes, disclaimer, sources and issuing office.
  - Labels use the prototype's collision-free engine. Every export is re-measured at 400 dpi and a label
    report is stored (83 labels, 0 overlaps), as §6 requires.
  - Porting the rainfall layouts to the `.qgz` "seasonal rainfall in mm layout" is listed under milestone 7.

## 2. Data model (Supabase / PostGIS)

The full DDL is in [`supabase/migrations/0001_init.sql`](../supabase/migrations/0001_init.sql). The seed (gazetteer,
boundaries, legend presets) is in [`supabase/seed.sql`](../supabase/seed.sql).

| Table | Purpose |
|---|---|
| `profiles` | User → role (`editor` / `admin`), active flag. Linked to `auth.users`. |
| `gazetteer` | 77 municipalities. Key `PROVINCE\|MUNICIPALITY`, PSGC code, GIS name, aliases. |
| `boundary_versions`, `boundaries` | Versioned municipal/provincial/region geometries (EPSG:4326). |
| `legends` | Class breaks and colours per legend id (`rainfall_dekad`, `rainfall_month`, `pct_normal`, …). |
| `print_templates` | `.qgz` / `.qpt` files in the `templates` bucket. |
| `crops_tables`, `crop_values` | Standing crops per inventory date (ha) → crop overlay. |
| `irrigation_sources` | Points (+ optional service-area polygons): NIS/CIS/SWIP/SSIP/dams. |
| `products` | Product type + period (`period_start`/`period_end` dates, `period_kind`) + issue date. |
| `product_versions` | Draft → published → archived, with texts, settings, method, summary, payload, inputs, validation, exports, label report, author, publisher. |
| `product_values` | Municipality × layer (month / season / dekad) × variable, **with unit**, class and colour. |
| `submissions` | Optional field-office submissions (schema only, see status). |
| `audit_log` | Logins, uploads, validation, edits, exports, publish / unpublish, reference updates. |

Every table has row-level security: the public (`anon`) role can read only published versions and reference
data. Publishing goes through the server after an admin role check. A `publish_version()` SQL function is also
provided for direct use. The `exports` bucket is private: drafts are served through short-lived signed URLs.
On publish, the files are copied to the public `public-exports` bucket.

## 3. Screens

Screenshots are in [`docs/img/`](img/).

- **Dashboard (desktop).** The header has the DA / Bagong Pilipinas / AMIA logos, the product name, the period
  and the "as of" date. The map is on the left with a floating legend. The side panel holds:
  - map type;
  - issue/period (the latest is the default; older issues are the archive);
  - month and player;
  - legend with counts;
  - overlays (crop with circles/choropleth; irrigation with type filters; basemap);
  - summary cards;
  - downloads;
  - notes;
  - recommendations;
  - share link;
  - about.
- **Dashboard (≤ 820 px).** The panel becomes a bottom sheet with a handle that shows the current map. It was
  tested at 360 px.
- **Admin.** A product list with versions and status, plus "create" buttons per type and the feed button.
  - The **upload wizard** goes: period → template download and upload → validation report (row/column errors,
    warnings, unmatched names with suggestions and "assign to") → live map preview → save draft.
  - The **version page** has: map, text editing (with "Generate automatically" for recommendations), export
    job progress and label check, downloads, publish/unpublish.
  - There are also **Reference data** (crops, irrigation) and **Audit log** pages.

## 4. Open questions (§12): assumptions until confirmed

| Question | Assumption used now | What changes when it is answered |
|---|---|---|
| DroughtCaster access method, licence, municipal data | No public machine-readable endpoint has been confirmed. The fetcher interface (`worker/agriclimate/droughtcaster.py`) has retries, logging and a "last fetched" record. It currently downloads a table in the manual template format from a configured URL (`DROUGHTCASTER_URL`). **Manual upload always works.** Fetched data is only ever a draft. | Add a `Fetcher` subclass for the official endpoint (API / GeoJSON / raster + zonal stats). Accept municipal rows if PAGASA provides them; the loader already supports both levels. |
| 10-day rainfall source | **Confirmed by DA-RFO-CAR:** `https://cordillera-weather.onrender.com/api/cordillera/full/`. It gives daily `rainfall_total` (mm) for all 77 municipalities over 10 days. Only rainfall is used. A daily cron creates a draft with exports; an admin publishes it. | If the feed's 10-day window should map to calendar dekads (1–10, 11–20, 21–end), add that rule in `rainfall_feed.py`. Today the period is stored exactly as the feed gives it (e.g. Oct 5–14). |
| Seasonal rainfall source | **Added:** PAGASA's seasonal forecast page publishes provincial tables (mm min/mean/max, % normal) as images only. The worker reads the CAR rows with OCR (RapidOCR/ONNX), checks them, and builds a draft with the extracted values and image links for the admin to check. Upload stays available. | If PAGASA publishes machine-readable data, replace the OCR step in `pagasa_seasonal.py`. |
| Official class breaks and colours for rainfall maps | The brief's defaults (dekad 0–10…>200 mm; monthly 0–50…>500 mm). Colours: brown → green → blue, colour-blind safe. Breaks are lower-inclusive. % of normal: ≤ 40 / 41–80 / 81–120 / > 120 (PAGASA wording, to be verified). | Edit `worker/agriclimate/classes.py` presets (or the `legends` table). Per-product overrides already pass through `settings.legend(s)`. |
| Irrigation / dams dataset (NIA, BSWM, LGU), service areas | CSV/XLSX (lat/lon) or GeoJSON upload. Types NIS/CIS/SWIP/SSIP/DAM/OTHER. Service-area polygons are matched by name. The demo records are **synthetic**. | Map the real dataset's columns in `reference_layers.py` if they differ. |
| Crops beyond rice and corn; update frequency | Every crop column in the standing-crops upload becomes an overlay choice. Each upload is stored per "as of" date; the latest is shown. | Nothing, unless a per-date picker is wanted on the dashboard. |
| Hosting | Vercel (web) + Supabase (DB/Auth/Storage) + a container host for the worker (Cloud Run / Render / Fly / VPS). | If only a VPS is available, run both the web app (`next start`) and the worker there. |
| Domain and email provider for logins | Supabase Auth email + password (magic links work through Supabase too); Supabase's SMTP for invites. | Configure custom SMTP and the domain in Supabase. |
| Who approves publication; two-step review | Two-step: editors create drafts, edit and export; **only admins publish**. Every step is in the audit log. | Make publishing an editor right if a single step is preferred (`requireRole("admin")` in the publish route). |
| Languages | English only. Texts are kept in a few components so they can be translated later. | Add Filipino strings (next-intl) if needed. |

## 5. Milestones and status

| # | Milestone | Status |
|---|---|---|
| 1 | Architecture, schema, wireframes, answers to §12 | **Done**: this document, migration, screenshots. |
| 2 | Gazetteer, boundaries, auth and roles, data model | **Done**: gazetteer with PSGC (77/77), simplified boundaries (162 KB), Supabase schema + RLS (checked on Postgres 17 without PostGIS), local dev auth, role checks and CSRF checks. The full schema and seed run on the local PostgreSQL 17 + PostGIS 3.6 database, and all end-to-end tests pass on it. Supabase-specific code (Auth, Storage, PostgREST) is written but **not yet run against a live project**. |
| 3 | ENVI port, end to end | **Done**: reproduces the prototype exactly with equal weights (Tabuk City 0.806 Very High; 14/44/11/7/1), through the portal too. Default weights are now drought 50 % / damage 25 % / crops 25 % (DA-RFO-CAR). |
| 4 | 10-day and seasonal rainfall | **Done**: upload + validation + preview + exports + publish, plus the live 10-day feed and daily cron. |
| 5 | Drought product | **Done for manual upload.** Fetcher interface ready; the DroughtCaster endpoint is pending (§12). |
| 6 | Public dashboard | **Done**: map types, periods/archive, month player, crops and irrigation overlays, popups, downloads, share links, CAR mask/outline, collision-free labels, mobile bottom sheet. Compare mode (optional) is not built. |
| 7 | Exports polish, tests, docs, deployment | **Mostly done.** Exports with label verification, 97 worker tests + 7 web unit tests + an end-to-end script for all products, docs and Dockerfile. Still open: PyQGIS `.qgz` layouts for the rainfall/drought maps (matplotlib reproduces the layout today), building and deploying the Docker image (no Docker on the dev machine), admin UIs for users/legends/templates (managed in Supabase for now), and field submissions (optional). |
