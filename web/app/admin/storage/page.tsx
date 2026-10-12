import { redirect } from "next/navigation";
import { currentUser } from "@/lib/server/auth";
import { AdminBar } from "../AdminBar";
import StorageCleanup from "./StorageCleanup";

export const dynamic = "force-dynamic";

export default async function StoragePage() {
  const user = await currentUser();
  if (!user) redirect("/admin/login");
  if (user.role !== "admin") redirect("/admin");
  return (
    <>
      <AdminBar email={user.email} role={user.role} />
      <main className="page">
        <h1>Storage</h1>
        <p className="muted">
          Files in Cloudflare R2 that no version uses any more: inputs of previews that were never saved or of deleted
          versions, export files of deleted versions, files left behind when exports were regenerated, and public
          copies of versions that are no longer published. Files from the last 24 hours are never removed.
        </p>
        <StorageCleanup />
      </main>
    </>
  );
}
