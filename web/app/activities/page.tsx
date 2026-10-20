import { promises as fs } from "fs";
import path from "path";
import ActivitiesDashboard from "@/components/ActivitiesDashboard";
import type { Gazetteer } from "@/lib/types";

export const revalidate = 3600;
export const metadata = { title: "Activities – AMIA CAR MAPS" };

export default async function ActivitiesPage() {
  const geo = JSON.parse(await fs.readFile(path.join(process.cwd(), "public", "geo", "car.json"), "utf-8")) as Gazetteer;
  return <ActivitiesDashboard geo={geo} />;
}
