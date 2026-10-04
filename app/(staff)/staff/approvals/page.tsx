"use client";

/** Everything waiting for a teacher's decision, scoped server-side to their classes. */
import { Suspense, useCallback, useEffect, useState } from "react";

import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { api } from "@/lib/client";
import { Page, PageHeader } from "@/components/shell";
import { Card, Pill } from "@/components/ui";
import { Button } from "@/components/forms";
import { EmptyState, PageError, PageLoading } from "@/components/states";
import { useUi } from "@/components/toast";
import { FaceReview } from "@/components/face-review";
import { ApprovalManagement } from "@/components/approval-management";

type EditReq = {
  id: number; student_id: number; student: string; roll_number: string | null;
  changes: Record<string, unknown>; current: Record<string, unknown>; reason: string; created_at: string;
};
type Summary = {
  registrations: number; edit_requests: number; face_enrollments: number; reenroll_requests: number;
  staff: number; can_review_staff: boolean;
};
type StaffReq = {
  id: number; full_name: string; email: string; phone: string | null; email_verified: boolean;
  employee_id: string; designation: string | null; requested_role: "faculty" | "admin";
  department: string | null; created_at: string;
};

const TABS = [
  ["registrations", "Students"],
  ["edits", "Profile edits"],
  ["faces", "Face enrollments"],
  ["staff", "Staff"],
] as const;

const ROLE_NAME = { faculty: "Teacher", admin: "HOD" } as const;

export default function ApprovalsPage() {
  return (
    <Suspense fallback={<Page><PageHeader title="Approvals" /><PageLoading /></Page>}>
      <Approvals />
    </Suspense>
  );
}

function Approvals() {
  const tab = useSearchParams().get("tab") ?? "registrations";
  const [summary, setSummary] = useState<Summary | null>(null);
  const loadSummary = useCallback(() => {
    api.get<Summary>("/api/approvals/summary").then(setSummary).catch(() => {});
  }, []);
  useEffect(loadSummary, [loadSummary]);
  const count: Record<string, number | undefined> = {
    registrations: summary?.registrations,
    edits: summary?.edit_requests,
    faces: summary ? summary.face_enrollments + summary.reenroll_requests : undefined,
    staff: summary?.staff,
  };
  // Only HODs and admins decide staff requests; the server enforces it, the tab just hides.
  const tabs = TABS.filter(([key]) => key !== "staff" || summary?.can_review_staff);

  return (
    <Page wide>
      <PageHeader title="Approval management" subtitle="Students by status, profile corrections, face enrollments and staff requests" />
      <nav aria-label="Approval types" className="mb-4 flex flex-wrap gap-1">
        {tabs.map(([key, label]) => (
          <Link
            key={key}
            href={`/staff/approvals?tab=${key}`}
            aria-current={tab === key ? "page" : undefined}
            className="display rounded-[3px] border px-3 py-1.5 text-[11.5px] no-underline"
            style={tab === key ? { background: "var(--ink)", borderColor: "var(--ink)", color: "var(--card)" } : { borderColor: "var(--rule)", color: "var(--ink)" }}
          >
            {label}
            {count[key] ? ` (${count[key]})` : ""}
          </Link>
        ))}
      </nav>
      {tab === "edits" ? <EditRequests onChange={loadSummary} />
        : tab === "faces" ? <FaceReview onChange={loadSummary} />
        : tab === "staff" ? <StaffRequests onChange={loadSummary} />
        : <ApprovalManagement onChange={loadSummary} />}
    </Page>
  );
}

