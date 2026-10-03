/** Pick a period to mark. Today's schedule with what is still outstanding. */
import Link from "next/link";

import { apiGet } from "@/lib/api";
import { TimetableTodaySchema, safe } from "@/lib/types";
import { Card, CardHeader, Empty, Pill } from "@/components/ui";

export const dynamic = "force-dynamic";

export default async function MarkIndex() {
  const raw = await apiGet("/api/timetable/today").catch(() => null);
  const today = safe(TimetableTodaySchema, raw);
  const periods = today?.periods ?? [];
  const outstanding = periods.filter((p) => !p.marked).length;

  return (
    <main className="relative z-[1] mx-auto max-w-[900px] px-4 pb-16 pt-6 md:px-5">
      <header className="mb-5 flex flex-wrap items-end justify-between gap-4 border-b-2 border-ink pb-3">
        <div>
          <h1 className="display m-0 text-[26px]">Mark attendance</h1>
          <p className="mt-0.5 font-mono text-xs text-ash">
            {today?.date ?? ""} · {periods.length} period(s) · {outstanding} outstanding
          </p>
        </div>
        <Link
          href="/dashboard"
          className="display rounded-[3px] border border-ink px-3.5 py-2 text-[12px] text-ink hover:bg-tint"
        >
          Dashboard
        </Link>
      </header>

      <Card ruled>
        <CardHeader title="Today" meta={today?.date} />
        {periods.length ? (
          <ul className="m-0 list-none p-0">
            {periods.map((p) => (
              <li
                key={p.slot_id}
                className="flex flex-wrap items-center justify-between gap-3 border-b border-dashed border-rule py-2.5 last:border-0"
              >
                <div className="min-w-0">
                  <span className="font-mono text-[13px] tnum text-ash">
                    {p.start_time}–{p.end_time}
                  </span>{" "}
                  <strong className="text-[14px]">{p.subject_code}</strong>{" "}
                  <span className="text-[13px] text-ash">
                    {p.subject_name} · {p.section_label} · {p.room}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  {p.locked ? (
                    <Pill tone="bad">locked</Pill>
                  ) : p.marked ? (
                    <Pill tone="ok">marked</Pill>
                  ) : (
                    <Pill tone="warn">not marked</Pill>
                  )}
                  <Link
                    href={`/mark/${p.slot_id}`}
                    className="display rounded-[3px] border px-3 py-1.5 text-[11px]"
                    style={
                      p.marked
                        ? { borderColor: "var(--rule)", color: "var(--ash)" }
                        : {
                            background: "var(--ink)",
                            borderColor: "var(--ink)",
                            color: "var(--card)",
                          }
                    }
                  >
                    {p.marked ? "Review" : "Mark now"}
                  </Link>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <Empty>
            No periods scheduled today. The timetable runs Monday to Friday — check back on a
            working day, or open a session from the dashboard.
          </Empty>
        )}
      </Card>
    </main>
  );
}
