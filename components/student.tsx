/**
 * Student attendance views.
 *
 * Server components — no interactivity is needed, so none is shipped. The ring is inline SVG
 * and the calendar is a CSS grid; neither costs a byte of JavaScript.
 */
import { Card, CardHeader, Empty, Mark } from "@/components/ui";

type Projection = {
  can_miss: number;
  reachable: boolean;
  at_risk: boolean;
  /** null until the first class is held — there is no percentage of nothing. */
  current_pct: number | null;
  projected_pct: number;
  remaining: number;
  /** Consecutive classes to attend to reach the minimum; 0 when already there. */
  classes_needed?: number;
};

type Subject = {
  subject_id: number;
  code: string;
  name: string;
  counted: number;
  present: number;
  attendance_pct: number | null;
  remaining: number;
  projection: Projection;
};

export type StudentSummary = {
  threshold_pct: number;
  overall: Projection & { counted: number; present: number };
  subjects: Subject[];
  calendar: { date: string; status: string; periods: number; statuses: string[] }[];
  student: { id: number; display_name: string; roll_number: string | null };
};

const STATUS_COLOR: Record<string, string> = {
  present: "var(--status-present)",
  late: "var(--status-late)",
  absent: "var(--status-absent)",
  excused: "var(--status-excused)",
  on_leave: "var(--status-leave)",
};

/** Must match `MARK_LETTER` in components/ui.tsx — the register's own alphabet. */
const STATUS_LETTER: Record<string, string> = {
  present: "P",
  late: "L",
  absent: "A",
  excused: "E",
  on_leave: "O",
};

/* --------------------------------------------------------------- the ring */

export function AttendanceRing({
  pct,
  threshold,
}: {
  pct: number | null;
  threshold: number;
}) {
  const none = pct === null;
  const size = 168;
  const stroke = 14;
  const r = (size - stroke) / 2;
  const circumference = 2 * Math.PI * r;
  const clamped = Math.max(0, Math.min(100, pct ?? 0));
  const dash = (clamped / 100) * circumference;
  const meets = none || clamped >= threshold;
  const colour = none ? "var(--rule)" : meets ? "var(--status-present)" : "var(--status-absent)";

  return (
    <figure className="m-0 flex flex-col items-center">
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${size} ${size}`}
        role="img"
        aria-label={`Attendance ${clamped.toFixed(1)} percent, minimum ${threshold} percent`}
      >
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--rule)"
          strokeWidth={stroke}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={colour}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${dash} ${circumference - dash}`}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
        {/* The threshold is a tick on the ring, so "how far off am I" is visible, not inferred. */}
        <line
          x1={size / 2}
          y1={stroke / 2 + 1}
          x2={size / 2}
          y2={stroke + 7}
          stroke="var(--ink)"
          strokeWidth={2}
          transform={`rotate(${(threshold / 100) * 360 - 90} ${size / 2} ${size / 2})`}
        />
        <text
          x="50%"
          y="47%"
          textAnchor="middle"
          fill="var(--ink)"
          style={{ font: "600 34px var(--font-mono)", fontVariantNumeric: "tabular-nums" }}
        >
          {none ? "—" : `${clamped.toFixed(1)}%`}
        </text>
        <text
          x="50%"
          y="63%"
          textAnchor="middle"
          fill="var(--ash)"
          style={{ font: "600 11px var(--font-label)", letterSpacing: "0.13em" }}
        >
          MINIMUM {threshold}%
        </text>
      </svg>
      <figcaption className="sr-only">
        {none ? "No classes held yet" : `Current attendance ${clamped.toFixed(1)}%`}, against a minimum of {threshold}%.
      </figcaption>
    </figure>
  );
}

/* ------------------------------------------------------- the can-miss line */

export function CanMiss({ p, threshold }: { p: Projection; threshold: number }) {
  if (p.current_pct === null) {
    return (
      <div>
        <span className="label block">No classes held yet</span>
        <p className="mt-1 text-[13.5px] text-ash">
          Your percentage starts with your first class. You need to attend at least {threshold}% of classes
          {p.remaining ? <> — {p.remaining} are scheduled for the rest of this term</> : null}.
        </p>
      </div>
    );
  }
  if (!p.reachable) {
    return (
      <div>
        <span className="label block">Can you still reach {threshold}%?</span>
        <p className="mt-1 font-mono text-[26px] font-semibold" style={{ color: "var(--oxide)" }}>
          Not this term
        </p>
        <p className="mt-1 text-[13.5px] text-ash">
          Attending all {p.remaining} remaining classes would still leave you at{" "}
          <strong className="tnum">{p.projected_pct}%</strong>. Talk to your faculty adviser
          about a correction or medical leave.
        </p>
      </div>
    );
  }

  return (
    <div>
      <span className="label block">You can still miss</span>
      <p
        className="mt-1 font-mono text-[34px] font-semibold tnum"
        style={{ color: p.can_miss === 0 ? "var(--oxide)" : "var(--ink)" }}
      >
        {p.can_miss} <span className="text-[16px] font-normal text-ash">more class{p.can_miss === 1 ? "" : "es"}</span>
      </p>
      <p className="mt-1 text-[13.5px] text-ash">
        {p.can_miss === 0
          ? `You are at ${p.current_pct}%. Miss one more and you drop below ${threshold}%.`
          : `Out of ${p.remaining} still scheduled, before dropping below ${threshold}%.`}
      </p>
    </div>
  );
}

/* --------------------------------------------------------- subject bars */

