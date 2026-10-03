/**
 * Student dashboard. Pending and rejected accounts see where they stand; approved students
 * see today's lectures with live status, their percentage, what they need to stay above the
 * minimum, and a calendar. Everything is fetched server-side, self-scoped by the API.
 */
import Link from "next/link";

import { apiGetAll, getMe } from "@/lib/api";
import { Banner, Card, CardHeader, Mark, Pill, StatTile } from "@/components/ui";
import { Page, PageHeader } from "@/components/shell";
import {
  AttendanceCalendar,
  AttendanceRing,
  CanMiss,
  SubjectBars,
  type StudentSummary,
} from "@/components/student";

export const dynamic = "force-dynamic";

type Today = {
  date: string;
  holiday: string | null;
  periods: {
    slot_id: number; session_id: number | null; subject_code: string | null; subject_name: string | null;
    teacher: string | null; room: string; start_time: string; end_time: string;
    phase: "upcoming" | "ongoing" | "over"; session_state: string | null; status: string | null; method: string | null;
  }[];
};
type Active = { approved: boolean; sessions: { id: number; marked: boolean; window_open: boolean; subject_code: string | null }[] };

export default async function StudentHome() {
  const me = await getMe();
  if (!me) return null;

  if (me.student_status === "pending" || me.student_status === "rejected") {
    return (
      <Page>
        <PageHeader title={`Hello, ${me.display_name.split(" ")[0]}`} subtitle={me.email ?? ""} />
        {me.student_status === "pending" ? (
          <Banner>
            <strong className="label mb-0.5 block">Awaiting approval</strong>
            Your registration is with a teacher of your class for approval. You can sign in and
            look around, but attendance can only be marked once you are approved. You will get a
            notification and an email as soon as it is decided.
          </Banner>
        ) : (
          <Banner bad>
            <strong className="label mb-0.5 block">Registration rejected</strong>
            {me.rejection_reason ? `Reason given: ${me.rejection_reason}` : "No reason was recorded."}{" "}
            <Link href="/student/profile" className="text-ink underline">Correct your details and resubmit</Link>.
          </Banner>
        )}
      </Page>
    );
  }

  const raw = await apiGetAll({
    summary: "/api/me/summary",
    today: "/api/me/timetable/today",
    active: "/api/me/sessions/active",
  });
  const summary = raw.summary as StudentSummary | null;
  const today = raw.today as Today | null;
  const active = raw.active as Active | null;

  const threshold = summary?.threshold_pct ?? 75;
  const overall = summary?.overall;
  const below = overall && overall.current_pct !== null && overall.current_pct < threshold;
  const markable = active?.sessions.filter((s) => !s.marked && s.window_open) ?? [];

  return (
    <Page>
      <PageHeader
        title="My attendance"
        subtitle={`${me.display_name}${me.roll_number ? ` · ${me.roll_number}` : ""}`}
        actions={
          markable.length ? (
            <Link
              href="/student/mark"
              className="display inline-flex items-center gap-2 rounded-[3px] border px-4 py-2.5 text-[12px] no-underline"
              style={{ background: "var(--ink)", borderColor: "var(--ink)", color: "var(--card)" }}
            >
              <span className="h-2 w-2 animate-pulse rounded-full" style={{ background: "var(--verdant)" }} aria-hidden />
              Mark attendance — {markable[0].subject_code ?? "now"}
            </Link>
          ) : null
        }
      />

      {!summary ? (
        <Banner bad>
          <strong className="label mb-0.5 block">Could not load</strong>
          Your attendance summary is unavailable right now. Refresh in a moment.
        </Banner>
      ) : null}

      {below && overall ? (
        <Banner bad>
          <strong className="label mb-0.5 block">Below the minimum</strong>
          You are at {overall.current_pct}%, under the {threshold}% required.{" "}
          {overall.classes_needed && overall.classes_needed > 0 ? (
            <>
              You need to attend <strong>{overall.classes_needed} more class{overall.classes_needed === 1 ? "" : "es"}</strong>{" "}
              in a row to reach {threshold}%.
            </>
          ) : null}
        </Banner>
      ) : null}

      <div className="mb-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Card ruled>
          <CardHeader title="Today" meta={today?.date} />
          {today?.holiday ? (
            <p className="m-0 text-[14px]">Holiday — {today.holiday}. No lectures today.</p>
          ) : today && today.periods.length ? (
            <ul className="m-0 list-none p-0">
              {today.periods.map((p) => (
                <li key={p.slot_id} className="flex items-center justify-between gap-2 border-b border-dashed border-rule py-2 last:border-0">
                  <div className="min-w-0">
                    <span className="font-mono text-[13px] tnum text-ash">{p.start_time}</span>{" "}
                    <strong className="text-[14px]">{p.subject_code}</strong>{" "}
                    <span className="text-[13px] text-ash">{p.room}{p.teacher ? ` · ${p.teacher}` : ""}</span>
                  </div>
                  {p.status ? (
                    <span className="inline-flex items-center gap-1.5">
                      <Mark status={p.status} />
                      <span className="text-[12px] text-ash">{p.status.replace("_", " ")}</span>
                    </span>
                  ) : p.session_state === "active" ? (
                    <Pill tone="ok">live now</Pill>
                  ) : p.phase === "upcoming" ? (
                    <Pill tone="neutral">upcoming</Pill>
                  ) : p.phase === "ongoing" ? (
                    <Pill tone="warn">not started</Pill>
                  ) : (
                    <Pill tone="neutral">over</Pill>
                  )}
                </li>
              ))}
            </ul>
          ) : (
            <p className="m-0 text-[13.5px] text-ash">No lectures scheduled today.</p>
          )}
        </Card>

        {overall ? (
          <Card className="flex flex-wrap items-center justify-center gap-6">
            <AttendanceRing pct={overall.current_pct} threshold={threshold} />
            <div className="min-w-[200px] flex-1">
              <CanMiss p={overall} threshold={threshold} />
            </div>
          </Card>
        ) : null}
      </div>

      {summary && overall ? (
        <>
          <div className="mb-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatTile label="Classes held" value={overall.counted} />
            <StatTile label="Attended" value={overall.present} tone="verdant" />
            <StatTile label="Still scheduled" value={overall.remaining} sub="this term" />
            <StatTile
              label="To reach minimum"
              value={overall.current_pct === null ? "—" : overall.classes_needed ? `+${overall.classes_needed}` : "On track"}
              tone={overall.current_pct === null ? "ink" : overall.classes_needed ? "oxide" : "verdant"}
              sub={overall.current_pct === null ? "after your first class" : overall.classes_needed ? "classes in a row" : `at or above ${threshold}%`}
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader title="By subject" meta={`${summary.subjects.length} subject(s)`} />
              <SubjectBars subjects={summary.subjects} threshold={threshold} />
            </Card>
            <Card>
              <CardHeader title="Calendar" meta={<Link href="/student/history" className="text-ink">Full history</Link>} />
              <AttendanceCalendar days={summary.calendar} />
            </Card>
          </div>
        </>
      ) : null}
    </Page>
  );
}
