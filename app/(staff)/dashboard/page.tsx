/**
 * Faculty / HOD dashboard — the Phase 3 sample screen.
 *
 * A Server Component: every fetch happens on the server with the httpOnly token attached, so
 * no data the signed-in role is not entitled to ever reaches the browser. There is no
 * client-side filtering to bypass.
 */
import Link from "next/link";
import { redirect } from "next/navigation";

import { apiGet, apiGetAll } from "@/lib/api";
import {
  DashboardSchema,
  DefaultersSchema,
  SummarySchema,
  TimetableTodaySchema,
  TrendSchema,
  WeekdaySchema,
  safe,
} from "@/lib/types";
import { TrendChart, WeekdayHeatmap } from "@/components/charts";
import { Banner, Card, CardHeader, Empty, Pill, StatTile } from "@/components/ui";

export const dynamic = "force-dynamic";

type Counts = { roster: number; present: number; late: number; absent: number; on_leave: number; unmarked: number };
type LivePayload = {
  periods: { slot_id: number | null; subject_code: string | null; subject_name: string | null; start_time: string;
    section_label: string | null; holiday: string | null; session: { id: number; state: string; counts: Counts } | null }[];
};
type ClassesPayload = { days: number; threshold_pct: number; classes: { section_id: number | null; label: string; pct: number | null; lectures: number }[] };

