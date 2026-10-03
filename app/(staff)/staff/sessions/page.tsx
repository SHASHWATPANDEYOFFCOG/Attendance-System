"use client";

/** Today's lectures: start, watch live, stop. Lectures also start and stop on their own from the
 *  timetable; this page is for starting early, stopping, and jumping into the live view. */
import { useCallback, useEffect, useState } from "react";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { api } from "@/lib/client";
import { Page, PageHeader } from "@/components/shell";
import { Card, Pill } from "@/components/ui";
import { Button, TextField } from "@/components/forms";
import { EmptyState, PageError, PageLoading } from "@/components/states";
import { useUi } from "@/components/toast";

type Counts = { roster: number; present: number; late: number; absent: number; on_leave: number; unmarked: number };
type Card_ = { id: number; state: string; counts: Counts; review_pending: number };
type Period = {
  slot_id: number | null; subject_code: string | null; subject_name: string | null; room: string;
  start_time: string; end_time: string; section_label: string | null; holiday: string | null;
  session: Card_ | null;
};

export default function SessionsPage() {
  const router = useRouter();
  const { toast, confirm } = useUi();
  const [day, setDay] = useState("");
  const [data, setData] = useState<{ date: string; periods: Period[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.get(`/api/sessions/live${day ? `?on=${day}` : ""}`));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load today's lectures.");
    }
  }, [day]);
  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [load]);

  async function startSlot(p: Period) {
    setBusy(`slot-${p.slot_id}`);
    try {
      const s = await api.post<{ id: number }>("/api/sessions/open", { slot_id: p.slot_id, date: data?.date, start: true });
      toast("Session started. Students can mark attendance now.");
      router.push(`/staff/sessions/${s.id}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not start.", "bad");
    } finally {
      setBusy(null);
    }
  }

  async function stop(id: number) {
    if (!(await confirm({ title: "Close this session?", body: "Everyone not marked becomes Absent (or On leave, if an approved leave covers them).", confirmLabel: "Close session", danger: true }))) return;
    setBusy(`s-${id}`);
    try {
      await api.post(`/api/sessions/${id}/stop`);
      toast("Session closed.");
      load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not close.", "bad");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Page wide>
      <PageHeader
        title="Live sessions"
        subtitle={data ? `${data.date} · ${data.periods.length} lecture(s)` : ""}
        actions={<div className="w-[180px]"><TextField label="Date" type="date" value={day} onChange={(e) => setDay(e.target.value)} /></div>}
      />
      {error ? <PageError message={error} retry={load} /> : !data ? <PageLoading /> : !data.periods.length ? (
        <EmptyState title="No lectures on this day">Lectures come from the timetable (Setup → Timetable).</EmptyState>
      ) : (
        <div className="grid gap-3">
          {data.periods.map((p, i) => {
            const s = p.session;
            const c = s?.counts;
            return (
              <Card key={s?.id ?? `slot-${p.slot_id}-${i}`}>
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="font-mono text-[13px] text-ash">{p.start_time}–{p.end_time} · {p.room}</div>
                    <div className="text-[16px] font-semibold">{p.subject_code} <span className="font-normal text-ash">{p.subject_name}</span></div>
                    <div className="text-[13px] text-ash">{p.section_label}</div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    {p.holiday ? <Pill tone="neutral">holiday · {p.holiday}</Pill> : null}
                    {s ? <Pill tone={s.state === "active" ? "ok" : s.state === "closed" ? "neutral" : "warn"}>{s.state}</Pill> : null}
                    {s?.review_pending ? <Pill tone="bad">{s.review_pending} to review</Pill> : null}
                  </div>
                </div>
                {c ? (
                  <dl className="mt-3 grid grid-cols-3 gap-2 text-center sm:grid-cols-6">
                    {([["Present", c.present, "var(--status-present)"], ["Late", c.late, "var(--status-late)"],
                      ["Absent", c.absent, "var(--status-absent)"], ["On leave", c.on_leave, "var(--status-leave)"],
                      ["Unmarked", c.unmarked, "var(--ash)"], ["Class", c.roster, "var(--ink)"]] as const).map(([k, v, col]) => (
                      <div key={k} className="rounded-[3px] border border-rule py-1.5">
                        <dt className="label text-[10.5px]">{k}</dt>
                        <dd className="m-0 font-mono text-[20px] font-semibold tnum" style={{ color: col }}>{v}</dd>
                      </div>
                    ))}
                  </dl>
                ) : null}
                <div className="mt-3 flex flex-wrap gap-2">
                  {!s && p.slot_id && !p.holiday ? (
                    <Button variant="primary" busy={busy === `slot-${p.slot_id}`} onClick={() => startSlot(p)}>Start session</Button>
                  ) : null}
                  {s ? <Link href={`/staff/sessions/${s.id}`} className="display rounded-[3px] border border-ink px-3.5 py-2 text-[12px] text-ink no-underline hover:bg-tint">Live view</Link> : null}
                  {s?.state === "active" ? (
                    <>
                      <Link href={`/present/${s.id}`} target="_blank" className="display rounded-[3px] border border-ink px-3.5 py-2 text-[12px] text-ink no-underline hover:bg-tint">Show QR full-screen</Link>
                      <Button busy={busy === `s-${s.id}`} onClick={() => stop(s.id)}>Close session</Button>
                    </>
                  ) : null}
                  {p.slot_id ? <Link href={`/mark/${p.slot_id}${data.date ? `?date=${data.date}` : ""}`} className="display self-center px-2 text-[11.5px] text-ink">Register</Link> : null}
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </Page>
  );
}
