"use client";

/**
 * Mark attendance. Visible content only when a lecture is live. Two ways in:
 *   * QR / code: scan the code on the classroom screen with the phone camera (it opens
 *     /student/scan), or type the six digits here.
 *   * Selfie: a live face check, enabled once the student has enrolled their face.
 * Both run the same server checks (time window, geofence, enrolled in this class, retry limit).
 */
import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/client";
import { Page, PageHeader } from "@/components/shell";
import { Banner, Card, CardHeader, Mark, Pill } from "@/components/ui";
import { Button, TextField } from "@/components/forms";
import { EmptyState, PageError, PageLoading } from "@/components/states";
import { getLocation, LocationHelp, type GeoFailure } from "@/components/geo-help";
import { SelfieMark } from "@/components/selfie-mark";
import Link from "next/link";

type ActiveSession = {
  id: number; subject_code: string | null; subject_name: string | null; room: string;
  scheduled_start: string; scheduled_end: string; marked: boolean; status: string | null;
  method: string | null; would_be: string | null; window_open: boolean; attempts_left: number;
};
type Payload = {
  approved: boolean; sessions: ActiveSession[]; requires_code: boolean; geofence: boolean;
  face_ready: boolean; windows: { present_min: number; late_min: number };
};

export default function MarkPage() {
  const [data, setData] = useState<Payload | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.get<Payload>("/api/me/sessions/active"));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not check for a live lecture.");
    }
  }, []);
  useEffect(() => {
    load();
    const t = setInterval(load, 20000);
    return () => clearInterval(t);
  }, [load]);

  return (
    <Page>
      <PageHeader title="Mark attendance" subtitle={data ? `present within ${data.windows.present_min} min · late until ${data.windows.late_min} min` : ""} />
      {error ? <PageError message={error} retry={load} /> : !data ? <PageLoading rows={2} /> : !data.approved ? (
        <Banner>Your account is awaiting approval, so you cannot mark attendance yet.</Banner>
      ) : !data.sessions.length ? (
        <EmptyState title="No lecture is live right now">
          This page shows a lecture as soon as your teacher starts it (or at its start time). It
          refreshes itself.
        </EmptyState>
      ) : (
        <div className="grid gap-4">
          {data.sessions.map((s) => (
            <SessionCard key={s.id} s={s} data={data} onDone={load} />
          ))}
        </div>
      )}
    </Page>
  );
}

function SessionCard({ s, data, onDone }: { s: ActiveSession; data: Payload; onDone: () => void }) {
  const [mode, setMode] = useState<"selfie" | "code">(data.face_ready ? "selfie" : "code");
  const start = new Date(s.scheduled_start);
  return (
    <Card>
      <CardHeader
        title={`${s.subject_code ?? ""} ${s.subject_name ?? ""}`.trim()}
        meta={`${s.room} · started ${start.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`}
      />
      {s.marked ? (
        <div className="flex items-center gap-3">
          <Mark status={s.status ?? "present"} />
          <div>
            <strong>You are marked {s.status?.replace("_", " ")}.</strong>
            <div className="text-[13px] text-ash">via {s.method}</div>
          </div>
        </div>
      ) : !s.window_open ? (
        <Banner bad>The attendance window for this lecture has closed. Ask your teacher if you were here.</Banner>
      ) : s.attempts_left <= 0 ? (
        <Banner bad>You have used all your attempts for this lecture. Ask your teacher to mark you.</Banner>
      ) : (
        <>
          <p className="mt-0 text-[13.5px]">
            You will be marked <Pill tone={s.would_be === "late" ? "warn" : "ok"}>{s.would_be}</Pill>{" "}
            · {s.attempts_left} attempt{s.attempts_left === 1 ? "" : "s"} left
          </p>
          <div role="tablist" aria-label="How to mark" className="mb-3 flex gap-1">
            {(["selfie", "code"] as const).map((m) => (
              <button key={m} role="tab" type="button" aria-selected={mode === m} onClick={() => setMode(m)}
                      className="display cursor-pointer rounded-[var(--radius)] border px-3 py-1.5 text-[12.5px]"
                      style={mode === m ? { background: "var(--grad-primary)", borderColor: "transparent", color: "var(--on-accent)" } : { borderColor: "var(--rule)", color: "var(--ink)", background: "transparent" }}>
                {m === "selfie" ? "Face check" : "Classroom code / QR"}
              </button>
            ))}
          </div>
          {mode === "code" ? (
            <CodeMark sessionId={s.id} onDone={onDone} />
          ) : data.face_ready ? (
            <SelfieMark sessionId={s.id} requiresCode={data.requires_code} onDone={onDone} />
          ) : (
            <Banner>
              The face check needs your face enrolled and approved first.{" "}
              <Link href="/student/face" className="text-ink underline">Enroll your face</Link> (one time), or use the classroom code.
            </Banner>
          )}
        </>
      )}
    </Card>
  );
}

function CodeMark({ sessionId, onDone }: { sessionId: number; onDone: () => void }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);
  const [geoFail, setGeoFail] = useState<GeoFailure | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!/^\d{6}$/.test(code)) return setResult({ ok: false, text: "Enter the 6-digit code on the classroom screen." });
    setBusy(true);
    setResult(null);
    setGeoFail(null);
    let fix;
    try {
      fix = await getLocation();
    } catch (reason) {
      setGeoFail(reason as GeoFailure);
      setBusy(false);
      return;
    }
    try {
      const r = await api.post<{ message: string }>("/api/attendance/qr", { session_id: sessionId, code, ...fix });
      setResult({ ok: true, text: r.message });
      setTimeout(onDone, 1500);
    } catch (err) {
      setResult({ ok: false, text: err instanceof Error ? err.message : "Could not mark attendance." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} noValidate className="grid gap-3">
      <p className="m-0 text-[13.5px] text-ash">
        Scan the QR on the classroom screen with your phone camera, or type the 6-digit code shown
        under it. The code changes every 30 seconds. Your location is checked once.
      </p>
      <TextField
        label="Classroom code"
        inputMode="numeric"
        autoComplete="one-time-code"
        maxLength={6}
        value={code}
        onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
        className="font-mono text-[22px] tracking-[0.4em]"
      />
      {geoFail ? <Banner bad><LocationHelp reason={geoFail} /></Banner> : null}
      {result ? <Banner bad={!result.ok}>{result.text}</Banner> : null}
      <div><Button type="submit" variant="primary" busy={busy}>Mark me present</Button></div>
    </form>
  );
}
