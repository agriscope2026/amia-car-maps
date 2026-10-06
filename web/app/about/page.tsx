import Link from "next/link";

export const metadata = { title: "About & methodology – CAR Agri-Climate Portal" };

export default function About() {
  return (
    <main className="page">
      <p>
        <Link href="/">← Back to the map</Link>
      </p>
      <h1>About the maps &amp; methodology</h1>
      <p className="muted">
        The CAR Agri-Climate Portal publishes climate-risk maps for the 77 municipalities and 6 provinces of the Cordillera
        Administrative Region. It is run by the Department of Agriculture – Regional Field Office, Cordillera Administrative
        Region (DA-RFO-CAR), Adaptation and Mitigation Initiative in Agriculture (AMIA) Program. Only products approved by a
        DA-RFO-CAR administrator appear here. Every map lists its validity period, its “as of” date and its sources.
      </p>

      <section id="envi">
        <h2>El Niño Vulnerability Index (ENVI)</h2>
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
            <strong>Standing crops</strong>: rice + corn area in hectares (ha) on the inventory date.
          </li>
        </ul>
        <p>
          Each indicator is min–max normalized to 0–1 (0 when all values are equal). The index is the weighted sum of the
          normalized indicators, using equal weights (⅓ each) unless stated otherwise. The index is split into five classes
          using equal intervals: Very Low &lt; 0.2, Low 0.2–0.4, Moderate 0.4–0.6, High 0.6–0.8 and Very High ≥ 0.8.
          Municipalities without data are hatched grey (“No data”). “Crop area at risk” is the standing crop area in the High
          and Very High municipalities.
        </p>
      </section>

      <section id="rainfall_dekad">
        <h2>10-day rainfall forecast</h2>
        <p>
          Shows the forecast rainfall total for one dekad (10 days), in <strong>millimetres (mm)</strong>, by municipality.
          Default classes are 0–10, 10–25, 25–50, 50–100, 100–150 and 150–200 mm, plus a class above 200 mm. A value equal
          to a class break belongs to the higher class (10 mm is in “10–25”). Each map states the dates it covers.
        </p>
      </section>

      <section id="rainfall_seasonal">
        <h2>Seasonal rainfall forecast</h2>
        <p>
          There is one map per month (classes 0–50, 50–100, 100–200, 200–300, 300–400 and 400–500 mm, plus a class above
          500 mm) and one map of the season total. When the source provides percent of normal, an extra map shows: way below
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
