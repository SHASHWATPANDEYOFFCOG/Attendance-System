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

const ROLE_NAME: Record<string, string> = { faculty: "Teacher", admin: "HOD", super_admin: "Administrator" };

function warningTitle(w: string): string {
  if (/ANTI-SPOOF/i.test(w)) return "Anti-spoofing";
  if (/CLOCK/i.test(w)) return "Server clock";
  if (/EMAIL/i.test(w)) return "Email";
  return "Face thresholds";
}

type Counts = { roster: number; present: number; late: number; absent: number; on_leave: number; unmarked: number };
type LivePayload = {
  periods: { slot_id: number | null; subject_code: string | null; subject_name: string | null; start_time: string;
    section_label: string | null; holiday: string | null; session: { id: number; state: string; counts: Counts } | null }[];
};
type Overview = {
  cameras: { total: number; online: number; offline: number; connecting: number; idle: number; disabled: number };
  tablets: { total: number; active: number };
  workspaces: number;
  students: { pending: number; approved: number; rejected: number; revoked: number };
  authorities?: { total: number; active: number };
  is_administrator: boolean;
};
type ClassesPayload = { days: number; threshold_pct: number; classes: { section_id: number | null; label: string; pct: number | null; lectures: number }[] };

export default async function DashboardPage() {
  // Students and parents get a self-scoped payload from /api/dashboard, so this staff screen
  // would render empty for them. Send them to their own view instead of showing a wall of
  // blanks and 403s. Handles direct navigation as well as the post-login redirect.
  const who = (await apiGet("/api/dashboard").catch(() => null)) as { scope?: string } | null;
  if (who?.scope === "self") redirect("/my-attendance");

  const raw = await apiGetAll({
    overview: "/api/admin/overview",
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
  const overview = raw.overview as Overview | null;
  const trend = safe(TrendSchema, raw.trend);
  const weekday = safe(WeekdaySchema, raw.weekday);
  const defaulters = safe(DefaultersSchema, raw.defaulters);
  const today = safe(TimetableTodaySchema, raw.today);

  const warnings = me?.system?.warnings ?? [];
  const isAdmin = me?.role === "admin" || me?.role === "super_admin";
  const unmarked = today?.periods.filter((p) => !p.marked).length ?? 0;

  return (
    <main className="animate-page-in relative z-[1] mx-auto max-w-[1280px] px-4 pb-16 pt-7 md:px-8">
      <header className="mb-5 flex flex-wrap items-end justify-between gap-4 border-b border-[color-mix(in_srgb,var(--ink)_20%,transparent)] pb-3">
        <div>
          <h1 className="headline m-0 text-[30px] md:text-[40px]">Authority <span className="text-gradient">dashboard</span></h1>
          <p className="mt-0.5 font-mono text-xs text-ash">
            {me ? `${me.user.display_name} · ${ROLE_NAME[me.role] ?? me.role} · ` : ""}
            {new Date().toLocaleDateString([], { weekday: "long", day: "numeric", month: "long", timeZone: me?.timezone })}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link href="/staff/sessions" className="display rounded-[var(--radius)] border px-3.5 py-2 text-[13px] no-underline"
                style={{ background: "var(--grad-primary)", borderColor: "transparent", color: "var(--on-accent)" }}>Live sessions</Link>
          <Link href="/staff/reports" className="display rounded-[var(--radius)] border border-ink px-3.5 py-2 text-[13px] text-ink no-underline hover:bg-tint">Reports</Link>
        </div>
      </header>

      {me?.role === "faculty" && classes && classes.classes.length === 0 ? (
        <Banner>
          <strong className="label mb-0.5 block">Welcome — no classes assigned to you yet</strong>
          Your HOD or the administrator assigns your subjects and classes (Academic setup → Teacher assignments and
          Timetable). Until then you can already verify new student registrations of your branch under{" "}
          <Link href="/staff/approvals" className="text-ink underline">Approvals</Link>; you are notified of each one.
        </Banner>
      ) : null}

      {overview ? (
        <section aria-label={overview.is_administrator ? "System overview" : "Your resources"} className="mb-4">
          <h2 className="label m-0 mb-2 text-[12px] text-ash">{overview.is_administrator ? "System overview" : "Your workspaces and students"}</h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
            {([
              ["Cameras", overview.cameras.total, `${overview.cameras.online} online · ${overview.cameras.offline} offline`, "/staff/cameras", overview.cameras.offline ? "oxide" : "ink"],
              ...(overview.authorities ? [["Authorities", overview.authorities.total, `${overview.authorities.active} active`, "/staff/admin/users", "ink"]] : []),
              ["Tablets", overview.tablets.total, `${overview.tablets.active} active`, "/staff/tablets", "ink"],
              ["Workspaces", overview.workspaces, "active", "/staff/workspaces", "ink"],
              ["Students", overview.students.approved, `${overview.students.pending} pending · ${overview.students.rejected} rejected${overview.students.revoked ? ` · ${overview.students.revoked} revoked` : ""}`, "/staff/approvals", overview.students.pending ? "amber" : "verdant"],
            ] as [string, number, string, string, "ink" | "oxide" | "amber" | "verdant"][]).map(([label, n, sub, href, tone]) => (
              <Link key={label} href={href} className="no-underline">
                <StatTile label={label} value={n} sub={sub} tone={tone} />
              </Link>
            ))}
          </div>
        </section>
      ) : null}

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
                  {["Time", "Subject", "Class", "State", "Present", "Late", "Absent", "Leave", "Unmarked", ""].map((h) => (
                    <th key={h} className="label border-b border-[color-mix(in_srgb,var(--ink)_20%,transparent)] px-2 pb-1.5 text-left">{h}</th>
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
                      <td className="border-b border-rule px-2 py-1 text-right">
                        {p.session && p.session.state !== "closed" ? (
                          <Link href={`/staff/sessions/${p.session.id}`}
                                className="display inline-block whitespace-nowrap rounded-[var(--radius)] border px-2.5 py-1.5 text-[12px] no-underline"
                                style={{ background: "var(--grad-primary)", borderColor: "transparent", color: "var(--on-accent)" }}>
                            {p.session.state === "active" ? "Take attendance" : "Open"}
                          </Link>
                        ) : p.session ? (
                          <Link href={`/staff/sessions/${p.session.id}`} className="text-[12px] text-ink">View</Link>
                        ) : null}
                      </td>
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
                  <div className="relative mt-1 h-2 rounded-[var(--radius-sm)]" style={{ background: "var(--tint-hard)" }} role="img" aria-label={`${c.label}: ${pct} percent`}>
                    <div className="h-full rounded-[var(--radius-sm)]" style={{ width: `${Math.min(100, pct)}%`, background: below ? "var(--status-absent)" : "var(--status-present)" }} />
                    <div className="absolute top-0 h-full" style={{ left: `${classes.threshold_pct}%`, width: 2, background: "var(--ink)" }} />
                  </div>
                </li>
              );
            })}
          </ul>
        </Card>
      ) : null}

      {/* Server housekeeping is for whoever runs the system, not for every teacher. */}
      {isAdmin && warnings.length ? (
        <details className="mb-4 rounded-[var(--radius-lg)] border border-rule glass shadow-card">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-4 py-3">
            <span className="flex items-center gap-2">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: warnings.some((w) => /ANTI-SPOOF|EMAIL FAILING/i.test(w)) ? "var(--oxide)" : "var(--amber)" }} aria-hidden />
              <span className="label text-[12px]">System health</span>
              <span className="text-[13px] text-ash">
                {warnings.length} item{warnings.length === 1 ? "" : "s"} need attention: {warnings.map(warningTitle).join(", ")}
              </span>
            </span>
            <span className="display text-[12px] text-ash">details</span>
          </summary>
          <div className="grid gap-2 border-t border-rule px-4 py-3">
            {warnings.map((w) => (
              <Banner key={w} bad={/ANTI-SPOOF|EMAIL FAILING/i.test(w)}>
                <strong className="label mb-0.5 block text-[12px]">{warningTitle(w)}</strong>
                {w}
              </Banner>
            ))}
          </div>
        </details>
      ) : null}

      {/* ---------------------------------------------------------- stat row */}
      <div className="mb-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatTile
          label="Average attendance"
          value={summary && summary.records_counted > 0 ? `${summary.average_pct}%` : "—"}
          tone={summary && summary.records_counted > 0 && summary.average_pct < summary.threshold_pct ? "oxide" : "ink"}
          sub={summary && summary.records_counted > 0 ? `minimum ${summary.threshold_pct}%` : "no lectures recorded yet"}
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
                      <th className="label border-b border-[color-mix(in_srgb,var(--ink)_20%,transparent)] px-2 pb-1.5 text-left">Student</th>
                      <th className="label border-b border-[color-mix(in_srgb,var(--ink)_20%,transparent)] px-2 pb-1.5 text-right">%</th>
                      <th className="label border-b border-[color-mix(in_srgb,var(--ink)_20%,transparent)] px-2 pb-1.5 text-right">Needs</th>
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
