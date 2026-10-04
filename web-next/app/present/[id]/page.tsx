"use client";

/**
 * Projector view: the rotating QR and its six digits, nothing else. Outside the portal shell on
 * purpose — no navigation, no names, nothing a room full of students should see on the wall.
 * Staff-only: the code endpoint refuses anyone else.
 */
import { use, useCallback, useEffect, useRef, useState } from "react";

import QRCode from "qrcode";

import { api } from "@/lib/client";

type Code = { code: string; expires_in: number; rotation_s: number; qr_url: string };
type Live = { subject_code: string | null; room: string; state: string; counts: { roster: number; present: number; late: number } };

export default function PresentPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const sid = Number(id);
  const [code, setCode] = useState<Code | null>(null);
  const [live, setLive] = useState<Live | null>(null);
  const [left, setLeft] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const canvas = useRef<HTMLCanvasElement>(null);

  const fetchCode = useCallback(async () => {
    try {
      const c = await api.get<Code>(`/api/sessions/${sid}/code`);
      setCode(c);
      setLeft(c.expires_in);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load the code.");
    }
  }, [sid]);

  useEffect(() => {
    fetchCode();
    const counts = () => api.get<Live>(`/api/sessions/${sid}/live`).then(setLive).catch(() => {});
    counts();
    const t = setInterval(counts, 5000);
    return () => clearInterval(t);
  }, [fetchCode, sid]);

  useEffect(() => {
    if (!code) return;
    const t = setInterval(() => {
      setLeft((l) => {
        if (l <= 1) {
          fetchCode();
          return 0;
        }
        return l - 1;
      });
    }, 1000);
    return () => clearInterval(t);
  }, [code, fetchCode]);

  useEffect(() => {
    if (!code || !canvas.current) return;
    const size = Math.min(window.innerWidth, window.innerHeight) * 0.62;
    QRCode.toCanvas(canvas.current, code.qr_url, { width: size, margin: 1, errorCorrectionLevel: "M" }).catch(() => {});
  }, [code]);

  return (
    <main className="fixed inset-0 z-[1] flex flex-col items-center justify-center gap-4 bg-white px-4 text-center" style={{ color: "#16304F" }}>
      {error ? (
        <div className="max-w-[520px] text-[20px]">
          <p>{error}</p>
          <button type="button" onClick={fetchCode} className="mt-3 cursor-pointer rounded border border-current px-4 py-2 text-[16px]">Retry</button>
        </div>
      ) : (
        <>
          <p className="m-0 font-mono text-[clamp(16px,2.4vw,26px)] tracking-wide">
            {live?.subject_code ?? ""} · {live?.room ?? ""} · scan to mark attendance
          </p>
          <canvas ref={canvas} aria-label="Attendance QR code" role="img" />
          <p className="m-0 font-mono text-[clamp(40px,8vw,96px)] font-semibold tracking-[0.3em]" aria-live="polite">
            {code ? `${code.code.slice(0, 3)} ${code.code.slice(3)}` : "··· ···"}
          </p>
          <div className="h-2 w-[min(520px,80vw)] overflow-hidden rounded-full" style={{ background: "#D9DDD3" }}>
            <div className="h-full transition-[width] duration-1000 ease-linear" style={{ width: `${code ? (left / code.rotation_s) * 100 : 0}%`, background: "#16304F" }} />
          </div>
          <p className="m-0 text-[clamp(14px,1.8vw,20px)]" style={{ color: "#6E7468" }}>
            New code in {left}s · {live ? `${live.counts.present + live.counts.late} of ${live.counts.roster} marked` : ""}
          </p>
          {live && live.state !== "active" ? <p className="m-0 text-[22px]" style={{ color: "#9A3B2E" }}>This session is {live.state}.</p> : null}
        </>
      )}
    </main>
  );
}
