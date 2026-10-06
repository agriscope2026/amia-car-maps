import { redirect } from "next/navigation";
import { currentUser } from "@/lib/server/auth";
import { AdminBar } from "../AdminBar";
import ReferenceUploads from "@/components/admin/ReferenceUploads";

export const dynamic = "force-dynamic";

export default async function ReferencePage() {
  const user = await currentUser();
  if (!user) redirect("/admin/login");
  if (user.role !== "admin") redirect("/admin");
  return (
    <>
      <AdminBar email={user.email} role={user.role} />
      <main className="page">
        <h1>Reference data</h1>
        <ReferenceUploads />
        <section>
          <h2>Gazetteer and boundaries</h2>
          <p className="muted">
            77 municipalities and 6 provinces from the CAR boundary shapefiles (EPSG:4326), with PSGC codes. To change the
            boundaries, replace the shapefiles in <code>worker/data/gis</code> and run <code>python -m scripts.build_reference</code>
            (see the admin guide).
          </p>
        </section>
      </main>
    </>
  );
}
