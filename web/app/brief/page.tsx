import { promises as fs } from "fs";
import path from "path";
import Brief from "@/components/Brief";
import type { Gazetteer } from "@/lib/types";

export const metadata = { title: "Climate-risk brief – AMIA CAR MAPS" };

/** One-page printable brief for a municipality (?area=KEY) or a province (?province=Name) from a published map
 * (?product=ID&layer=ID; the latest ENVI when no product is given). Printed to PDF from the browser. */
export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | undefined>> }) {
  const q = await searchParams;
  const geo = JSON.parse(await fs.readFile(path.join(process.cwd(), "public", "geo", "car.json"), "utf-8")) as Gazetteer;
  return <Brief geo={geo} productId={q.product} layerId={q.layer} area={q.area} province={q.province} />;
}
