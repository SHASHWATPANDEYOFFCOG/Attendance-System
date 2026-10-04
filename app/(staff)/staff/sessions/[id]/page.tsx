"use client";

/**
 * Live session: students appear as they are marked (CCTV, selfie, QR, or by hand), over the
 * same server-sent-event stream the camera worker publishes to. The roster is re-fetched on each
 * event rather than patched from the event payload — a missed event can never leave the screen
 * wrong, only briefly stale.
 */
import { use, useCallback, useEffect, useRef, useState } from "react";

import Link from "next/link";

import { api } from "@/lib/client";
import { Page, PageHeader } from "@/components/shell";
import { Banner, Card, CardHeader, Mark, Pill } from "@/components/ui";
import { Button } from "@/components/forms";
import { PageError, PageLoading } from "@/components/states";
import { useUi } from "@/components/toast";
import { ClassCamera, TabletPhoto } from "@/components/class-attendance";

type Row = {
  user_id: number; display_name: string; roll_number: string | null; record_id: number | null;
  status: string | null; method: string | null; marked_at: string | null; confidence: number | null;
  overridden: boolean; needs_review: boolean;
};
type Live = {
  id: number; title: string; state: string; room: string; subject_code: string | null;
  subject_name: string | null; section_label: string | null; scheduled_start: string; scheduled_end: string;
  is_locked: boolean; review_pending: number;
  counts: { roster: number; present: number; late: number; absent: number; on_leave: number; unmarked: number };
  roster: Row[]; windows: { present_min: number; late_min: number };
};

const QUICK = [
  ["present", "P"], ["late", "L"], ["absent", "A"], ["on_leave", "O"], ["excused", "E"],
] as const;
const METHOD: Record<string, string> = { cctv: "camera", face: "camera", mobile: "selfie", qr: "QR", manual: "teacher", system: "auto", photo: "tablet photo" };

