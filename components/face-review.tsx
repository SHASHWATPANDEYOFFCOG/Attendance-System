"use client";

/** Teacher review of face enrollments and re-enrollment requests (Approvals → Faces). */
import { useCallback, useEffect, useState } from "react";

import Link from "next/link";

import { api } from "@/lib/client";
import { Card, Pill } from "@/components/ui";
import { Button } from "@/components/forms";
import { EmptyState, PageError, PageLoading } from "@/components/states";
import { useUi } from "@/components/toast";

type Pending = {
  id: number; student_id: number; student: string; roll_number: string | null; section: string | null;
  photo_url: string | null; liveness_passed: boolean; mean_quality: number; created_at: string; reenrollment: boolean;
};
type Reenroll = { id: number; student_id: number; student: string; roll_number: string | null; reason: string; created_at: string };

export function FaceReview({ onChange }: { onChange: () => void }) {
  const { toast, askReason } = useUi();
  const [rows, setRows] = useState<Pending[] | null>(null);
  const [requests, setRequests] = useState<Reenroll[]>([]);
  const [samples, setSamples] = useState<Record<number, string[]>>({});
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [e, r] = await Promise.all([api.get<Pending[]>("/api/face-enrollments"), api.get<Reenroll[]>("/api/reenroll-requests")]);
      setRows(e);
      setRequests(r);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load.");
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  async function show(id: number) {
    try {
      const r = await api.get<{ images: string[] }>(`/api/face-enrollments/${id}/samples`);
      setSamples((m) => ({ ...m, [id]: r.images }));
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not load the photos.", "bad");
    }
  }

  async function decide(path: string, approve: boolean, who: string) {
    try {
      if (approve) await api.post(`${path}/approve`, {});
      else {
        const reason = await askReason({ title: `Reject for ${who}?`, danger: true, confirmLabel: "Reject",
          reason: { label: "Reason shown to the student", minLength: 3, placeholder: "e.g. photos are of someone else / too dark" } });
        if (!reason) return;
        await api.post(`${path}/reject`, { reason });
      }
      toast(approve ? "Approved." : "Rejected.");
      load();
      onChange();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Action failed.", "bad");
    }
  }

  if (error) return <PageError message={error} retry={load} />;
  if (!rows) return <PageLoading />;
  return (
    <div className="grid gap-4">
      {!rows.length && !requests.length ? <EmptyState title="No face enrollments or requests waiting" /> : null}
      {rows.map((e) => (
        <Card key={e.id}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <Link href={`/staff/students/${e.student_id}`} className="font-semibold text-ink">{e.student}</Link>
              <span className="ml-2 font-mono text-[12px] text-ash">{e.roll_number} · {e.section}</span>
              <div className="mt-1 flex flex-wrap gap-1">
                <Pill tone={e.liveness_passed ? "ok" : "warn"}>{e.liveness_passed ? "liveness passed" : "uploaded, no liveness"}</Pill>
                {e.reenrollment ? <Pill tone="neutral">re-enrollment</Pill> : null}
                <Pill tone="neutral">quality {Math.round(e.mean_quality * 100)}%</Pill>
              </div>
            </div>
            <div className="flex gap-2">
              <Button variant="primary" onClick={() => decide(`/api/face-enrollments/${e.id}`, true, e.student)}>Approve</Button>
              <Button onClick={() => decide(`/api/face-enrollments/${e.id}`, false, e.student)}>Reject</Button>
            </div>
          </div>
          <p className="mb-2 mt-2 text-[13px] text-ash">Check that these photos show the same person as the profile photo. They are deleted as soon as you decide.</p>
          <div className="flex flex-wrap items-end gap-2">
            {e.photo_url ? (
              <figure className="m-0 text-center">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={`/api/backend${e.photo_url}`} alt="Profile photo" className="h-[96px] w-[96px] rounded-[3px] border-2 object-cover" style={{ borderColor: "var(--ink)" }} />
                <figcaption className="label text-[10px]">profile</figcaption>
              </figure>
            ) : null}
            {samples[e.id] ? samples[e.id].map((src, i) => (
              // eslint-disable-next-line @next/next/no-img-element
              <img key={i} src={src} alt={`Enrollment photo ${i + 1}`} className="h-[96px] w-[96px] rounded-[3px] border border-rule object-cover" />
            )) : <Button onClick={() => show(e.id)}>Show enrollment photos</Button>}
          </div>
        </Card>
      ))}
      {requests.length ? (
        <Card>
          <h2 className="display m-0 mb-2 text-[15px] text-ash">Re-enrollment requests</h2>
          <ul className="m-0 list-none p-0">
            {requests.map((r) => (
              <li key={r.id} className="flex flex-wrap items-center justify-between gap-2 border-b border-rule py-2 last:border-0">
                <div>
                  <Link href={`/staff/students/${r.student_id}`} className="font-semibold text-ink">{r.student}</Link>
                  <span className="ml-2 font-mono text-[12px] text-ash">{r.roll_number}</span>
                  <div className="text-[13px] text-ash">“{r.reason}”</div>
                </div>
                <div className="flex gap-2">
                  <Button variant="primary" onClick={() => decide(`/api/reenroll-requests/${r.id}`, true, r.student)}>Allow</Button>
                  <Button onClick={() => decide(`/api/reenroll-requests/${r.id}`, false, r.student)}>Decline</Button>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}