export function SubjectBars({ subjects, threshold }: { subjects: Subject[]; threshold: number }) {
  if (!subjects.length) return <Empty>No subjects recorded yet.</Empty>;

  return (
    <ul className="m-0 list-none p-0">
      {subjects.map((s) => {
        const pct = s.attendance_pct ?? 0;
        const below = pct < threshold;
        return (
          <li key={s.subject_id} className="border-b border-dashed border-rule py-2.5 last:border-0">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <div className="min-w-0">
                <strong className="font-mono text-[13px]">{s.code}</strong>{" "}
                <span className="text-[13.5px] text-ash">{s.name}</span>
              </div>
              <div className="font-mono text-[13px] tnum" style={{ color: below ? "var(--oxide)" : "var(--ink)" }}>
                {pct}%{" "}
                <span className="text-ash">
                  ({s.present}/{s.counted})
                </span>
              </div>
            </div>

            <div
              className="relative mt-1.5 h-2.5 w-full overflow-hidden rounded-[var(--radius-sm)]"
              style={{ background: "var(--tint-hard)" }}
              role="img"
              aria-label={`${s.code}: ${pct} percent, minimum ${threshold} percent`}
            >
              <div
                className="h-full rounded-[var(--radius-sm)]"
                style={{
                  width: `${Math.max(0, Math.min(100, pct))}%`,
                  background: below ? "var(--status-absent)" : "var(--status-present)",
                }}
              />
              {/* Threshold marker — the number alone does not show how close the edge is. */}
              <div
                className="absolute top-0 h-full"
                style={{ left: `${threshold}%`, width: 2, background: "var(--ink)" }}
              />
            </div>

            <p className="mt-1 text-[12.5px] text-ash">
              {s.projection.reachable
                ? `Can miss ${s.projection.can_miss} of ${s.remaining} remaining.`
                : `Cannot reach ${threshold}% this term even with a perfect record.`}
            </p>
          </li>
        );
      })}
    </ul>
  );
}

/* ------------------------------------------------------------- calendar */

export function AttendanceCalendar({
  days,
}: {
  days: { date: string; status: string; periods: number; statuses: string[] }[];
}) {
  if (!days.length) return <Empty>No classes recorded yet.</Empty>;

  // Group by month so the grid reads like a wall calendar rather than one long strip.
  const byMonth = new Map<string, typeof days>();
  for (const d of days) {
    const key = d.date.slice(0, 7);
    if (!byMonth.has(key)) byMonth.set(key, []);
    byMonth.get(key)!.push(d);
  }

  return (
    <div className="grid gap-4">
      {[...byMonth.entries()].map(([month, entries]) => {
        const first = new Date(`${month}-01T00:00:00Z`);
        const label = first.toLocaleDateString("en-GB", {
          month: "long",
          year: "numeric",
          timeZone: "UTC",
        });
        const daysInMonth = new Date(
          first.getUTCFullYear(),
          first.getUTCMonth() + 1,
          0,
        ).getUTCDate();
        const lead = (first.getUTCDay() + 6) % 7; // Monday-first
        const lookup = new Map(entries.map((e) => [e.date, e]));

        return (
          <div key={month}>
            <h3 className="label mb-1.5 block">{label}</h3>
            <div className="grid grid-cols-7 gap-1">
              {["M", "T", "W", "T", "F", "S", "S"].map((d, i) => (
                <div key={i} className="text-center font-mono text-[10px] text-ash">
                  {d}
                </div>
              ))}
              {Array.from({ length: lead }).map((_, i) => (
                <div key={`lead-${i}`} />
              ))}
              {Array.from({ length: daysInMonth }).map((_, i) => {
                const dayNum = i + 1;
                const iso = `${month}-${String(dayNum).padStart(2, "0")}`;
                const entry = lookup.get(iso);
                // Status is carried by the LETTER, with colour as reinforcement. A tinted day
                // number alone would be unreadable in greyscale, in forced-colors mode, and
                // for the ~8% of men with a red-green deficiency — on the one screen a
                // student opens to find out whether they are in trouble.
                const letter = entry ? STATUS_LETTER[entry.status] ?? "?" : null;
                return (
                  <div
                    key={iso}
                    title={entry ? `${iso}: ${entry.statuses.join(", ")}` : `${iso}: no class`}
                    aria-label={
                      entry
                        ? `${iso}: ${entry.status}, ${entry.periods} period(s)`
                        : undefined
                    }
                    className="flex aspect-square flex-col items-center justify-center rounded-[var(--radius-sm)] border leading-none"
                    style={{
                      borderColor: entry ? STATUS_COLOR[entry.status] : "var(--rule)",
                      color: entry ? STATUS_COLOR[entry.status] : "var(--ash)",
                      background: entry
                        ? `color-mix(in srgb, ${STATUS_COLOR[entry.status]} 12%, transparent)`
                        : "transparent",
                    }}
                  >
                    <span className="font-mono text-[10px] tnum opacity-70">{dayNum}</span>
                    {letter ? (
                      <span className="font-mono text-[11px] font-semibold">{letter}</span>
                    ) : null}
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}

      <div className="flex flex-wrap gap-3 text-[12px] text-ash">
        {(["present", "late", "absent", "on_leave", "excused"] as const).map((s) => (
          <span key={s} className="inline-flex items-center gap-1.5">
            <Mark status={s} />
            {s.replace("_", " ")}
          </span>
        ))}
      </div>
    </div>
  );
}