export default function LiveSessionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const sid = Number(id);
  const { toast, confirm, askReason } = useUi();
  const [data, setData] = useState<Live | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);
  const [flash, setFlash] = useState<number | null>(null);
  const refetch = useRef<() => void>(() => {});

  const load = useCallback(async () => {
    try {
      setData(await api.get<Live>(`/api/sessions/${sid}/live`));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load the session.");
    }
  }, [sid]);
  useEffect(() => {
    refetch.current = load;
  }, [load]);

  useEffect(() => {
    load();
    let es: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    const connect = () => {
      es = new EventSource(`/api/backend/api/live/stream?session_id=${sid}`);
      es.addEventListener("hello", () => setConnected(true));
      const onEvent = (ev: MessageEvent) => {
        try {
          const d = JSON.parse(ev.data);
          if (d.user_id) {
            setFlash(d.user_id);
            setTimeout(() => setFlash(null), 1800);
          }
        } catch {
          /* keepalive */
        }
        refetch.current();
      };
      for (const kind of ["record_updated", "attendance_marked", "record_overridden", "checkin", "session_state", "review_item"]) {
        es.addEventListener(kind, onEvent as EventListener);
      }
      es.onerror = () => {
        setConnected(false);
        es?.close();
        retry = setTimeout(connect, 5000);           // reconnect; re-fetch covers the gap
      };
    };
    connect();
    const poll = setInterval(load, 30000);           // belt and braces if a proxy buffers SSE
    return () => {
      es?.close();
      if (retry) clearTimeout(retry);
      clearInterval(poll);
    };
  }, [sid, load]);

  async function mark(row: Row, status: string) {
    if (row.status === status) return;
    let reason: string | null | undefined;
    if (row.status && row.method !== "system") {
      reason = await askReason({
        title: `Change ${row.display_name} to ${status.replace("_", " ")}?`,
        body: `Currently ${row.status.replace("_", " ")} (${METHOD[row.method ?? ""] ?? row.method}). The change and your reason are recorded in the audit log and the student is notified.`,
        confirmLabel: "Change",
        reason: { label: "Reason", minLength: 3, placeholder: "e.g. seen in class, camera missed them" },
      });
      if (!reason) return;
    }
    try {
      await api.post(`/api/attendance/sessions/${sid}/records`, { marks: [{ user_id: row.user_id, status, reason: reason ?? undefined }] });
      load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not save.", "bad");
    }
  }

  async function act(kind: "start" | "stop") {
    if (kind === "stop" && !(await confirm({ title: "Close this session?", body: "Everyone not marked becomes Absent (or On leave where an approved leave covers them).", confirmLabel: "Close session", danger: true }))) return;
    try {
      await api.post(`/api/sessions/${sid}/${kind}`);
      toast(kind === "start" ? "Session started." : "Session closed.");
      load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Action failed.", "bad");
    }
  }

  if (error) return <Page><PageHeader title="Live session" /><PageError message={error} retry={load} /></Page>;
  if (!data) return <Page><PageHeader title="Live session" /><PageLoading /></Page>;
  const c = data.counts;
  const start = new Date(data.scheduled_start);
  const end = new Date(data.scheduled_end);

  return (
    <Page wide>
      <PageHeader
        title={`${data.subject_code ?? data.title}${data.section_label ? ` · ${data.section_label}` : ""}`}
        subtitle={`${data.room} · ${start.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}–${end.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} · present within ${data.windows.present_min} min, late until ${data.windows.late_min} min`}
        actions={
          <>
            <Pill tone={data.state === "active" ? "ok" : data.state === "closed" ? "neutral" : "warn"}>{data.state}</Pill>
            <span className="inline-flex items-center gap-1 text-[12px] text-ash" title={connected ? "Live updates connected" : "Reconnecting"}>
              <span className="h-2 w-2 rounded-full" style={{ background: connected ? "var(--verdant)" : "var(--amber)" }} aria-hidden />
              {connected ? "live" : "reconnecting"}
            </span>
            {data.state === "scheduled" ? <Button variant="primary" onClick={() => act("start")}>Start session</Button> : null}
            {data.state === "active" ? (
              <>
                <Link href={`/present/${sid}`} target="_blank" className="display rounded-[3px] border px-3.5 py-2 text-[12px] no-underline" style={{ background: "var(--ink)", borderColor: "var(--ink)", color: "var(--card)" }}>Show QR full-screen</Link>
                <Button onClick={() => act("stop")}>Close session</Button>
              </>
            ) : null}
          </>
        }
      />

      {data.is_locked ? <Banner bad>This session is locked (past the edit window). Changes need a correction request.</Banner> : null}
      {data.review_pending ? (
        <Banner>
          <strong className="label mb-0.5 block">Review queue</strong>
          {data.review_pending} near-match camera sighting(s) need your decision.{" "}
          <Link href={`/staff/review?session=${sid}`} className="text-ink underline">Review now</Link>
        </Banner>
      ) : null}

      <div className="mb-4 grid grid-cols-3 gap-2 sm:grid-cols-6">
        {([["Present", c.present, "var(--status-present)"], ["Late", c.late, "var(--status-late)"], ["Absent", c.absent, "var(--status-absent)"],
          ["On leave", c.on_leave, "var(--status-leave)"], ["Unmarked", c.unmarked, "var(--ash)"], ["Class", c.roster, "var(--ink)"]] as const).map(([k, v, col]) => (
          <div key={k} className="rounded-[3px] border border-rule bg-card py-2 text-center shadow-card">
            <div className="label text-[10.5px]">{k}</div>
            <div className="font-mono text-[24px] font-semibold tnum" style={{ color: col }}>{v}</div>
          </div>
        ))}
      </div>

      <div className="mb-4 grid gap-4 xl:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
        <TabletPhoto sessionId={Number(sid)} live={data.state === "active"} onMarked={load} />
        <ClassCamera sessionId={Number(sid)} live={data.state === "active"} />
      </div>

      <Card>
        <CardHeader title="Class list" meta="tap a letter to mark · changing a recorded mark asks for a reason" />
        <ul className="m-0 list-none p-0" aria-live="polite">
          {data.roster.map((r) => (
            <li
              key={r.user_id}
              className="flex flex-wrap items-center justify-between gap-2 border-b border-rule py-2 transition-colors last:border-0"
              style={flash === r.user_id ? { background: "color-mix(in srgb, var(--verdant) 14%, transparent)" } : undefined}
            >
              <div className="flex min-w-0 items-center gap-3">
                {r.status ? <Mark status={r.status} /> : <span className="inline-block h-6 w-6 rounded-[2px] border border-dashed border-rule" aria-label="not marked" />}
                <div className="min-w-0">
                  <div className="truncate text-[14px] font-semibold">{r.display_name}</div>
                  <div className="font-mono text-[11px] text-ash">
                    {r.roll_number}
                    {r.method ? ` · ${METHOD[r.method] ?? r.method}` : ""}
                    {r.marked_at ? ` · ${new Date(r.marked_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}` : ""}
                    {r.confidence != null ? ` · ${(r.confidence * 100).toFixed(0)}% match` : ""}
                    {r.overridden ? " · changed by teacher" : ""}
                  </div>
                </div>
              </div>
              {!data.is_locked ? (
                <div className="flex gap-1" role="group" aria-label={`Mark ${r.display_name}`}>
                  {QUICK.map(([status, letter]) => (
                    <button
                      key={status}
                      type="button"
                      onClick={() => mark(r, status)}
                      aria-pressed={r.status === status}
                      title={status.replace("_", " ")}
                      className="h-9 w-9 cursor-pointer rounded-[3px] border font-mono text-[13px] font-semibold"
                      style={r.status === status
                        ? { background: "var(--ink)", borderColor: "var(--ink)", color: "var(--card)" }
                        : { background: "transparent", borderColor: "var(--rule)", color: "var(--ink)" }}
                    >
                      {letter}
                    </button>
                  ))}
                </div>
              ) : null}
            </li>
          ))}
        </ul>
      </Card>
    </Page>
  );
}
