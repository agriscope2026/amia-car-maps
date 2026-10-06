# Build prompt: CAR Agri-Climate Portal (public dashboard + admin map production)

You are a senior full-stack + GIS engineer. Build a **web-based system** for the Department of Agriculture –
Regional Field Office, Cordillera Administrative Region (DA-RFO-CAR, AMIA Program). It has two parts:

1. A **public dashboard**. Anyone can explore the map products the admin has published on an interactive map.
2. An **admin workspace**. Staff upload data, generate map products, edit text, export print-ready files,
   and publish them to the dashboard.

Before writing code, read this whole prompt. Then reply with:
- your architecture,
- your answers to the open questions in §12 (or the assumptions you will make),
- a milestone plan.

---

## 1. Geography and reference data

- **Study area:** Cordillera Administrative Region (CAR), Philippines. It has **6 provinces** (Abra, Apayao,
  Benguet, Ifugao, Kalinga, Mountain Province) and **77 municipalities/cities**. The cities are Baguio and Tabuk.
- **Boundaries:** the CAR municipal and provincial shapefiles (EPSG:4326). Fields are `Pro_Name`, `Mun_Name`
  (e.g. "Bangued (Abra)") and `MunName2`; the provincial layer has `OBJECTID` 65–70. They have **no PSGC
  field**, so build a gazetteer table with a canonical key `PROVINCE|MUNICIPALITY` plus PSGC codes.
  Treat municipality as the base unit, with province roll-ups.
- **Name matching** for every upload. The rule is: trim, uppercase, strip accents (Ñ→N), treat U+FFFD as N
  (corrupted Ñ), drop "(Province)" suffixes and "City of" / "City", and expand "Mt."→"Mountain",
  "Sto."→"Santo", "Sta."→"Santa". Use the province hint from the PSGC code, the province column, or the
  province subtotal row above. Fall back to fuzzy matching (≥ 85% similarity, flagged for confirmation).
  Unmatched rows must be shown with suggestions and a manual "assign to" control.
  Known cases:
  - Paracelis can be listed under Kalinga but belongs to Mountain Province.
  - Baguio City / City of Baguio / Baguio are the same area, as are Tabuk City / City of Tabuk / Tabuk.
  - Province rows and "CAR" rows inside municipal tables are **subtotals** and must be skipped.
- **Reference implementation to reuse.** A working prototype exists in the repository `Elnino-vul-index/`.
  Port its logic rather than reinventing it:
  - `envi/io_loader.py`: loaders, validation, name cleaning and matching.
  - `envi/normalize.py`, `envi/index.py`: ENVI calculation, classification and Jenks breaks.
  - `envi/recommendations.py`: rule-based recommendations.
  - `envi/labels.py`, `envi/qgis_render.py`: collision-free labels and QGIS print layouts.
  - `envi/presentation.py`: infographic.
  - `web/js/validate.js`: browser-side validation.
  - `gis template/drought_forecast.qgz` and `.qpt`: the official DA print layouts. The `.qgz` contains the
    layouts "drougt_layout" and "seasonal rainfall in mm layout", with logos, title box, legend, note,
    disclaimer, sources, north arrow, scale bar and grid.
  - `assets/logos/`, `assets/fonts/` (Montserrat).

## 2. Users and roles

| Role | Can do |
|---|---|
| Public (no login) | View published products on the dashboard, switch layers and periods, see popups, download the published exports |
| Editor | Upload data, validate, generate drafts, edit titles/notes/recommendations, export |
| Admin | Everything editors can do, plus publish/unpublish, manage users, reference layers (crops, dams), legends and templates, view the audit log |

Use real authentication (email + password or magic link, hashed, with sessions and CSRF protection), with
role checks on every admin API. The public side is read-only and only ever sees **published** products.

## 3. Products (admin tools)

Every product is a record with:
- type,
- **issue date ("as of")**,
- **validity period** (dekad, month range, or season),
- source and data files,
- legend and class breaks,
- title, subtitle, notes, disclaimer and recommendations,
- status (draft → published → archived),
- version and author.

Every product goes through the same pipeline:

**upload → validate → preview map → edit text → generate exports → publish.**

### 3.1 ENVI – El Niño Vulnerability Index (port the existing tool)
- **Inputs (same templates as the prototype):**
  - drought forecast per province: monthly categories — not affected / dry condition / dry spell / drought;
  - historical El Niño damage per municipality, in **hectares**, one column per crop and year;
  - standing crops per municipality, in **hectares**: PSGC, name, then Corn Total and Rice Total.
