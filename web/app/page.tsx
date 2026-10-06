import { promises as fs } from "fs";
import path from "path";
import Dashboard from "@/components/Dashboard";
import type { Gazetteer } from "@/lib/types";

export const revalidate = 3600;

export default async function Page() {
  const geo = JSON.parse(await fs.readFile(path.join(process.cwd(), "public", "geo", "car.json"), "utf-8")) as Gazetteer;
  return <Dashboard geo={geo} />;
}
