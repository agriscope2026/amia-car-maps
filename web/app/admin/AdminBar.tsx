"use client";

import Link from "next/link";
import { api } from "@/lib/client";

export function AdminBar({ email, role }: { email: string; role: string }) {
  return (
    <header className="topbar">
      <div className="logos">
        <img src="/logos/da-car.webp" alt="DA-RFO-CAR" width={40} height={40} />
      </div>
      <div className="titles">
        <h1>Admin workspace</h1>
        <p>
          {email} · {role}
        </p>
      </div>
      <nav className="row toplinks" style={{ display: "flex" }}>
        <Link href="/admin">Products</Link>
        {role === "admin" && <Link href="/admin/reference">Reference data</Link>}
        {role === "admin" && <Link href="/admin/audit">Audit log</Link>}
        <Link href="/">Dashboard</Link>
        <a
          href="#"
          onClick={async (e) => {
            e.preventDefault();
            await api("/api/auth/logout", { method: "POST" });
            window.location.href = "/admin/login";
          }}
        >
          Sign out
        </a>
      </nav>
    </header>
  );
}