export default async function DashboardPage() {
  // Students and parents get a self-scoped payload from /api/dashboard, so this staff screen
  // would render empty for them. Send them to their own view instead of showing a wall of
  // blanks and 403s. Handles direct navigation as well as the post-login redirect.
  const who = (await apiGet("/api/dashboard").catch(() => null)) as { scope?: string } | null;
  if (who?.scope === "self") redirect("/my-attendance");

  const raw = await apiGetAll({
    me: "/api/dashboard",
    summary: "/api/analytics/summary",
    trend: "/api/analytics/trend?days=30",
    weekday: "/api/analytics/weekday?days=90",
    defaulters: "/api/reports/defaulters?limit=12",
    today: "/api/timetable/today",
    live: "/api/sessions/live",
    classes: "/api/analytics/classes?days=30",
    counts: "/api/notifications/counts",
    approvals: "/api/approvals/summary",
  });
  const live = raw.live as LivePayload | null;
  const classes = raw.classes as ClassesPayload | null;
  const counts = (raw.counts ?? {}) as Record<string, number>;
  const approvals = raw.approvals as { total: number } | null;
  const attention: [string, number, string][] = [
    ["Approvals", approvals?.total ?? 0, "/staff/approvals"],
    ["Leave requests", counts.leaves ?? 0, "/staff/leaves"],
    ["Open issues", counts.issues ?? 0, "/staff/issues"],
    ["Camera reviews", counts.review ?? 0, "/staff/review"],
  ];

  const me = safe(DashboardSchema, raw.me);
  const summary = safe(SummarySchema, raw.summary);
  const trend = safe(TrendSchema, raw.trend);
  const weekday = safe(WeekdaySchema, raw.weekday);
  const defaulters = safe(DefaultersSchema, raw.defaulters);
  const today = safe(TimetableTodaySchema, raw.today);

  const warnings = me?.system?.warnings ?? [];
  const unmarked = today?.periods.filter((p) => !p.marked).length ?? 0;

  return (
    <main className="relative z-[1] mx-auto max-w-[1240px] px-4 pb-16 pt-6 md:px-5">
      <header className="mb-5 flex flex-wrap items-end justify-between gap-4 border-b-2 border-ink pb-3">
        <div>
          <h1 className="display m-0 text-[26px]">Attendance Register</h1>
          <p className="mt-0.5 font-mono text-xs text-ash">
            {me ? `${me.user.display_name} · ${me.role.replace("_", " ")}` : "loading"}
            {me ? ` · ${me.timezone} · stored UTC` : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/staff/sessions" className="display rounded-[3px] border px-3.5 py-2 text-[12px] no-underline"
                style={{ background: "var(--ink)", borderColor: "var(--ink)", color: "var(--card)" }}>Live sessions</Link>
          <Link href="/staff/reports" className="display rounded-[3px] border border-ink px-3.5 py-2 text-[12px] text-ink no-underline hover:bg-tint">Reports</Link>
        </div>
      </header>

      <nav aria-label="Needs attention" className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {attention.map(([label, n, href]) => (
          <Link key={href} href={href} className="no-underline">
            <StatTile label={label} value={n} tone={n ? "amber" : "verdant"} sub={n ? "waiting for you" : "all clear"} />
          </Link>
        ))}
      </nav>

      {live && live.periods.length ? (
        <Card className="mb-4">
          <CardHeader title="Today's sessions" meta={<Link href="/staff/sessions" className="text-ink">Open live view</Link>} />
          <div className="overflow-x-auto">
            <table className="w-full min-w-[620px] border-collapse text-[13.5px]">
              <thead>
                <tr>
                  {["Time", "Subject", "Class", "State", "Present", "Late", "Absent", "Leave", "Unmarked"].map((h) => (
                    <th key={h} className="label border-b-2 border-ink px-2 pb-1.5 text-left">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {live.periods.map((p, i) => {
                  const c = p.session?.counts;
                  return (
                    <tr key={p.session?.id ?? `slot-${p.slot_id}-${i}`} className="hover:bg-tint">
                      <td className="border-b border-rule px-2 py-1.5 font-mono tnum">{p.start_time}</td>
                      <td className="border-b border-rule px-2">
                        {p.session ? <Link href={`/staff/sessions/${p.session.id}`} className="text-ink">{p.subject_code ?? p.subject_name}</Link> : (p.subject_code ?? p.subject_name)}
                      </td>
                      <td className="border-b border-rule px-2">{p.section_label}</td>
                      <td className="border-b border-rule px-2">
                        {p.holiday ? <Pill tone="neutral">holiday</Pill> : p.session ? <Pill tone={p.session.state === "active" ? "ok" : p.session.state === "closed" ? "neutral" : "warn"}>{p.session.state}</Pill> : <Pill tone="neutral">not started</Pill>}
                      </td>
                      {(["present", "late", "absent", "on_leave", "unmarked"] as const).map((k) => (
                        <td key={k} className="border-b border-rule px-2 font-mono tnum">{c ? c[k] : "—"}</td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Card>
      ) : null}

      {classes && classes.classes.length ? (
        <Card className="mb-4">
          <CardHeader title="Class-wise attendance" meta={`last ${classes.days} days · minimum ${classes.threshold_pct}%`} />
          <ul className="m-0 grid list-none gap-2 p-0 md:grid-cols-2">
            {classes.classes.map((c) => {
              const pct = c.pct ?? 0;
              const below = pct < classes.threshold_pct;
              return (
                <li key={c.section_id ?? c.label}>
                  <div className="flex items-baseline justify-between text-[13.5px]">
                    <span>{c.label}</span>
                    <span className="font-mono tnum" style={{ color: below ? "var(--oxide)" : "var(--ink)" }}>{pct}% <span className="text-ash">({c.lectures})</span></span>
                  </div>
                  <div className="relative mt-1 h-2 rounded-[2px]" style={{ background: "var(--tint-hard)" }} role="img" aria-label={`${c.label}: ${pct} percent`}>
                    <div className="h-full rounded-[2px]" style={{ width: `${Math.min(100, pct)}%`, background: below ? "var(--status-absent)" : "var(--status-present)" }} />
                    <div className="absolute top-0 h-full" style={{ left: `${classes.threshold_pct}%`, width: 2, background: "var(--ink)" }} />
                  </div>
                </li>
              );
            })}
          </ul>
        </Card>
      ) : null}

      {warnings.map((w) => (
        <Banner key={w} bad={/ANTI-SPOOF/i.test(w)}>
          <strong className="label mb-0.5 block text-[12px]">
            {/ANTI-SPOOF/i.test(w) ? "Anti-spoofing" : /CLOCK/i.test(w) ? "Host clock" : "Thresholds"}
          </strong>
          {w}
        </Banner>
      ))}

      {/* ---------------------------------------------------------- stat row */}
      <div className="mb-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatTile
          label="Average attendance"
          value={summary ? `${summary.average_pct}%` : "—"}
          tone={summary && summary.average_pct < summary.threshold_pct ? "oxide" : "ink"}
          sub={summary ? `minimum ${summary.threshold_pct}%` : undefined}
        />
        <StatTile
          label="Defaulters"
          value={summary?.defaulters ?? "—"}
          tone="oxide"
          sub={summary ? `below ${summary.threshold_pct}%` : undefined}
        />
        <StatTile label="At risk" value={summary?.at_risk ?? "—"} tone="amber" sub="within 1 point" />
        <StatTile
          label="Unmarked today"
          value={unmarked}
          tone={unmarked > 0 ? "amber" : "verdant"}
          sub={today ? `${today.periods.length} period(s) scheduled` : undefined}
        />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]">
        <div className="grid gap-4">
          <Card>
            <CardHeader
              title="Attendance trend"
              meta={trend ? `${trend.dates.length} days · ${trend.series.length} dept` : undefined}
            />
            {trend ? <TrendChart trend={trend} /> : <Empty>Trend unavailable.</Empty>}
          </Card>

          <Card>
            <CardHeader title="Absence by weekday" meta={weekday ? `${weekday.days} days` : undefined} />
            {weekday ? <WeekdayHeatmap weekday={weekday} /> : <Empty>No weekday data.</Empty>}
          </Card>
        </div>

        <div className="grid gap-4">
          {/* --------------------------------------------------- today */}
          <Card ruled>
            <CardHeader title="Today" meta={today?.date} />
            {today && today.periods.length ? (
              <ul className="m-0 list-none p-0">
                {today.periods.map((p) => (
                  <li
                    key={p.slot_id}
                    className="flex items-center justify-between gap-2 border-b border-dashed border-rule py-2 last:border-0"
                  >
                    <div className="min-w-0">
                      <span className="font-mono text-[13px] tnum text-ash">{p.start_time}</span>{" "}
                      <strong className="text-[14px]">{p.subject_code}</strong>{" "}
                      <span className="text-ash text-[13px]">
                        {p.section_label} · {p.room}
                      </span>
                    </div>
                    {p.marked ? (
                      <Pill tone="ok">marked</Pill>
                    ) : (
                      <Pill tone="warn">not marked</Pill>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <Empty>No periods scheduled today.</Empty>
            )}
          </Card>

          {/* ---------------------------------------------- defaulters */}
          <Card>
            <CardHeader
              title="Defaulters"
              meta={defaulters ? `${defaulters.count} below ${defaulters.threshold_pct}%` : undefined}
            />
            {defaulters && defaulters.defaulters.length ? (
              <div className="overflow-x-auto">
                <table className="w-full border-collapse text-[13.5px]">
                  <thead>
                    <tr>
                      <th className="label border-b-2 border-ink px-2 pb-1.5 text-left">Student</th>
                      <th className="label border-b-2 border-ink px-2 pb-1.5 text-right">%</th>
                      <th className="label border-b-2 border-ink px-2 pb-1.5 text-right">Needs</th>
                    </tr>
                  </thead>
                  <tbody>
                    {defaulters.defaulters.map((d) => (
                      <tr key={d.user_id} className="hover:bg-tint">
                        <td className="h-[30px] border-b border-rule px-2">
                          <span className="block truncate">{d.display_name}</span>
                          <span className="font-mono text-[11px] text-ash">{d.roll_number}</span>
                        </td>
                        <td className="border-b border-rule px-2 text-right font-mono tnum text-oxide">
                          {d.attendance_pct}%
                        </td>
                        <td
                          className="border-b border-rule px-2 text-right font-mono tnum text-ash"
                          title="Consecutive classes needed to reach the minimum"
                        >
                          {d.shortfall_classes < 0 ? "—" : `+${d.shortfall_classes}`}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <Empty>Nobody is below the minimum.</Empty>
            )}
          </Card>
        </div>
      </div>
    </main>
  );
}
