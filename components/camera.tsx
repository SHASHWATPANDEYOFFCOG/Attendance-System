"use client";

/**
 * Guided face capture, shared by face enrollment and selfie attendance.
 *
 * The browser only GUIDES: it shows the instruction for each step, sends a frame to the server
 * about once a second for feedback ("too dark", "turn a little to your left"), and captures the
 * step once two consecutive frames pass. Whether the result is accepted — quality, pose sequence,
 * liveness, identity — is decided again on the server from the captured frames themselves.
 *
 * Frames are taken from the raw camera stream (unmirrored); only the on-screen preview is
 * mirrored so it behaves like a mirror for the student.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/lib/client";
import { Button } from "@/components/forms";

export type CameraFailure = "denied" | "none" | "busy" | "insecure" | "unsupported";

export function CameraHelp({ reason }: { reason: CameraFailure }) {
  if (reason === "insecure")
    return <p className="m-0 text-[13.5px]">The camera only works over a secure (https) connection. Open the portal from its https address.</p>;
  if (reason === "unsupported")
    return <p className="m-0 text-[13.5px]">This browser cannot use the camera. Use Chrome on Android or Safari on iPhone, or use the classroom code instead.</p>;
  if (reason === "none")
    return <p className="m-0 text-[13.5px]">No camera was found on this device. Use a phone or laptop with a front camera, or the classroom code instead.</p>;
  if (reason === "busy")
    return <p className="m-0 text-[13.5px]">The camera is being used by another app (a video call?). Close it and try again.</p>;
  return (
    <div className="grid gap-2 text-[13.5px]">
      <p className="m-0"><strong>Camera access is blocked for this site.</strong> Allow it, then reload:</p>
      <div>
        <span className="label block">Android · Chrome</span>
        Tap the <strong>lock / tune icon</strong> left of the address → <strong>Permissions</strong> → <strong>Camera</strong> →{" "}
        <strong>Allow</strong>. If it stays blocked: phone <strong>Settings → Apps → Chrome → Permissions → Camera → Allow</strong>.
      </div>
      <div>
        <span className="label block">iPhone · Safari</span>
        Tap <strong>aA</strong> in the address bar → <strong>Website Settings</strong> → <strong>Camera</strong> → <strong>Allow</strong>. Also check{" "}
        <strong>Settings → Safari → Camera</strong> is set to <strong>Ask</strong> or <strong>Allow</strong>.
      </div>
    </div>
  );
}

function classify(err: unknown): CameraFailure {
  const name = (err as { name?: string })?.name ?? "";
  if (name === "NotAllowedError" || name === "SecurityError") return "denied";
  if (name === "NotFoundError" || name === "OverconstrainedError") return "none";
  if (name === "NotReadableError" || name === "AbortError") return "busy";
  return "denied";
}

export function useCamera() {
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);
  const [ready, setReady] = useState(false);
  const [failure, setFailure] = useState<CameraFailure | null>(null);

  const start = useCallback(async () => {
    setFailure(null);
    if (!window.isSecureContext) return setFailure("insecure");
    if (!navigator.mediaDevices?.getUserMedia) return setFailure("unsupported");
    try {
      const s = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 960 }, height: { ideal: 720 } },
        audio: false,
      });
      stream.current = s;
      if (video.current) {
        video.current.srcObject = s;
        // iOS Safari requires muted + playsInline for autoplay of a camera stream.
        await video.current.play().catch(() => {});
      }
      setReady(true);
    } catch (e) {
      setFailure(classify(e));
    }
  }, []);

  const stop = useCallback(() => {
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
    setReady(false);
  }, []);

  useEffect(() => stop, [stop]);

  const capture = useCallback(async (): Promise<Blob | null> => {
    const v = video.current;
    if (!v || !v.videoWidth) return null;
    const c = document.createElement("canvas");
    c.width = v.videoWidth;
    c.height = v.videoHeight;
    c.getContext("2d")?.drawImage(v, 0, 0);
    return new Promise((res) => c.toBlob((b) => res(b), "image/jpeg", 0.88));
  }, []);

  return { video, ready, failure, start, stop, capture };
}

type Check = { ok: boolean; message: string; pitch: number | null };

export function GuidedCapture({
  steps,
  instructions,
  onComplete,
  busy,
}: {
  steps: string[];
  instructions: string[];
  onComplete: (frames: Blob[]) => void;
  busy?: boolean;
}) {
  const { video, ready, failure, start, stop, capture } = useCamera();
  const [index, setIndex] = useState(0);
  const [frames, setFrames] = useState<Blob[]>([]);
  const [check, setCheck] = useState<Check | null>(null);
  const frontPitch = useRef<number | null>(null);
  const streak = useRef(0);
  const inFlight = useRef(false);

  useEffect(() => {
    start();
  }, [start]);

  const done = index >= steps.length;

  useEffect(() => {
    if (!ready || done || busy) return;
    let cancelled = false;
    const tick = async () => {
      if (inFlight.current || cancelled) return;
      inFlight.current = true;
      try {
        const blob = await capture();
        if (!blob) return;
        const fd = new FormData();
        fd.append("frame", blob, "frame.jpg");
        fd.append("expect", steps[index]);
        if (frontPitch.current != null) fd.append("front_pitch", String(frontPitch.current));
        const r = await api.upload<Check>("/api/me/face/check", fd);
        if (cancelled) return;
        setCheck(r);
        streak.current = r.ok ? streak.current + 1 : 0;
        if (streak.current >= 2) {
          // Two good frames in a row: keep this one for the step.
          if (steps[index] === "front" && r.pitch != null) frontPitch.current = r.pitch;
          streak.current = 0;
          setFrames((f) => [...f, blob]);
          setIndex((i) => i + 1);
          setCheck(null);
        }
      } catch (e) {
        if (!cancelled) setCheck({ ok: false, message: e instanceof Error ? e.message : "Checking failed.", pitch: null });
      } finally {
        inFlight.current = false;
      }
    };
    const t = setInterval(tick, 900);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, [ready, capture, index, steps, done, busy]);

  useEffect(() => {
    if (done && frames.length === steps.length) {
      stop();
      onComplete(frames);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [done]);

  if (failure) {
    return (
      <div className="rounded-[3px] border-l-4 px-3.5 py-3" style={{ borderLeftColor: "var(--oxide)", background: "color-mix(in srgb, var(--oxide) 10%, transparent)" }}>
        <CameraHelp reason={failure} />
        <Button className="mt-3" onClick={start}>Try again</Button>
      </div>
    );
  }

  return (
    <div className="grid gap-3">
      <div className="relative mx-auto aspect-[3/4] w-full max-w-[360px] overflow-hidden rounded-[6px] bg-black">
        {/* muted + playsInline: required for iPhone Safari to play a camera stream inline. */}
        <video ref={video} muted playsInline autoPlay className="h-full w-full -scale-x-100 object-cover" aria-label="Camera preview" />
        <svg viewBox="0 0 300 400" className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden="true">
          <defs>
            <mask id="oval">
              <rect width="300" height="400" fill="white" />
              <ellipse cx="150" cy="185" rx="95" ry="128" fill="black" />
            </mask>
          </defs>
          <rect width="300" height="400" fill="rgba(0,0,0,0.45)" mask="url(#oval)" />
          <ellipse cx="150" cy="185" rx="95" ry="128" fill="none" strokeWidth="4"
                   stroke={check?.ok ? "#5DBF92" : check ? "#E2A945" : "#ffffff"} strokeDasharray={check?.ok ? "0" : "10 8"} />
        </svg>
        {!ready ? <p className="absolute inset-x-0 top-1/2 m-0 text-center text-[14px] text-white">Starting camera…</p> : null}
      </div>
      <ol className="m-0 flex list-none justify-center gap-1.5 p-0" aria-label="Steps">
        {steps.map((s, i) => (
          <li key={s + i} className="h-2 w-8 rounded-full" style={{ background: i < index ? "var(--verdant)" : i === index ? "var(--ink)" : "var(--rule)" }}
              aria-label={`${instructions[i]}: ${i < index ? "done" : i === index ? "now" : "next"}`} />
        ))}
      </ol>
      <div aria-live="polite" className="min-h-[56px] text-center">
        {done ? (
          <p className="m-0 text-[15px] font-semibold">{busy ? "Checking…" : "All photos taken."}</p>
        ) : (
          <>
            <p className="m-0 text-[17px] font-semibold">{instructions[index]}</p>
            <p className="m-0 text-[13.5px]" style={{ color: check?.ok ? "var(--verdant)" : "var(--ash)" }}>
              {check ? (check.ok ? "Hold still…" : check.message) : "Position your face inside the outline."}
            </p>
          </>
        )}
      </div>
    </div>
  );
}
