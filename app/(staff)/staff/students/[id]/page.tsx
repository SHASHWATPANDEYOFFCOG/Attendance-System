/**
 * One student, as their teacher sees them. Server-rendered; the API refuses (403) when the
 * student is not in one of this teacher's classes, and that refusal is shown as-is.
 */
import Link from "next/link";

import { apiGet, getMe, isAdminRole } from "@/lib/api";
import { Page, PageHeader } from "@/components/shell";
import { Banner, Card, CardHeader, Pill, StatTile } from "@/components/ui";
import { AttendanceCalendar, SubjectBars, type StudentSummary } from "@/components/student";
import { StudentActions } from "@/components/student-actions";

type Detail = {
  id: number;
  full_name: string;
  email: string | null;
  email_verified: boolean;
  phone: string | null;
  has_biometrics: boolean;
  consent_given: boolean;
  student: {
    status: string; rejection_reason: string | null; roll_number: string | null; enrollment_no: string | null;
    department: string | null; batch: string | null; year: number | null; section: string | null;
    dob: string | null; gender: string | null; guardian_name: string | null; guardian_phone: string | null;
    guardian_email: string | null; address: string | null; photo_url: string | null;
  };
  attendance: StudentSummary;
  leaves: { id: number; type: string; from_date: string; to_date: string; reason: string; status: string; comment: string | null }[];
  edit_requests: { id: number; changes: Record<string, unknown>; reason: string; status: string; remark: string | null }[];
};

export const dynamic = "force-dynamic";

