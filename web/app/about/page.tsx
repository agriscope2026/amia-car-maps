import Link from "next/link";

export const metadata = { title: "About & methodology – AMIA CAR MAPS" };

export default function About() {
  return (
    <main className="page">
      <p>
        <Link href="/">← Back to the map</Link>
      </p>
      <h1>About the maps &amp; methodology</h1>
      <p className="muted">
        AMIA CAR MAPS publishes climate-risk maps for the 77 municipalities and 6 provinces of the Cordillera
        Administrative Region. It is run by the Department of Agriculture – Regional Field Office, Cordillera Administrative
        Region (DA-RFO-CAR), Adaptation and Mitigation Initiative in Agriculture (AMIA) Program. Only products approved by a
        DA-RFO-CAR administrator appear here. Every map lists its validity period, its “as of” date and its sources.
      </p>

      <section id="envi">
        <h2>El Niño Vulnerability Index (ENVI)</h2>
        <blockquote className="plain-quote">
          <strong>In short:</strong> a municipality is more vulnerable to El Niño when drought is forecast there, when El
          Niño has damaged its crops before, and when it has a lot of standing crops in the field. The higher all
          three are, the higher its El Niño vulnerability.
        </blockquote>
        <p>The index combines three indicators for each municipality:</p>
        <ul>
          <li>
            <strong>Drought forecast</strong> (PAGASA). Monthly categories are scored: not affected = 0, dry condition = 1,
            dry spell = 2, drought = 3. The scores are summed over the outlook months.
          </li>
          <li>
            <strong>Historical El Niño damage</strong>: the mean damaged crop area per event year, in hectares (ha).
          </li>
          <li>
            <strong>Standing crops</strong>: rice + corn area in hectares (ha) on the inventory date, plus the high-value crops
            (vegetables, root crops, spices, cut flowers, fruit and plantation crops) standing on the same date, computed from
            the HVCDP planting records. When a livestock &amp; poultry inventory is included, this indicator becomes
            <strong> exposure</strong>: the crop area and the livestock (heads converted to livestock units, e.g. carabao 0.7,
            swine 0.25, chicken 0.01 per head) are each normalized to 0–1 and combined (by default 75 % crops, 25 %
            livestock) – hectares and heads are never added together.
          </li>
        </ul>
        <p>
          Each indicator is min–max normalized to 0–1 (0 when all values are equal). The index is the weighted sum of the
          normalized indicators. By default the drought forecast counts for 0.7 and historical damage and standing crops
          (exposure) for 0.15 each; a map states other weights if they were used:
        </p>
        <div className="formula" role="math" aria-label="x norm equals x minus x min, divided by x max minus x min">
          x<sub>norm</sub> = (x − x<sub>min</sub>) / (x<sub>max</sub> − x<sub>min</sub>)
        </div>
        <div
          className="formula"
          role="math"
          aria-label="ENVI equals w drought times drought norm, plus w damage times damage norm, plus w crops times crops norm"
        >
          ENVI = w<sub>D</sub> · Drought<sub>norm</sub> + w<sub>H</sub> · Damage<sub>norm</sub> + w<sub>C</sub> ·
          Crops<sub>norm</sub>
        </div>
        <p className="small muted">
          where x<sub>min</sub> and x<sub>max</sub> are the lowest and highest values of that indicator across all areas,
          and the weights w<sub>D</sub> + w<sub>H</sub> + w<sub>C</sub> = 1 (default 0.7, 0.15 and 0.15). ENVI ranges from 0 (least
          vulnerable) to 1 (most vulnerable). If any indicator is missing for an area, its ENVI is “No data”.
        </p>
        <p>
          The index is split into five classes
          using equal intervals: Very Low &lt; 0.2, Low 0.2–0.4, Moderate 0.4–0.6, High 0.6–0.8 and Very High ≥ 0.8.
          Municipalities without data are hatched grey (“No data”). “Crop area at risk” is the standing crop area in the High
          and Very High municipalities.
        </p>
        <p>
          <strong>Monthly ENVI.</strong> Besides the season map, there is one ENVI map per outlook month. It uses only that
          month’s drought forecast, scaled as score ÷ 3 (not affected 0, dry condition 0.33, dry spell 0.67, drought 1).
          Historical damage and standing crops are the same as in the season map. A fixed scale is used so that a month with
          drought everywhere still counts fully; min–max would turn identical values into 0.
        </p>
      </section>

      <section id="rainfall_dekad">
        <h2>10-day rainfall forecast</h2>
        <p>
          Shows the forecast rainfall for each day of one dekad (10 days), in <strong>millimetres (mm)</strong>, by
          municipality, one map per day. Default classes are 0–10, 10–25, 25–50, 50–100, 100–150 and 150–200 mm, plus a class above 200 mm. A value equal
          to a class break belongs to the higher class (10 mm is in “10–25”). Each map states the dates it covers.
        </p>
      </section>

      <section id="rainfall_seasonal">
        <h2>Seasonal rainfall forecast</h2>
        <p>
          There is one map per month (classes 0–50, 50–100, 100–200, 200–300, 300–400 and 400–500 mm, plus a class above
          500 mm). When the source provides percent of normal, an extra map shows: way below
          normal (≤ 40%), below normal (41–80%), near normal (81–120%) and above normal (&gt; 120%).
        </p>
        <p>1 mm of rainfall = 1 litre of water per square metre, or 10 m³ per hectare.</p>
      </section>

      <section id="drought">
        <h2>Drought forecast</h2>
        <p>
          Based on PAGASA drought outlooks (DroughtCaster or the official outlook table) and clipped to CAR. There is one
          map per month. The categories follow PAGASA:
        </p>
        <ul>
          <li>
            <strong>Dry condition</strong>: 2 consecutive months of below-normal rainfall (21–60% reduction).
          </li>
          <li>
            <strong>Dry spell</strong>: 3 consecutive months of below-normal rainfall, or 2 consecutive months of
            way-below-normal rainfall (more than 60% reduction).
          </li>
          <li>
            <strong>Drought</strong>: 3 consecutive months of way-below-normal rainfall, or 5 consecutive months of
            below-normal rainfall.
          </li>
        </ul>
      </section>

      <section>
        <h2>Overlays</h2>
        <p>
          <strong>Standing crops</strong> show the area in hectares per municipality, as proportional circles or as a
          choropleth. <strong>Irrigation sources</strong> show national and communal irrigation systems (NIA), SWIP/SSIP
          and dams, as maintained by DA-RFO-CAR.
        </p>
      </section>

      <section>
        <h2>Disclaimer</h2>
        <p>
          DA-RFO-CAR is not liable for any loss or damage arising from the use of these maps. Forecasts are indicative and
          valid only for the period and areas stated. For official forecasts, refer to DOST-PAGASA.
        </p>
        <p className="small muted">
          Basemaps: © Esri, HERE, Garmin, Maxar; © OpenStreetMap contributors; © OpenTopoMap (CC-BY-SA). Font: Montserrat (SIL Open Font
          License).
        </p>
      </section>
    </main>
  );
}
