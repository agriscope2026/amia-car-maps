import { promises as fs } from "fs";
import path from "path";
import { redirect } from "next/navigation";
import { currentUser } from "@/lib/server/auth";
import ActivitiesAdmin from "@/components/admin/ActivitiesAdmin";
import type { Gazetteer } from "@/lib/types";
import { AdminBar } from "../AdminBar";

export const dynamic = "force-dynamic";

export default async function ActivitiesAdminPage() {
  const user = await currentUser();
  if (!user) redirect("/admin/login");
  const geo = JSON.parse(await fs.readFile(path.join(process.cwd(), "public", "geo", "car.json"), "utf-8")) as Gazetteer;
  return (
    <>
      <AdminBar email={user.email} role={user.role} />
      <main className="page">
        <h1>Activities</h1>
        <p className="muted">
          Activities in the municipalities – to conduct, ongoing, completed or postponed – and the map they respond to. They appear
          on the public <a href="/activities">activities page</a> next to the vulnerable areas of the published maps as soon as they
          are saved.
        </p>
        <ActivitiesAdmin geo={geo} />
      </main>
    </>
  );
}