export default async function StudentDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const me = await getMe();
  let d: Detail | null = null;
  let error: string | null = null;
  try {
    d = await apiGet<Detail>(`/api/students/${Number(id)}`);
  } catch (e) {
    error = e instanceof Error ? e.message : "Could not load this student.";
  }

  if (!d) {
    return (
      <Page>
        <PageHeader title="Student" />
        <Banner bad>{error}</Banner>
        <Link href="/staff/students" className="text-ink underline">Back to students</Link>
      </Page>
    );
  }
  const s = d.student;
  const a = d.attendance;
  const overall = a.overall;

  const facts: [string, string | null | undefined][] = [
    ["Roll number", s.roll_number], ["Enrollment no.", s.enrollment_no], ["Branch", s.department],
    ["Batch", s.batch], ["Year", s.year ? String(s.year) : null], ["Class", s.section],
    ["Email", d.email], ["Mobile", d.phone], ["Date of birth", s.dob], ["Gender", s.gender?.replace(/_/g, " ")],
    ["Guardian", s.guardian_name], ["Guardian phone", s.guardian_phone], ["Guardian email", s.guardian_email],
    ["Address", s.address],
  ];

  return (
    <Page wide>
      <PageHeader
        title={d.full_name}
        subtitle={`${s.roll_number ?? ""} · ${s.section ?? "no class"}`}
        actions={
          <StudentActions
            studentId={d.id}
            name={d.full_name}
            status={s.status}
            emailVerified={d.email_verified || !d.email}
            canRemove={isAdminRole(me?.role)}
          />
        }
      />

      {s.status === "pending" ? (
        <Banner>
          <strong className="label mb-0.5 block">Awaiting approval</strong>
          {d.email_verified ? "Email verified. Check the details against college records, then approve or reject." : "The student has not verified their email yet."}
        </Banner>
      ) : s.status === "rejected" ? (
        <Banner bad>
          <strong className="label mb-0.5 block">Rejected</strong>
          {s.rejection_reason}
        </Banner>
      ) : null}

      <div className="mb-4 grid gap-4 lg:grid-cols-[300px_minmax(0,1fr)]">
        <Card>
          <div className="mb-3 flex items-center gap-3">
            <div className="h-[88px] w-[88px] shrink-0 overflow-hidden rounded-[3px] border border-rule bg-paper">
              {s.photo_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={`/api/backend${s.photo_url}`} alt={`${d.full_name}'s photo`} className="h-full w-full object-cover" />
              ) : null}
            </div>
            <div className="grid gap-1">
              <Pill tone={s.status === "approved" ? "ok" : s.status === "rejected" ? "bad" : "warn"}>{s.status}</Pill>
              <Pill tone={d.has_biometrics ? "ok" : "neutral"}>{d.has_biometrics ? "face enrolled" : "no face data"}</Pill>
              {!d.consent_given ? <span className="text-[11.5px] text-ash">no biometric consent</span> : null}
            </div>
          </div>
          <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-[13.5px]">
            {facts.map(([k, v]) => (
              <div key={k} className="contents">
                <dt className="label pt-[2px] text-[11px]">{k}</dt>
                <dd className="m-0 break-words">{v || <span className="text-ash">—</span>}</dd>
              </div>
            ))}
          </dl>
        </Card>

        <div className="grid content-start gap-4">
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <StatTile label="Attendance" value={`${overall.current_pct}%`} tone={overall.current_pct < a.threshold_pct ? "oxide" : "verdant"} sub={`minimum ${a.threshold_pct}%`} />
            <StatTile label="Classes held" value={overall.counted} />
            <StatTile label="Attended" value={overall.present} />
            <StatTile
              label={overall.current_pct < a.threshold_pct ? "Needs" : "Can miss"}
              value={overall.current_pct < a.threshold_pct ? `+${(overall as { classes_needed?: number }).classes_needed ?? 0}` : overall.can_miss}
              sub={overall.current_pct < a.threshold_pct ? "classes in a row" : "classes this term"}
              tone={overall.current_pct < a.threshold_pct ? "oxide" : "ink"}
            />
          </div>
          <Card>
            <CardHeader title="By subject" />
            <SubjectBars subjects={a.subjects} threshold={a.threshold_pct} />
          </Card>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Calendar" meta="last 120 days" />
          <AttendanceCalendar days={a.calendar} />
        </Card>
        <div className="grid content-start gap-4">
          <Card>
            <CardHeader title="Leave history" meta={`${d.leaves.length}`} />
            {d.leaves.length ? (
              <ul className="m-0 list-none p-0 text-[13.5px]">
                {d.leaves.map((l) => (
                  <li key={l.id} className="flex items-start justify-between gap-2 border-b border-dashed border-rule py-2 last:border-0">
                    <div>
                      <span className="font-mono tnum">{l.from_date}{l.to_date !== l.from_date ? ` → ${l.to_date}` : ""}</span>{" "}
                      <span className="text-ash">{l.type.replace(/_/g, " ")}</span>
                      <div>{l.reason}</div>
                    </div>
                    <Pill tone={l.status === "approved" ? "ok" : l.status === "rejected" ? "bad" : "warn"}>{l.status}</Pill>
                  </li>
                ))}
              </ul>
            ) : <p className="m-0 text-[13.5px] text-ash">No leave applications.</p>}
          </Card>
          <Card>
            <CardHeader title="Profile edit requests" meta={`${d.edit_requests.length}`} />
            {d.edit_requests.length ? (
              <ul className="m-0 list-none p-0 text-[13.5px]">
                {d.edit_requests.map((r) => (
                  <li key={r.id} className="flex items-start justify-between gap-2 border-b border-dashed border-rule py-2 last:border-0">
                    <div>
                      {Object.entries(r.changes).map(([k, v]) => <div key={k}><span className="font-mono">{k}</span> → <strong>{String(v)}</strong></div>)}
                      <div className="text-ash">“{r.reason}”</div>
                    </div>
                    <Pill tone={r.status === "approved" ? "ok" : r.status === "rejected" ? "bad" : "warn"}>{r.status}</Pill>
                  </li>
                ))}
              </ul>
            ) : <p className="m-0 text-[13.5px] text-ash">None.</p>}
            {d.edit_requests.some((r) => r.status === "pending") ? (
              <Link href="/staff/approvals?tab=edits" className="mt-2 inline-block text-[13.5px] text-ink underline">Review in Approvals</Link>
            ) : null}
          </Card>
        </div>
      </div>
    </Page>
  );
}
