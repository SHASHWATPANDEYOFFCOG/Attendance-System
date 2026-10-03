"use client";

/** Mark attendance with a live face check: location, a short head-turn challenge, then submit. */
import { useState } from "react";

import { api } from "@/lib/client";
import { Banner } from "@/components/ui";
import { Button, TextField } from "@/components/forms";
import { GuidedCapture } from "@/components/camera";
import { getLocation, LocationHelp, type Fix, type GeoFailure } from "@/components/geo-help";

type Challenge = { id: number; steps: string[]; instructions: string[] };

export function SelfieMark({ sessionId, requiresCode, onDone }: { sessionId: number; requiresCode: boolean; onDone: () => void }) {
  const [stage, setStage] = useState<"intro" | "capture" | "sending" | "done" | "failed">("intro");
  const [challenge, setChallenge] = useState<Challenge | null>(null);
  const [fix, setFix] = useState<Fix | null>(null);
  const [geoFail, setGeoFail] = useState<GeoFailure | null>(null);
  const [code, setCode] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function begin() {
    if (requiresCode && !/^\d{6}$/.test(code)) return setMessage("Enter the 6-digit code on the classroom screen first.");
    setBusy(true);
    setMessage(null);
    setGeoFail(null);
    try {
      setFix(await getLocation());
    } catch (reason) {
      setGeoFail(reason as GeoFailure);
      setBusy(false);
      return;
    }
    try {
      setChallenge(await api.post<Challenge>("/api/me/face/challenge", { purpose: "attendance", session_id: sessionId }));
      setStage("capture");
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Could not start the face check.");
    } finally {
      setBusy(false);
    }
  }

  async function submit(frames: Blob[]) {
    if (!challenge || !fix) return;
    setStage("sending");
    const fd = new FormData();
    fd.append("challenge_id", String(challenge.id));
    frames.forEach((f, i) => fd.append("frames", f, `${i}.jpg`));
    fd.append("lat", String(fix.lat));
    fd.append("lng", String(fix.lng));
    fd.append("accuracy", String(fix.accuracy));
    if (code) fd.append("code", code);
    try {
      const r = await api.upload<{ message: string }>(`/api/attendance/sessions/${sessionId}/self-mark`, fd);
      setMessage(r.message);
      setStage("done");
      setTimeout(onDone, 1500);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Could not mark attendance.");
      setStage("failed");
    }
  }

  if (stage === "capture" && challenge) {
    return <GuidedCapture steps={challenge.steps} instructions={challenge.instructions} onComplete={submit} />;
  }
  if (stage === "sending") return <p className="m-0 text-[15px]" role="status">Checking your face and location…</p>;
  if (stage === "done") return <Banner><strong className="label mb-0.5 block">Done</strong>{message}</Banner>;

  return (
    <div className="grid gap-3">
      {stage === "failed" ? <Banner bad><strong className="label mb-0.5 block">Not marked</strong>{message}</Banner> : null}
      <p className="m-0 text-[13.5px] text-ash">
        Face the camera in good light. You will be asked to look straight, then turn your head slightly
        both ways — this proves it is really you, live. Your location is checked once. Nothing is stored
        except the result.
      </p>
      {requiresCode ? (
        <TextField label="Classroom code" inputMode="numeric" maxLength={6} value={code}
                   onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} className="font-mono text-[20px] tracking-[0.4em]" />
      ) : null}
      {geoFail ? <Banner bad><LocationHelp reason={geoFail} /></Banner> : null}
      {message && stage !== "failed" ? <Banner bad>{message}</Banner> : null}
      <div><Button variant="primary" busy={busy} onClick={begin}>{stage === "failed" ? "Try again" : "Start face check"}</Button></div>
    </div>
  );
}
