import Link from "next/link";
import { redirect } from "next/navigation";
import { currentUser } from "@/lib/server/auth";
import { listPublished, listVersions } from "@/lib/server/repo";
import { PRODUCT_TYPES } from "@/lib/types";
import { fmtDate } from "@/lib/format";
import { AdminBar } from "./AdminBar";
import { DeleteVersionButton, FeedButton, UnpublishButton } from "./actions";

export const dynamic = "force-dynamic";

export default async function AdminHome() {
  const user = await currentUser();
  if (!user) redirect("/admin/login");
  const [versions, published] = await Promise.all([listVersions(), listPublished()]);
  const own = new Set(versions.map((v) => v.id));
  const demo = published.filter((p) => !own.has(p.id));
  const typeLabel = (t: string) => PRODUCT_TYPES.find((x) => x.id === t)?.label ?? t;

  return (
    <>
      <AdminBar email={user.email} role={user.role} />
      <main className="page">
        <h1>Map products</h1>
        <section>
          <h2>Create a product</h2>
          <p className="muted">Upload → validate → preview → edit text → generate exports → publish.</p>
          <div className="row">
            {PRODUCT_TYPES.map((t) => (
              <Link key={t.id} className="btn secondary" href={`/admin/new/${t.id}`}>
                + {t.label}
              </Link>
            ))}
          </div>
          <h3>10-day rainfall feed</h3>
          <p className="muted small">
            Pulls the latest 10-day forecast (rainfall in mm per municipality) from the Cordillera weather API. The result
            becomes a draft that still needs review and publishing.
          </p>
          <FeedButton />
          <h3>Seasonal rainfall forecast from PAGASA</h3>
          <p className="muted small">
            Reads the latest CAR values (provincial forecast rainfall in mm and % of normal) from PAGASA&apos;s seasonal forecast
            page. The values are read from PAGASA&apos;s table images, so check them against the image before publishing.
          </p>
          <FeedButton type="rainfall_seasonal" label="Fetch latest seasonal forecast from PAGASA" />
        </section>

        <section>
          <h2>Versions</h2>
          {versions.length === 0 ? (
            <p className="muted">No versions yet.</p>
          ) : (
            <table className="data">
              <thead>
                <tr>
                  <th>Product</th>
                  <th>Period</th>
                  <th>As of</th>
                  <th>Version</th>
                  <th>Status</th>
                  <th>Author</th>
                  <th>Created</th>
                  {user.role === "admin" && <th></th>}
                </tr>
              </thead>
              <tbody>
                {versions.map((v) => (
                  <tr key={v.id}>
                    <td>
                      <Link href={`/admin/versions/${v.id}`}>{typeLabel(v.type)}</Link>
                    </td>
                    <td>{v.period?.label}</td>
                    <td>{v.issued ? fmtDate(v.issued) : ""}</td>
                    <td>v{v.version}</td>
                    <td>
                      <span className={`status ${v.status}`}>{v.status}</span>
                    </td>
                    <td>{v.author}</td>
                    <td>{new Date(v.created_at).toLocaleString("en-PH", { timeZone: "Asia/Manila" })}</td>
                    {user.role === "admin" && (
                      <td>
                        {v.status === "archived" && (
                          <DeleteVersionButton id={v.id} label={`${typeLabel(v.type)} v${v.version} (archived)`} small />
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        {demo.length > 0 && (
          <section>
            <h2>Bundled demo products</h2>
            <p className="muted small">
              Shipped with the app for local development. Publishing a newer version of the same product replaces them;
              admins can also unpublish them.
            </p>
            <table className="data">
              <tbody>
                {demo.map((p) => (
                  <tr key={p.id}>
                    <td>{typeLabel(p.type)}</td>
                    <td>{p.period.label}</td>
                    <td>{p.synthetic ? "synthetic demo data" : "sample data"}</td>
                    <td>{user.role === "admin" && <UnpublishButton id={p.id} />}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        )}
      </main>
    </>
  );
}
