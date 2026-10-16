# Admin user guide

This guide is for DA-RFO-CAR staff who prepare and publish maps on the CAR Agri-Climate Portal.

- **Editors** upload data, check it, edit the text and generate the print files.
- **Administrators** do everything editors do. They also publish and unpublish maps, and maintain the crops and
  irrigation layers.

## Signing in

Go to **`/admin`** on the portal and sign in with your email and password. If you forget your password, ask an
administrator to send a reset link.

## Making a map: the six steps

On the **Products** page, choose the map you want to make: ENVI, 10-day rainfall, Seasonal rainfall or Drought
forecast.

1. **Period and source.** Enter the issue date (the "as of" date) and the period the map covers:
   - **10-day rainfall:** the first and last day, for example October 1 and October 10, 2026. The template
     has one column per day (DAY_1 … DAY_10, in mm; DAY_1 is the first day). The system makes **one map per day**
     (no 10-day total map).
   - **Seasonal rainfall and drought:** the first month (and, for seasonal rainfall, the last month).
   - **ENVI:** the weights are drought forecast 70 %, historical damage 15 % and exposure (standing crops, plus
     livestock when uploaded) 15 %. You can change them (they must add up to 1), and the way classes are drawn.
   - **Drought forecast from PAGASA:** on the ENVI and Drought forecast upload pages, **Fetch from PAGASA
     DroughtCaster** fills in the drought forecast file for the six CAR provinces from
     https://droughtcaster.pagasa.dost.gov.ph/ and sets the issue date and period from it. Then click **Validate** as
     for an upload. If PAGASA cannot be reached, upload the template instead.
   - **ENVI monthly update:** each month, make a new ENVI version with the new drought forecast, the new standing
     rice and corn (with its "as of" date) and the latest **HVCDP Regional Summary**. Historical damage and the
     livestock inventory can be left empty: the files of the latest ENVI issue are reused (the upload page says
     which ones). Upload a new damage file only when it changes, and a new livestock file each quarter. The new issue
     gets a season ENVI map plus one map per forecast month, all computed from the new forecast; earlier issues stay
     in the archive. See *ENVI: high-value crops and livestock* below.
2. **Download the template.** Click **Download template** next to each file. The template already lists all 77
   municipalities (or the 6 provinces for drought). Fill in the values and keep the PSGC, province and
   municipality columns.
   - Rainfall is in **millimetres (mm)**.
   - Crop and damage areas are in **hectares (ha)**. Livestock is in **number of heads**.
   - Drought uses the PAGASA words: *not affected*, *dry condition*, *dry spell*, *drought*.
   - Leave a cell empty if there is no value. That municipality will show as "No data".
3. **Upload and validate.** Choose the file and click **Validate**. The report shows:
   - **Red** messages: problems that must be fixed, for example "row 12, column RAINFALL_MM: 'abc' is not a
     number". Fix the file and upload it again.
   - **Yellow** messages: things to check, for example a very high value, a name matched approximately, or
     missing municipalities.
   - **Names not found**: pick the right municipality in the **Assign to** list. The closest names are
     suggested first. The file is checked again straight away.
   - Province rows and "CAR" total rows are skipped automatically. Paracelis is placed in Mountain Province even
     if it is listed under Kalinga.
4. **Preview.** Check the map and the legend. For seasonal rainfall and drought, use the list to see each month.
5. **Save draft.** This opens the draft page.
6. **On the draft page:**
   - **Text:** edit the title, subtitle, notes, disclaimer and sources.
   - **Agricultural recommendations:** a draft is written for you from the data. Edit it freely. Put each
     recommendation on its own line starting with "-". **Generate automatically** brings back the suggested
     text. Click **Save text**.
   - **Generate exports:** for rainfall and drought this makes, for **every map** (each day or month), a print-ready
     **PNG (400 dpi)**, plus one ZIP with all of them (about 12 seconds per map). No PDFs are made. For ENVI it makes, for
     the season outlook and each month, the **presentation** (landscape, 5760×3240) and the **A4 poster** (portrait,
     450 dpi) as PNG images, plus one ZIP with them and the computation Excel (about a minute). When it is done, the
     page confirms that all 77 municipality names and 6 province names are visible with no overlapping labels.
     Download and check the files.
   - **Publish** (administrators only): the map appears on the public dashboard straight away. If an earlier
     version of the same map was published, it is archived.

If you change the text after generating exports, generate them again before publishing.

## ENVI: high-value crops and livestock

