import { ACTIVITY_STATUSES, statusLabel, type Activity } from "@/lib/activities";
import { fmtDate } from "@/lib/format";

/** "October 15, 2026 – November 30, 2026", one date, "until …" or "". */
export const dateRange = (a: Pick<Activity, "start_date" | "end_date">) =>
  a.start_date && a.end_date && a.start_date !== a.end_date
    ? `${fmtDate(a.start_date)} – ${fmtDate(a.end_date)}`
    : a.start_date
      ? fmtDate(a.start_date)
      : a.end_date
        ? `until ${fmtDate(a.end_date)}`
        : "";

export function StatusChip({ status }: { status: string }) {
  const s = ACTIVITY_STATUSES.find((x) => x.id === status);
  return (
    <span className="act-status" style={{ background: s?.color ?? "#757575" }}>
      {statusLabel(status)}
    </span>
  );
}