function StaffRequests({ onChange }: { onChange: () => void }) {
  const { toast, confirm, askReason } = useUi();
  const [rows, setRows] = useState<StaffReq[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setRows(await api.get<StaffReq[]>("/api/staff-registrations"));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load.");
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  async function decide(r: StaffReq, approve: boolean) {
    try {
      if (approve) {
        const ok = await confirm({
          title: `Approve ${r.full_name} as ${ROLE_NAME[r.requested_role]}?`,
          body: `${r.department ?? ""} · employee ID ${r.employee_id}. Check this against the staff list before approving: `
            + "they will be able to see and mark attendance for their classes."
            + (r.email_verified ? "" : " Their email is not verified yet; approving confirms it."),
          confirmLabel: "Approve",
        });
        if (!ok) return;
        await api.post(`/api/staff-registrations/${r.id}/decide`, { approve: true });
        toast(`${r.full_name} approved.`);
      } else {
        const reason = await askReason({
          title: `Reject ${r.full_name}?`, confirmLabel: "Reject", danger: true,
          reason: { label: "Reason sent to them", minLength: 3 },
        });
        if (!reason) return;
        await api.post(`/api/staff-registrations/${r.id}/decide`, { approve: false, reason });
        toast(`${r.full_name} rejected.`);
      }
      load();
      onChange();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Action failed.", "bad");
    }
  }

  if (error) return <PageError message={error} retry={load} />;
  if (!rows) return <PageLoading />;
  if (!rows.length) {
    return <EmptyState title="No staff requests waiting">Teachers who register at the authority register page appear here.</EmptyState>;
  }
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {rows.map((r) => (
        <Card key={r.id}>
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <strong className="text-[15px]">{r.full_name}</strong>
            <Pill tone={r.requested_role === "admin" ? "warn" : "neutral"}>asks for {ROLE_NAME[r.requested_role]}</Pill>
          </div>
          <dl className="m-0 mt-2 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-[13px]">
            <dt className="label pt-[2px] text-[11px]">Branch</dt><dd className="m-0">{r.department}</dd>
            <dt className="label pt-[2px] text-[11px]">Employee ID</dt><dd className="m-0 font-mono">{r.employee_id}</dd>
            {r.designation ? <><dt className="label pt-[2px] text-[11px]">Designation</dt><dd className="m-0">{r.designation}</dd></> : null}
            <dt className="label pt-[2px] text-[11px]">Email</dt><dd className="m-0 break-all">{r.email}</dd>
            {r.phone ? <><dt className="label pt-[2px] text-[11px]">Mobile</dt><dd className="m-0 font-mono">{r.phone}</dd></> : null}
          </dl>
          {!r.email_verified ? <div className="mt-2"><Pill tone="warn">email not verified</Pill></div> : null}
          <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="primary" onClick={() => decide(r, true)}>Approve</Button>
            <Button onClick={() => decide(r, false)}>Reject</Button>
          </div>
        </Card>
      ))}
    </div>
  );
}

const FIELD_LABEL: Record<string, string> = {
  full_name: "Name", roll_number: "Roll number", enrollment_no: "Enrollment no.", department_id: "Branch",
  batch_id: "Batch", year: "Year", section_id: "Section",
};

function EditRequests({ onChange }: { onChange: () => void }) {
  const { toast, askReason } = useUi();
  const [rows, setRows] = useState<EditReq[] | null>(null);
  const [labels, setLabels] = useState<Record<string, Record<string, string>>>({});
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setRows(await api.get<EditReq[]>("/api/edit-requests"));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load.");
    }
  }, []);
  useEffect(() => {
    load();
    Promise.all([
      api.get<{ id: number; code: string }[]>("/api/departments"),
      api.get<{ id: number; label: string }[]>("/api/batches"),
      api.get<{ id: number; label: string }[]>("/api/sections"),
    ]).then(([d, b, s]) =>
      setLabels({
        department_id: Object.fromEntries(d.map((x) => [x.id, x.code])),
        batch_id: Object.fromEntries(b.map((x) => [x.id, x.label])),
        section_id: Object.fromEntries(s.map((x) => [x.id, x.label])),
      }),
    ).catch(() => {});
  }, [load]);

  const show = (k: string, v: unknown) => (v == null ? "—" : labels[k]?.[String(v)] ?? String(v));

  async function decide(r: EditReq, approve: boolean) {
    try {
      if (approve) {
        await api.post(`/api/edit-requests/${r.id}/approve`, {});
        toast("Change applied.");
      } else {
        const reason = await askReason({ title: "Reject this change?", danger: true, confirmLabel: "Reject", reason: { label: "Reason shown to the student", minLength: 3 } });
        if (!reason) return;
        await api.post(`/api/edit-requests/${r.id}/reject`, { reason });
        toast("Request rejected.");
      }
      load();
      onChange();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Action failed.", "bad");
    }
  }

  if (error) return <PageError message={error} retry={load} />;
  if (!rows) return <PageLoading />;
  if (!rows.length) return <EmptyState title="No edit requests waiting" />;
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {rows.map((r) => (
        <Card key={r.id}>
          <Link href={`/staff/students/${r.student_id}`} className="font-semibold text-ink">{r.student}</Link>
          <span className="ml-2 font-mono text-[12px] text-ash">{r.roll_number}</span>
          <table className="mt-2 w-full border-collapse text-[13.5px]">
            <thead>
              <tr>
                <th className="label border-b border-rule pb-1 text-left">Field</th>
                <th className="label border-b border-rule pb-1 text-left">Now</th>
                <th className="label border-b border-rule pb-1 text-left">Requested</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(r.changes).map(([k, v]) => (
                <tr key={k}>
                  <td className="py-1 pr-2">{FIELD_LABEL[k] ?? k}</td>
                  <td className="py-1 pr-2 text-ash line-through">{show(k, r.current[k])}</td>
                  <td className="py-1 font-semibold">{show(k, v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="my-2 text-[13.5px] text-ash">“{r.reason}”</p>
          <div className="flex gap-2">
            <Button variant="primary" onClick={() => decide(r, true)}>Approve</Button>
            <Button onClick={() => decide(r, false)}>Reject</Button>
          </div>
        </Card>
      ))}
    </div>
  );
}