- **Method:**
  - Ordinal drought score: not affected = 0, dry condition = 1, dry spell = 2, drought = 3, summed over the
    months. Optionally use a fixed scale (score ÷ maximum possible score).
  - Min–max normalization of each indicator to 0–1; if max = min, the value is 0.
  - Weighted sum with editable weights that must total 1 (default ⅓ each).
  - 5 classes: equal intervals 0–0.2–0.4–0.6–0.8–1.0 by default, with natural breaks and quantiles as options.
  - Any area without data is drawn as **"No data"**.
- **Colours:** Very Low `#1a9850`, Low `#91cf60`, Moderate `#fee08b`, High `#fc8d59`, Very High `#d73027`,
  No data `#d9d9d9` (hatched).
- **Outputs:**
  - ranked, sortable table (CSV/XLSX);
  - map;
  - summary: counts per class, standing crop area at risk (High + Very High, in ha), top 10;
  - **agricultural recommendations**: a rule-based auto-draft from forecast timing, hotspot areas and past
    damage, always editable;
  - presentation images: a 1920×1080 slide and an A4 poster, styled after the DA Canva template.

### 3.2 10-day rainfall forecast (mm)
- **Input (admin upload, CSV/XLSX):** one row per **municipality** with PSGC (optional), province,
  municipality, and forecast rainfall in **mm** for the dekad. Allow either one total column, or daily
  columns that the system sums. Also capture the dekad dates ("Oct 1–10, 2026"), the issue date and the source.
- **Validation:**
  - numeric, ≥ 0;
  - warn above a configurable maximum (e.g. 500 mm per dekad);
  - all 77 municipalities present (missing ones become "No data").
- **Map:** graduated choropleth in mm with a sequential dry→wet palette (brown/yellow → green → blue).
  Default classes: 0–10, 10–25, 25–50, 50–100, 100–150, 150–200, >200 mm. The classes are admin-editable
  and saved per product type.

### 3.3 Seasonal rainfall forecast (mm)
- **Input (admin upload):** one row per **municipality**, and one column per month of the season (e.g.
  October … March), in **mm**. Optional extra columns are allowed for the season total and for normal or
  % of normal values.
- **Map:** one map per month plus a season-total map, all in mm.
  - Monthly default classes: 0–50, 50–100, 100–200, 200–300, 300–400, 400–500, >500 mm.
  - Season-total classes are configurable.
  - If % of normal is supplied, offer a second legend: way below normal <40%, below normal 41–80%, near
    normal 81–120%, above normal >120%. Confirm these thresholds with PAGASA's current legend.
- Base the print layout on the "seasonal rainfall in mm layout" in the `.qgz` ("SEASONAL RAINFALL OUTLOOK",
  "Legend in millimeters (mm)", the mm-to-litres note, PAGASA and AMIA credits).
- **Dashboard overlays for this product:** crops and irrigation sources (§4.3).

### 3.4 Drought monitoring forecast map
- **Data source:** PAGASA **DroughtCaster**. Keep only **CAR** (6 provinces, and municipalities if the
  source provides them).
  - Find the official, current access method. Check whether it offers a downloadable table, GeoJSON or
    raster, or only published maps.
  - Respect the terms of use.
  - Put the fetcher behind an interface with retries and logging, plus a "last fetched" timestamp.
  - **Always provide a manual upload fallback**, using the same template as the prototype's
    `drought forecast.csv`: `ID, PROVINCE, October … March`, with the PAGASA categories.
- **Categories (PAGASA definitions; verify against the current PAGASA documentation):**
  - not affected;
  - dry condition: 2 consecutive months of below-normal rainfall (21–60% reduction);
  - dry spell: 3 consecutive months below normal, or 2 months way below normal (>60% reduction);
  - drought: 3 consecutive months way below normal, or 5 months below normal.
- **Colours from the existing template:** not affected `#ffffff`, dry condition `#ffeb89`, dry spell
  `#ff9501`, drought `#921816`. Use a black province outline.
- **Maps:** one map per month of the outlook. The dashboard has a month slider/player.

## 4. Public dashboard

### 4.1 Layout
- Header with the DA / Bagong Pilipinas / AMIA logos and the product name.
- A large interactive map.
- Side panel with:
  - **map type** selector: ENVI, 10-day rainfall, seasonal rainfall, drought forecast;
  - **period** selector: dekad, month or season; the default is the latest published issue, and older
    issues are reachable through an archive;
  - **overlays**;
  - legend;
  - summary cards (e.g. areas per class, crop area at risk);
  - downloads of the published exports;
  - "about / methodology".
