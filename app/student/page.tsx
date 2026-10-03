/**
 * Student dashboard. Pending and rejected accounts see where they stand; approved students
 * see their attendance. Everything is fetched server-side, self-scoped by the API.
 */
import { apiGet, getMe } from "@/lib/api";
import { Banner, Card, CardHeader, StatTile } from "@/components/ui";
import { Page, PageHeader } from "@/components/shell";
import {
  AttendanceCalendar,
  AttendanceRing,
  CanMiss,
  SubjectBars,
  type StudentSummary,
} from "@/components/student";

export const dynamic = "force-dynamic";

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
            {me.rejection_reason
              ? `Reason given: ${me.rejection_reason}`
              : "No reason was recorded."}{" "}
            Contact your class teacher if you think this is a mistake.
          </Banner>
        )}
      </Page>
    );
  }

  let summary: StudentSummary | null = null;
  let error: string | null = null;
  try {
    summary = (await apiGet("/api/me/summary")) as StudentSummary;
  } catch (e) {
    error = e instanceof Error ? e.message : "Could not load your attendance.";
  }

  const threshold = summary?.threshold_pct ?? 75;
  const overall = summary?.overall;
  const meets = (overall?.current_pct ?? 0) >= threshold;

  return (
    <Page>
      <PageHeader
        title="My attendance"
        subtitle={`${me.display_name}${me.roll_number ? ` · ${me.roll_number}` : ""}`}
      />

      {error ? (
        <Banner bad>
          <strong className="label mb-0.5 block">Could not load</strong>
          {error}
        </Banner>
      ) : null}

      {summary && overall ? (
        <>
          {!meets && overall.counted > 0 ? (
            <Banner bad>
              <strong className="label mb-0.5 block">Below the minimum</strong>
              You are at {overall.current_pct}%, under the {threshold}% required.
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
                <StatTile label="Still scheduled" value={overall.remaining} sub="this term" />
              </div>
            </div>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
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
    </Page>
  );
}
