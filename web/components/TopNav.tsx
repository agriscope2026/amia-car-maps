import Link from "next/link";

const ICONS = {
  maps: (
    <path d="M9 3 3 5.5v15.5l6-2.5 6 2.5 6-2.5V3l-6 2.5L9 3Zm0 2.2 6 2.5v11.1l-6-2.5V5.2Z" />
  ),
  activities: (
    <path d="M9 4h6v2H9V4Zm-4 2h2v2h10V6h2v15H5V6Zm3.3 7.6L7 14.9l3 3 6-6-1.3-1.3-4.7 4.7-1.7-1.7Z" />
  ),
  about: (
    <path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm1 15h-2v-6h2v6Zm0-8h-2V7h2v2Z" />
  ),
};

/** The big Maps / Activities / About buttons of the top bar (shared by the map dashboard and the activities page). */
export default function TopNav({ active, mapsHref = "/", activitiesHref = "/activities" }: {
  active: "maps" | "activities";
  mapsHref?: string;
  activitiesHref?: string;
}) {
  const items = [
    { id: "maps", label: "Maps", href: mapsHref },
    { id: "activities", label: "Activities", href: activitiesHref },
    { id: "about", label: "About", href: "/about" },
  ] as const;
  return (
    <nav className="mainnav" aria-label="Main">
      {items.map((it) => (
        <Link key={it.id} href={it.href} className={it.id === active ? "on" : ""} aria-current={it.id === active ? "page" : undefined}>
          <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden fill="currentColor">
            {ICONS[it.id]}
          </svg>
          <span>{it.label}</span>
        </Link>
      ))}
    </nav>
  );
}