- Responsive down to 360 px wide: the map stays usable, and panels become a bottom sheet.

### 4.2 CAR must be the highlight
- Fit and restrict the view to CAR (with a small margin).
- Dim everything outside CAR with an inverted mask (semi-transparent white or grey).
- Draw a bold regional outline, province outlines, and thin municipal lines.
- Keep the basemap subtle (light grey; satellite/terrain as an option).
- Show province names at low zoom and municipality names as you zoom in. Labels must **never overlap**:
  use MapLibre symbol collision, or the label engine's collision detection.

### 4.3 Interaction
- Hover and click popups show:
  - municipality and province;
  - the value with its unit (mm / ha / class);
  - for ENVI, the indicator values;
  - links to the product's notes and recommendations.
- **Crops overlay:**
  - The user chooses a crop (rice, corn, plus any crops present in the uploaded standing-crops data).
  - Show the area in **ha** per municipality as proportional circles, or as an alternative choropleth.
  - Popups list every crop's area.
- **Irrigation sources overlay (dams):**
  - Point layer of dams and irrigation systems (NIA national/communal irrigation systems, SWIP/SSIP, dams)
    with name, type, river, service area (ha), status and source.
  - Add filters by type.
  - Show service-area polygons if they are provided.
  - The admin maintains this layer by uploading CSV (lat/lon) or GeoJSON.
- Compare mode is optional: a swipe or side-by-side view of two periods or products.
- Share links encode the product, period, overlays and view.

## 5. Admin workspace

- **Upload wizard per product:**
  1. Download the template (pre-filled with all 77 municipalities).
  2. Upload a CSV/XLSX.
  3. Validation report: columns, units, ranges, name matching with suggestions and manual assignment,
     missing areas.
  4. Live map preview.
  5. Settings: period, legend and classes, title, subtitle, notes, disclaimer, sources, and
     **agricultural recommendations** (Generate automatically + editable).
  6. Generate exports.
  7. Publish.
- **Reference data:** gazetteer and boundaries (versioned), crops tables per date, irrigation and dams
  layer, logos, legend presets, and print templates.
- **Archive and versioning:** every product version is kept, with who/when/what. Unpublishing is possible.
- **Field submissions (optional):** field offices upload via a public form with an access code. The admin
  reviews submissions and turns one into a product draft.
- **Audit log** of uploads, edits, publishes and logins.

## 6. Exports (must be clear and print-ready)

For every product and period:
- **Map PNG (300 dpi) and PDF (vector).** Use the DA layout: map frame, title, subtitle with the validity
  period and "as of" date, legend with the **unit** (mm / ha / class ranges), north arrow, scale bar,
  coordinate grid, CRS note, logos, note/disclaimer, data sources, and the issuing office.
- **Labels:**
  - All 77 municipality names and 6 province names are visible, with **no overlaps**.
  - A name goes inside its polygon when it fits; otherwise it sits just outside with a thin leader line.
  - Province names may wrap ("Mountain / Province").
  - Verify the result automatically (store a label report: placed, missing, overlaps = 0).
  - The prototype's approach works: PAL placement → shrink in 0.5 pt steps → pin remaining names to the
    nearest free spot → freeze positions → re-check at 300 dpi.
- **Presentation:** a 1920×1080 slide and an A4 poster. They include a summary panel, top areas, and the
  recommendations (condensed on the slide, in full on the poster).
- **Data:** XLSX/CSV of the values used, GeoJSON/GeoPackage, and a JSON of the settings and method.
- **Bundle:** a ZIP per product version.
- **Typography:** use **Montserrat** everywhere (UI, maps, exports, Excel). Bundle the font files (OFL);
  never rely on system fonts.
- **Rendering:** produce exports server-side and reproducibly. Preferred: headless **PyQGIS** in a Docker
  worker using the `.qgz`/`.qpt` templates. Fallback: geopandas + matplotlib reproducing the same layout.
  Remember that the offscreen Qt platform needs `QT_QPA_FONTDIR` and registered application fonts.

## 7. Recommended architecture (justify any change)

- **Frontend:** Next.js (TypeScript) with MapLibre GL JS, deployed on **Vercel**. Map data is served as
  vector tiles or simplified GeoJSON, with CAR boundaries as a static asset.
- **Backend / data:** Supabase or another managed Postgres with **PostGIS**, Auth and Storage (or an
  equivalent). Tables: gazetteer, boundaries, products, product_versions, values (municipality × period ×
  variable), legends, crops, irrigation_sources, submissions, users/roles, audit_log.
