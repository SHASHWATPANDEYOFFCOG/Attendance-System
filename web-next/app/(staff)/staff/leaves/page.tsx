"use client";

/** Leave management: filter, open the certificate, approve / reject with a remark, bulk approve. */
import { useCallback, useEffect, useState } from "react";

import Link from "next/link";

import { api } from "@/lib/client";
import { Page, PageHeader } from "@/components/shell";
import { Card, Pill } from "@/components/ui";
import { Button, Checkbox, SelectField, TextField } from "@/components/forms";
import { EmptyState, PageError, PageLoading } from "@/components/states";
import { AttachmentLink } from "@/components/thread";
import { useUi } from "@/components/toast";

type Leave = {
  id: number; type_label: string; from_date: string; to_date: string; reason: string;
  explanation: string | null; status: string; remark: string | null; created_at: string;
  lectures?: { id: number; date: string; subject: string }[];
  attachment: { url: string; name: string } | null;
  student: { id: number; name: string; roll_number: string | null; section: string | null };
};

export default function StaffLeavesPage() {
  const { toast, askReason, confirm } = useUi();
  const [f, setF] = useState({ status: "pending", type: "", q: "", date_from: "", date_to: "", page: 1 });
  const [data, setData] = useState<{ rows: Leave[]; meta: { total: number; pages: number } } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [picked, setPicked] = useState<number[]>([]);

  const load = useCallback(async () => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(f)) if (v) p.set(k, String(v));
    try {
      setData(await api.get(`/api/leaves?${p}`));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load leaves.");
    }
  }, [f]);
  useEffect(() => {
    const t = setTimeout(load, 200);
    return () => clearTimeout(t);
  }, [load]);
  useEffect(() => setPicked([]), [data]);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value, page: 1 }));

  async function approve(l: Leave) {
    const remark = await askReason({ title: `Approve ${l.student.name}'s leave?`, confirmLabel: "Approve",
      body: "Recorded absences in these dates become On leave.", reason: { label: "Remark (optional)", minLength: 0 } });
    if (remark === null) return;
    try {
      const r = await api.post<{ records_changed: number }>(`/api/leaves/${l.id}/approve`, { remark: remark || null });
      toast(`Approved${r.records_changed ? ` — ${r.records_changed} absence(s) now On leave` : ""}.`);
      load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not approve.", "bad");
    }
  }
  async function reject(l: Leave) {
    const remark = await askReason({ title: `Reject ${l.student.name}'s leave?`, confirmLabel: "Reject", danger: true,
      reason: { label: "Reason shown to the student", minLength: 3 } });
    if (!remark) return;
    try {
      await api.post(`/api/leaves/${l.id}/reject`, { remark });
      toast("Rejected.");
      load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not reject.", "bad");
    }
  }
  async function bulk() {
    if (!(await confirm({ title: `Approve ${picked.length} application(s)?`, confirmLabel: "Approve all" }))) return;
    try {
      const r = await api.post<{ approved: number; records_changed: number }>("/api/leaves/bulk-approve", { ids: picked });
      toast(`Approved ${r.approved}; ${r.records_changed} absence(s) now On leave.`);
      load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Bulk approval failed; nothing was changed.", "bad");
    }
  }

  const pending = data?.rows.filter((l) => l.status === "pending") ?? [];

  return (
    <Page wide>
      <PageHeader title="Leave applications" subtitle={data ? `${data.meta.total} matching` : ""}
                  actions={picked.length ? <Button variant="primary" onClick={bulk}>Approve selected ({picked.length})</Button> : null} />
      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          <SelectField label="Status" value={f.status} onChange={set("status")}>
            <option value="pending">Pending</option><option value="approved">Approved</option>
            <option value="rejected">Rejected</option><option value="cancelled">Cancelled</option><option value="">All</option>
          </SelectField>
          <SelectField label="Type" value={f.type} onChange={set("type")}>
            <option value="">All</option>
            {[["medical", "Medical"], ["personal", "Personal"], ["family_emergency", "Family emergency"], ["on_duty", "Duty / event"], ["other", "Other"]].map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </SelectField>
          <TextField label="From" type="date" value={f.date_from} onChange={set("date_from")} />
          <TextField label="To" type="date" value={f.date_to} onChange={set("date_to")} />
          <TextField label="Search" type="search" value={f.q} onChange={set("q")} placeholder="Student, roll no, reason" />
        </div>
      </Card>
      {error ? <PageError message={error} retry={load} /> : !data ? <PageLoading /> : !data.rows.length ? (
        <EmptyState title="No applications match" />
      ) : (
        <div className="grid gap-3">
          {pending.length > 1 ? (
            <Checkbox label="Select all pending on this page" checked={picked.length === pending.length}
                      onChange={(e) => setPicked(e.target.checked ? pending.map((l) => l.id) : [])} />
          ) : null}
          {data.rows.map((l) => (
            <Card key={l.id}>
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="flex min-w-0 gap-3">
                  {l.status === "pending" ? (
                    <input type="checkbox" aria-label={`Select ${l.student.name}`} className="mt-1 h-4 w-4 accent-[var(--ink)]"
                           checked={picked.includes(l.id)} onChange={(e) => setPicked((p) => e.target.checked ? [...p, l.id] : p.filter((x) => x !== l.id))} />
                  ) : null}
                  <div className="min-w-0">
                    <Link href={`/staff/students/${l.student.id}`} className="font-semibold text-ink">{l.student.name}</Link>
                    <span className="ml-2 font-mono text-[12px] text-ash">{l.student.roll_number} · {l.student.section}</span>
                    <div className="font-mono text-[13px] tnum">{l.from_date}{l.to_date !== l.from_date ? ` → ${l.to_date}` : ""} · {l.type_label}</div>
                    <div className="text-[14px]">{l.reason}</div>
                    {l.lectures?.length ? <div className="text-[12.5px] text-ash">Lectures: {l.lectures.map((x) => `${x.subject} (${x.date})`).join(", ")}</div> : null}
                    {l.explanation ? <p className="mb-0 mt-1 whitespace-pre-wrap text-[13.5px] text-ink/85">{l.explanation}</p> : null}
                    <AttachmentLink a={l.attachment} />
                    {l.remark ? <p className="mb-0 mt-1 text-[13px] text-ash">Remark: {l.remark}</p> : null}
                  </div>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <Pill tone={l.status === "approved" ? "ok" : l.status === "rejected" ? "bad" : l.status === "cancelled" ? "neutral" : "warn"}>{l.status}</Pill>
                  {l.status === "pending" ? (
                    <>
                      <Button variant="primary" onClick={() => approve(l)}>Approve</Button>
                      <Button onClick={() => reject(l)}>Reject</Button>
                    </>
                  ) : null}
                </div>
              </div>
            </Card>
          ))}
          {data.meta.pages > 1 ? (
            <nav className="flex items-center justify-between" aria-label="Pages">
              <Button disabled={f.page <= 1} onClick={() => setF((x) => ({ ...x, page: x.page - 1 }))}>Previous</Button>
              <span className="font-mono text-[12px] text-ash">page {f.page} of {data.meta.pages}</span>
              <Button disabled={f.page >= data.meta.pages} onClick={() => setF((x) => ({ ...x, page: x.page + 1 }))}>Next</Button>
            </nav>
          ) : null}
        </div>
      )}
    </Page>
  );
}
