/**
 * The student's own attendance. Also what a parent sees for their linked student.
 *
 * Server-rendered: the scoping happens in the API and nothing another student owns is ever
 * sent to this browser.
 */
import { apiGet } from "@/lib/api";
import { Banner, Card, CardHeader, StatTile } from "@/components/ui";
import { LogoutButton, ThemeToggle } from "@/components/controls";
import {
  AttendanceCalendar,
  AttendanceRing,
  CanMiss,
  SubjectBars,
  type StudentSummary,
} from "@/components/student";

export const dynamic = "force-dynamic";

export default async function MyAttendance() {
  let summary: StudentSummary | null = null;
  let error: string | null = null;
  try {
    summary = (await apiGet("/api/me/summary")) as StudentSummary;
  } catch (e) {
    error = e instanceof Error ? e.message : "Could not load your attendance.";
  }

  const threshold = summary?.threshold_pct ?? 75;
  const overall = summary?.overall;
  const meets = overall?.current_pct == null || overall.current_pct >= threshold;

  return (
    <main className="relative z-[1] mx-auto max-w-[1100px] px-4 pb-16 pt-6 md:px-5">
      <header className="mb-5 flex flex-wrap items-end justify-between gap-4 border-b border-[color-mix(in_srgb,var(--ink)_20%,transparent)] pb-3">
        <div>
          <h1 className="display m-0 text-[26px]">My attendance</h1>
          <p className="mt-0.5 font-mono text-xs text-ash">
            {summary
              ? `${summary.student.display_name}${summary.student.roll_number ? ` · ${summary.student.roll_number}` : ""}`
              : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <LogoutButton />
        </div>
      </header>

      {error ? (
        <Banner bad>
          <strong className="label mb-0.5 block">Could not load</strong>
          {error}
        </Banner>
      ) : null}

      {summary && overall ? (
        <>
          {!meets ? (
            <Banner bad>
              <strong className="label mb-0.5 block">Below the minimum</strong>
              You are at {overall.current_pct}%, under the {threshold}% required. See the
              subject breakdown below for where the shortfall is.
            </Banner>
          ) : null}

          <div className="mb-4 grid gap-4 lg:grid-cols-[auto_minmax(0,1fr)]">
            <Card className="flex items-center justify-center">
              <AttendanceRing pct={overall.current_pct} threshold={threshold} />
            </Card>

            <div className="grid content-start gap-4">
              <Card>
                <CanMiss p={overall} threshold={threshold} />
              </Card>
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
                <StatTile label="Classes held" value={overall.counted} />
                <StatTile label="Attended" value={overall.present} tone="verdant" />
                <StatTile
                  label="Still scheduled"
                  value={overall.remaining}
                  sub="this term"
                />
              </div>
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
            <Card>
              <CardHeader title="By subject" meta={`${summary.subjects.length} subject(s)`} />
              <SubjectBars subjects={summary.subjects} threshold={threshold} />
            </Card>

            <Card>
              <CardHeader title="Calendar" meta={`${summary.calendar.length} day(s) with classes`} />
              <AttendanceCalendar days={summary.calendar} />
            </Card>
          </div>
        </>
      ) : null}
    </main>
  );
}