The third ENVI indicator measures what is exposed to the drought. Besides rice and corn it can include high-value
crops (HVC) and livestock & poultry. Both are optional uploads on the ENVI upload page.

**Hectares and heads are never added together.** Rice, corn and HVC are all in hectares, so they are added into one
crop area. Livestock is counted in heads, so it is kept apart:
1. Each species is converted to **livestock units (TLU)** so that a chicken does not count like a carabao (carabao 0.7,
   cattle and horse 0.65, swine 0.25, goat and sheep 0.1, chicken and duck 0.01 per head; bee colonies are listed but
   not counted).
2. Crop area and livestock units are each rescaled to 0–1 (min–max).
3. **Exposure = 0.75 × crop area + 0.25 × livestock.** Change the livestock share on the upload page (next to the
   livestock file) if DA-RFO-CAR decides on another split.

Without a livestock file the indicator is the crop area alone, as before.

### High-value crops: the HVCDP Regional Summary

Upload the **HVCDP Regional Summary** workbook exactly as HVCDP sends it (e.g. *HVC REGIONAL SUMMARY
2025-2026.xlsx*). There is no template: the file has one row per planting with the date planted, commodity, crop
group, area planted (ha) and target month of harvest.
- **Large file:** the workbook is over 5 MB. The upload page reads it in your browser and uploads only the columns
  it needs (a few hundred kB). It says how many planting records it read.
- **Same date as rice and corn:** the HVC **standing area** is computed for the **"Standing crops as of"** date
  you enter next to the rice and corn file (e.g. September 30, 2026). A crop is standing if it was planted on or
  before that date and is not yet harvested. Tomato, chayote and other multi-harvest crops are counted for about
  9 weeks after their target harvest. Banana, coffee, cacao, mango, citrus and other tree crops always count once
  planted. Plantings after the date are not counted.
- **The crop-stage columns of the workbook are not used.** They are computed from the day the file is opened, so
  they change every day and do not match any fixed date.
- **El Niño timing:** the validation report shows, for each outlook month, how much HVC will still be in the field
  and how much is due for harvest. Most vegetables standing at the end of September are harvested before the
  drought months (January–March); crops planted later are not in the file yet. Ask HVCDP for the dry-season planting
  targets.
- **Things the report flags:** provinces with no records at all (e.g. Abra – their HVC counts as 0 until HVCDP sends
  data), records without a crop group (filled in from the commodity), the same commodity spelled differently
  (Peanut / peanut / PEANUT, merged), records without a target harvest or with one before the planting date (the
  usual duration of that commodity is used), and single records of 200 ha or more (check that they are new plantings
  and not a municipal total or an old plantation).

### Livestock & poultry inventory

- **Quarterly:** upload the DA livestock inventory each quarter. Title rows, the two header rows, the CAR total and
  province subtotal rows are handled automatically, or use **Download template** (one row per municipality).
- **"Inventory as of":** enter the inventory date, normally the last day of the quarter (the **End of last quarter**
  button fills it in). If the file title gives a different month (e.g. "As of March, 2026" in a "2nd QTR" sheet), the
  report asks you to check which is right.
- **Reused between quarters:** without a new file, the latest issue's inventory and its date are reused. Untick
  *Reuse …* to leave livestock out of an issue.
- **Things the report flags:** a province total that differs from the sum of its municipalities (the municipal
  figures are used), two animal columns with the same figures in every municipality (usually a copy-paste error),
  and municipalities with no figures (counted as 0).

The dates of each input are printed on the presentation, the poster and the Methodology sheet of the Excel. The
Computation sheet shows the livestock share, the livestock units and the exposure formula, and recalculates when
you change them.

## How the maps look

The print maps follow the official DA-RFO-CAR layouts in the `sample data` folder:
- **10-day rainfall** (`10-day_sample.jpg`): one map per day, titled with the date, e.g. "September 24", with
  "(Valid from September 24 – October 3, 2026)" underneath. The legend runs from 0–5 No Rain to 400+ Extreme Rain.
- **Seasonal rainfall** (`seasonal_sample.jpg`): one map per month, with white boundary lines. The legend runs from
  0–50 Minimal Rainfall to 500+ Extreme Rainfall.
- **ENVI** (`envi_sample.png`): the presentation (overview, criteria and weights, recommended actions, legend,
  summary, top 10) and the A4 poster with the full recommendations. The ENVI map in them, and the ENVI print
  map, are drawn in the same style as the other maps. The ENVI legend (0.00–0.20 Very Low … 0.80–1.00 Very High)
  is kept, and the print map lists the recommended actions under the legend.

