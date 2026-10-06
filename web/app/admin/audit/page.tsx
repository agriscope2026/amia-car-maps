import { redirect } from "next/navigation";
import { currentUser } from "@/lib/server/auth";
import { listAudit } from "@/lib/server/repo";
import { AdminBar } from "../AdminBar";

export const dynamic = "force-dynamic";

export default async function AuditPage() {
  const user = await currentUser();
  if (!user) redirect("/admin/login");
  if (user.role !== "admin") redirect("/admin");
  const rows = await listAudit(300);
  return (
    <>
      <AdminBar email={user.email} role={user.role} />
      <main className="page">
        <h1>Audit log</h1>
        <section>
          <table className="data">
            <thead>
              <tr>
                <th>When (Asia/Manila)</th>
                <th>Who</th>
                <th>Action</th>
                <th>What</th>
                <th>Details</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i}>
                  <td>{new Date(r.at).toLocaleString("en-PH", { timeZone: "Asia/Manila" })}</td>
                  <td>{r.actor}</td>
                  <td>{r.action}</td>
                  <td>
                    {r.entity} {r.entity_id ? <code className="small">{String(r.entity_id).slice(0, 12)}</code> : null}
                  </td>
                  <td className="small">{r.details ? JSON.stringify(r.details).slice(0, 160) : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      </main>
    </>
  );
}
