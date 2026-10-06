import { promises as fs } from "fs";
import path from "path";
import { notFound, redirect } from "next/navigation";
import { currentUser } from "@/lib/server/auth";
import { getVersion } from "@/lib/server/repo";
import type { Gazetteer } from "@/lib/types";
import { AdminBar } from "../../AdminBar";
import VersionEditor from "@/components/admin/VersionEditor";

export const dynamic = "force-dynamic";

export default async function VersionPage({ params }: { params: Promise<{ id: string }> }) {
  const user = await currentUser();
  if (!user) redirect("/admin/login");
  const v = await getVersion((await params).id);
  if (!v || !v.payload) notFound();
  const geo = JSON.parse(await fs.readFile(path.join(process.cwd(), "public", "geo", "car.json"), "utf-8")) as Gazetteer;
  return (
    <>
      <AdminBar email={user.email} role={user.role} />
      <VersionEditor version={JSON.parse(JSON.stringify(v))} role={user.role} geo={geo} />
    </>
  );
}