To show the PAGASA logo next to the AMIA logo at the bottom of the maps, save the official logo as
`worker/assets/logos/PAGASA_logo.png`.

Under the legend of every 10-day, seasonal and drought map there is a **Farm Recommendations** block: one short
piece of advice each for **rice**, **corn** and **HVC** (high-value crops such as vegetables).
- **Drafted for you:** the advice is written automatically from the forecast (heavy-rain days, dry months, drought
  onset…).
- **Editable:** change it on the version page under *Farm recommendations*. Keep each to about 230 characters;
  longer text is printed smaller. **Generate automatically** brings back the drafted text.
- **Where it appears:** on every map of the product, the slides, the social cards, the dashboard and photo mode.
- **Published versions too:** they can be edited like the recommendations (see *Editing a published product*).

The drought legend uses red for **Drought**. The seasonal legends show a description next to each range
(for example "100 - 200  Moderate Rainfall").

## Municipality details (dashboard)

Clicking a municipality on the dashboard opens a details window. It shows:
- the value and category on the current map;
- the values day by day or month by month (click one to show that map);
- the ENVI indicators (with the HVC area, livestock heads and livestock units when they were uploaded);
- the standing crops (all crops, in hectares);
- the farm recommendations;
- the recommendations that name the municipality or its province, with the full list below.

## Standing crops on the dashboard and on the maps

- **Several crops at once:** in the dashboard's *Standing crops* overlay, tick one or more crops. In
  *Proportional circles* mode each crop is drawn as a circle in its own colour. *Choropleth* mode shows one crop,
  shaded in that crop's colour.
- **Crop colours:** on **Reference data → Crop colours**, choose a colour for each crop and click
  **Save colours**.
- **Any crops in the upload:** the standing crops file can have as many crop columns as you need (Rice, Corn, Coffee,
  Cabbage, …), in hectares. Title rows above the header are fine, and a plain "Total" column is ignored.
- **Seasonal, drought and ENVI maps:** on a seasonal rainfall, drought or ENVI version, under *Exports → Standing crops on the maps*,
  tick the crops to draw as proportional circles on the exported maps (for ENVI also on the presentation and the
  poster), with a legend of the crop colours and circle sizes. Then generate or regenerate the exports. The choice is kept for the next regeneration.

The dashboard basemap takes a tint that matches the selected map: blue for rainfall, sand for drought, green for
ENVI.

## Photo mode (dashboard)

On the public dashboard, **Photo mode** opens the finished images full screen, with the recommendations beside
them:
- **ENVI** shows a **title page**, the season outlook, then each month's ENVI (each with its own classes, top 10,
  crops at risk and recommendations), then a **summary page** (areas per class for the season and every month,
  crops at risk, the top 10) and the **recommendations page**. Switch between **▭ Presentation** (landscape) and
  **▯ A4** (portrait poster) in the top bar: every page comes in both formats.
- **10-day rainfall, seasonal rainfall and drought** show a **title page**, then the print map for each day or month,
  then a **summary page** and an **agricultural recommendations page**. The pages are made with the exports, so after
  editing the recommendations click **Regenerate exports** to update them.
- **Title page** (all products): the DA-RFO-CAR AMIA Program header, the product title with the "for Cordillera
  Administrative Region" banner, the period and issue date, the map legend, QR codes to the ACAP website
  (acap-car.github.io) and the interactive maps (amia-car-maps.vercel.app), and the source (DOST-PAGASA).
- **Summary page:** the **current condition** (the first day or month of the forecast; for drought and ENVI also the
  observed PAGASA situation when the forecast was fetched from DroughtCaster) and the **expected forecast** in plain
  sentences, then the key figures.
- **Agricultural recommendations page:** the rice, corn and high-value crop advice first, then the advisory.
- **Readable on a phone:** the summary and recommendations pages use large text that adjusts to the amount of content
  (bigger when there is little to say). The summary is always one page: when there is a lot to say, the less
  important figures are left out first. Long recommendations continue on another page ("Recommendations (1/2)",
  "(2/2)") rather than becoming too small to read on a phone. On a phone, ENVI photo mode opens in the
  portrait A4 format. The farm recommendations on the maps and the ENVI recommended actions also use the largest text
  that fits their space.
- **Zoom:** use the + / − / Fit / 100% buttons, the mouse wheel, a double-click, or two fingers on a phone. Drag to
  move around a zoomed image.