- **Render worker:** a Python service (FastAPI) in a Docker image with QGIS LTR, geopandas, Pillow and
  openpyxl, hosted on a container platform (Cloud Run / Render / Fly / VPS). It runs a job queue with
  progress status. Vercel functions cannot run QGIS, and their request bodies are limited to 4.5 MB, so
  upload files directly to storage.
- **DroughtCaster fetcher:** a scheduled job (cron) on the worker. Admin approval is required before
  publishing.
- Store all values with units, and store periods as proper dates. Times are in **Asia/Manila**.

## 8. Data templates (ship them as downloads)

| Product | Columns | Unit |
|---|---|---|
| 10-day rainfall | PSGC, PROVINCE, MUNICIPALITY, RAINFALL_MM (or DAY_1 … DAY_10) | mm |
| Seasonal rainfall | PSGC, PROVINCE, MUNICIPALITY, one column per month (e.g. OCT_2026 … MAR_2027), optional SEASON_TOTAL, NORMAL_MM, PCT_NORMAL | mm, % |
| Drought (manual fallback) | ID, PROVINCE, one column per month | category |
| ENVI damage | MUNICIPALITY_CLEAN, RICE_DMG_YYYY, CORN_DMG_YYYY … | ha |
| Standing crops | PSGC, AREA, <crop> Total … | ha |
| Irrigation sources | NAME, TYPE, LAT, LON, MUNICIPALITY, RIVER, SERVICE_AREA_HA, STATUS, SOURCE | — |

Templates are pre-filled with every CAR municipality. Each one includes a README sheet explaining the units.

## 9. Quality and non-functional requirements

- Validation messages are plain-language and point to row and column.
- Dashboard performance: under 2.5 s to first map on 4G; under 1 MB of boundaries; cache published products.
- Accessibility:
  - colour-blind-safe palettes, with ENVI/drought class labels shown as text as well as colour;
  - keyboard-navigable controls;
  - alt text for exports.
- Security:
  - role checks server-side;
  - signed URLs for draft files, public URLs only for published exports;
  - rate limiting on public forms;
  - no secrets in the client.
- Tests:
  - name matching (all 77 names and the known variants);
  - normalization, weights and classification (equal, quantile, Jenks);
  - rainfall class assignment at the break values;
  - template round-trips;
  - label report (0 overlaps, 83 labels);
  - one end-to-end test per product (upload → publish → appears on the dashboard).
- Documentation: setup, environment variables, deployment (frontend, database, worker), and an admin user guide.

## 10. Acceptance criteria

1. With the sample ENVI files, the system reproduces the prototype's result. With equal weights and equal
   intervals, the top area is Tabuk City at 0.806 (Very High), and the class counts are 14 / 44 / 11 / 7 / 1.
2. An admin can upload a 10-day and a seasonal rainfall file. They see the validation, preview, edit the
   text, export PNG/PDF/XLSX, and publish. The public dashboard then shows the product with the correct mm
   legend and period.
3. The drought product can be created from DroughtCaster data or the manual template. It covers CAR only
   and has one map per month.
4. On the dashboard, the user can switch map type and period, toggle the crop overlay (choosing the crop)
   and the irrigation/dam overlay, open popups, and download the published exports. CAR is visually
   emphasized, and the view is limited to CAR.
5. Every export shows the title, period, "as of" date, legend with units, north arrow, scale bar, sources
   and logos, in Montserrat, with all area names visible and no overlapping labels.

## 11. Deliverables and milestones

1. Architecture, schema and wireframes for the dashboard and admin, plus answers to §12.
2. Gazetteer, boundaries, auth and roles, and product data model.
3. ENVI port, end to end.
4. 10-day and seasonal rainfall products.
5. Drought product (fetcher + manual fallback).
6. Public dashboard with overlays, archive and sharing.
7. Exports polish (labels, layouts, presentation), tests, docs and deployment.

Show a working demo at the end of each milestone.

## 12. Open questions to confirm with DA-RFO-CAR before building

- The exact PAGASA DroughtCaster access method and licence. Is municipal-level data available for CAR?
- The official class breaks and colours for the 10-day and seasonal rainfall maps. Should they match
  PAGASA's published legends?
- The source and format of the irrigation/dams dataset (NIA, BSWM, LGU), and whether service-area polygons
  exist.
- Which crops beyond rice and corn should appear in the crop overlay, and at what update frequency?
- Hosting constraints: Vercel only, or is a container host or VPS available for the QGIS worker? What are
  the domain and email provider for logins?
- Who approves publication, and is a two-step review (editor → admin) required?
- Languages: is English only enough, or is Filipino also needed?
