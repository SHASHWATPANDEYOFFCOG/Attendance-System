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

type Pending = {
  id: number; full_name: string; email: string | null; roll_number: string | null; section: string | null;
  department: string | null; batch: string | null; email_verified: boolean; photo_url: string | null; created_at: string;
};
type EditReq = {
  id: number; student_id: number; student: string; roll_number: string | null;
  changes: Record<string, unknown>; current: Record<string, unknown>; reason: string; created_at: string;
};
type Summary = { registrations: number; edit_requests: number; face_enrollments: number; reenroll_requests: number };

const TABS = [
  ["registrations", "Registrations"],
  ["edits", "Profile edits"],
  ["faces", "Face enrollments"],
] as const;

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
  };

  return (
    <Page wide>
      <PageHeader title="Approvals" subtitle="Registrations, profile corrections and face enrollments waiting for you" />
      <nav aria-label="Approval types" className="mb-4 flex flex-wrap gap-1">
        {TABS.map(([key, label]) => (
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
        : <Registrations onChange={loadSummary} />}
    </Page>
  );
}

function Registrations({ onChange }: { onChange: () => void }) {
  const { toast, confirm, askReason } = useUi();
  const [rows, setRows] = useState<Pending[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      const r = await api.get<{ rows: Pending[] }>("/api/students?status=pending&page_size=200");
      setRows(r.rows);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load.");
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  async function decide(s: Pending, approve: boolean) {
    try {
      if (approve) {
        if (!(await confirm({ title: `Approve ${s.full_name}?`, confirmLabel: "Approve" }))) return;
        await api.post(`/api/students/${s.id}/approve`);
        toast(`${s.full_name} approved.`);
      } else {
        const reason = await askReason({
          title: `Reject ${s.full_name}?`, confirmLabel: "Reject", danger: true,
          reason: { label: "Reason shown to the student", minLength: 3 },
        });
        if (!reason) return;
        await api.post(`/api/students/${s.id}/reject`, { reason });
        toast(`${s.full_name} rejected.`);
      }
      load();
      onChange();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Action failed.", "bad");
    }
  }

  if (error) return <PageError message={error} retry={load} />;
  if (!rows) return <PageLoading />;
  if (!rows.length) return <EmptyState title="No registrations waiting">New sign-ups for your classes appear here once they verify their email.</EmptyState>;
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {rows.map((s) => (
        <Card key={s.id}>
          <div className="flex gap-3">
            <div className="h-[72px] w-[72px] shrink-0 overflow-hidden rounded-[3px] border border-rule bg-paper">
              {s.photo_url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img src={`/api/backend${s.photo_url}`} alt="" className="h-full w-full object-cover" />
              ) : null}
            </div>
            <div className="min-w-0 flex-1">
              <Link href={`/staff/students/${s.id}`} className="font-semibold text-ink">{s.full_name}</Link>
              <div className="font-mono text-[12px] text-ash">{s.roll_number} · {s.section}</div>
              <div className="truncate text-[12.5px] text-ash">{s.email}</div>
              {!s.email_verified ? <Pill tone="warn">email not verified</Pill> : null}
            </div>
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button variant="primary" onClick={() => decide(s, true)} disabled={!s.email_verified}>Approve</Button>
            <Button onClick={() => decide(s, false)}>Reject</Button>
            <Link href={`/staff/students/${s.id}`} className="display self-center px-2 text-[11.5px] text-ink">Full details</Link>
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