- **Moving between images:** ‹ › or the arrow keys go to the next or previous image. Esc closes photo mode.
- **Downloads:** each image has buttons to download it and its image package.
- **Sharing:** the share link keeps photo mode open.

The dashboard map also zooms out to show northern Luzon around CAR.

## Seasonal rainfall forecast from PAGASA

For the seasonal rainfall forecast you can either **upload** the seasonal template, or **fetch it from PAGASA**:
- *Products → Fetch latest seasonal forecast from PAGASA*, or
- *Fetch from PAGASA (CAR only)* in the seasonal upload page.

The portal reads PAGASA's seasonal forecast page
(https://www.pagasa.dost.gov.ph/climate/climate-prediction/seasonal-forecast) and keeps CAR only:
- "Forecast rainfall in mm": minimum / mean / maximum for each province and month;
- "Forecast rainfall in % normal".

Things to know:
- **Provincial values:** PAGASA's forecast is per province, so every municipality shows its province's mean.
- **Check before publishing:** PAGASA publishes these tables as images, so the values are read automatically
  (text recognition). The validation step shows every value read (province × month: min · mean · max · % of
  normal), with links to PAGASA's images. Values the reader is unsure about are listed in yellow. Compare them,
  then save the draft.
- **Automatic check:** the portal also checks PAGASA every morning. When a new outlook is out, a draft appears on
  the Products page (author "cron"). Nothing is published until an administrator publishes it.
- **If PAGASA changes its page,** the fetch reports that it could not find the table. Upload the template instead.

## The 10-day rainfall feed

The 10-day rainfall forecast is fetched automatically every morning from the Cordillera weather service. It gives
daily rainfall, so you get one map per day. When a
new forecast is available, a draft appears on the **Products** page (author "cron") with its exports already made.
An administrator only needs to open it, check it, adjust the recommendations if needed, and publish.

You can also fetch it yourself: **Products → Fetch latest 10-day rainfall forecast**. The service can take up to a
minute to respond.

## Editing a published product

Administrators can still change the text of a published version, especially the recommendations:
1. Open the version from **Products**.
2. Edit the text (recommendations, farm recommendations for rice, corn and HVC, notes…) and click
   **Save – update the dashboard**. The new text appears on the dashboard and in photo mode
   straight away.
3. Click **Regenerate exports**. The maps, presentation and poster are made again with the new text. Until
   they are ready, the previous files stay available for download.

Every change is recorded in the audit log. Editors can only change drafts.

## Deleting old versions

Administrators can permanently delete an **archived** version (or a draft):
- from the **Delete** button in the Versions list, or
- from the version page (*Delete this version*).

The version's maps and files are removed too (on Cloudflare R2 also its uploaded input files, unless another
version still uses them), and the deletion is recorded in the audit log. A published version cannot be deleted;
unpublish it first.

**Storage (administrators):** the **Storage** page lists the files in Cloudflare R2 that no version uses any more –
inputs of previews that were never saved, files of versions deleted earlier, files left behind when exports were
regenerated, and public copies of unpublished versions – with their size. Nothing is deleted until you click
**Delete … unused files** and confirm. Files from the last 24 hours are never touched. Regenerating exports now
removes the previous export's leftover files automatically.

## Unpublishing

Open the version and click **Unpublish**. It disappears from the dashboard but stays in the archive. Every version
is kept, with who made it and when.

## Reference data (administrators)

On **Reference data** you can update:

- **Standing crops:** use the standing-crops template, with one column per crop in hectares, and set the "as of"
  date. Every crop column becomes a choice in the dashboard's crop overlay.
- **Livestock template:** a blank livestock & poultry form with every municipality, for the provincial
  coordinators. The HVCDP Regional Summary and the livestock inventory themselves are uploaded with each ENVI issue.
- **Irrigation sources and dams:** a list with name, type (e.g. NIS, CIS, SWIP, SSIP, DAM, RIVER – any other type is accepted and gets its own colour and legend entry; an optional TYPE_LABEL column gives it a full name), latitude and
  longitude in decimal degrees, river, service area (ha), status and source. A GeoJSON file also works. Saving
  replaces the whole layer. Locations outside CAR, or with latitude and longitude swapped, are reported.

Always click **Validate** first, then **Save**.

## Audit log

**Audit log** (administrators) lists sign-ins, uploads, checks, edits, exports and publishing, with the time in
Philippine time.
