"use client";

/**
 * Taking attendance from the front of the class.
 *
 *   ClassCamera  — connect any registered CCTV camera to this lecture, see what it sees,
 *                  disconnect. The camera then marks recognised students by itself.
 *   TabletPhoto  — photograph the class with the tablet (live viewfinder or the device's own
 *                  camera app). The server proposes who is in the photo; the teacher ticks and
 *                  confirms. Several photos can be combined (left half, right half of the room).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import Link from "next/link";

import { api } from "@/lib/client";
import { Button, SelectField } from "@/components/forms";
import { Banner, Card, CardHeader, Pill } from "@/components/ui";
import { CameraHelp, useCamera } from "@/components/camera";
import { useUi } from "@/components/toast";

/* ------------------------------------------------------------ classroom camera */

type Cam = { id: number; name: string; room: string; status: string; detail: string | null; running: boolean };
type CamState = {
  connected: Cam | null; in_room: Cam[]; available: Cam[];
  allowed: boolean; reason: string | null; tablet: { name: string; code: string } | null;
};

/** Shown instead of controls the server would refuse from this device. */
function TabletNeeded({ reason }: { reason: string | null }) {
  return (
    <Banner>
      <strong className="label mb-0.5 block">Registered tablet needed</strong>
      {reason ?? "Use a registered tablet for this."}{" "}
      <Link href="/staff/tablets" className="text-ink underline">Open Tablets</Link> to register and pair this device.
    </Banner>
  );
}

/** Whether this device may take attendance / control cameras for the lecture (server's answer). */
function useDeviceGate(sessionId: number) {
  const [gate, setGate] = useState<{ allowed: boolean; reason: string | null; tablet: CamState["tablet"] } | null>(null);
  useEffect(() => {
    api.get<CamState>(`/api/sessions/${sessionId}/camera`)
      .then((s) => setGate({ allowed: s.allowed, reason: s.reason, tablet: s.tablet }))
      .catch(() => setGate({ allowed: true, reason: null, tablet: null }));
  }, [sessionId]);
  return gate;
}

export function ClassCamera({ sessionId, live }: { sessionId: number; live: boolean }) {
  const { toast, confirm } = useUi();
  const [state, setState] = useState<CamState | null>(null);
  const [choice, setChoice] = useState("");
  const [busy, setBusy] = useState(false);
  const [preview, setPreview] = useState<{ src?: string; error?: string } | "loading" | null>(null);

  const load = useCallback(async () => {
    try {
      const s = await api.get<CamState>(`/api/sessions/${sessionId}/camera`);
      setState(s);
      setChoice((c) => c || String(s.in_room[0]?.id ?? s.available[0]?.id ?? ""));
    } catch {
      setState({ connected: null, in_room: [], available: [], allowed: true, reason: null, tablet: null });
    }
  }, [sessionId]);
  useEffect(() => {
    load();
  }, [load]);

  async function connect() {
    if (!choice) return;
    setBusy(true);
    try {
      await api.post(`/api/sessions/${sessionId}/camera`, { camera_id: Number(choice) });
      toast("Camera connected. Recognised students will be marked automatically.");
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not connect.", "bad");
    } finally {
      setBusy(false);
    }
  }

  async function disconnect() {
    if (!(await confirm({ title: "Disconnect the camera?", body: "It stops marking students for this lecture.", confirmLabel: "Disconnect" }))) return;
    setBusy(true);
    try {
      await api.del(`/api/sessions/${sessionId}/camera`);
      setPreview(null);
      toast("Camera disconnected.");
      await load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not disconnect.", "bad");
    } finally {
      setBusy(false);
    }
  }

  async function look() {
    setPreview("loading");
    try {
      const r = await api.get<{ ok: boolean; preview?: string; error?: string }>(`/api/sessions/${sessionId}/camera/preview`);
      setPreview(r.ok ? { src: r.preview } : { error: r.error ?? "The camera did not answer." });
    } catch (e) {
      setPreview({ error: e instanceof Error ? e.message : "The camera did not answer." });
    }
  }

  const cam = state?.connected;
  const roomCam = state?.in_room.find((c) => c.running);
  return (
    <Card>
      <CardHeader
        title="Classroom camera"
        meta={cam ? <Pill tone={cam.running ? "ok" : "warn"}>{cam.running ? "watching" : cam.status}</Pill> : roomCam ? <Pill tone="ok">room camera on</Pill> : null}
      />
      {!state ? <p className="m-0 text-[13.5px] text-ash">Loading cameras…</p> : !state.allowed ? (
        <TabletNeeded reason={state.reason} />
      ) : cam ? (
        <div className="grid gap-3">
          <p className="m-0 text-[13.5px]">
            <strong>{cam.name}</strong> <span className="text-ash">({cam.room})</span> is connected to this lecture and marks
            students it recognises with confidence. Uncertain matches go to the review queue.
          </p>
          {preview && preview !== "loading" && preview.src ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={preview.src} alt={`What ${cam.name} sees`} className="w-full rounded-[var(--radius)] border border-rule" />
          ) : null}
          {preview && preview !== "loading" && preview.error ? <Banner bad>{preview.error}</Banner> : null}
          <div className="flex flex-wrap gap-2">
            <Button onClick={look} busy={preview === "loading"}>{preview && preview !== "loading" && preview.src ? "Refresh view" : "Check the view"}</Button>
            <Button onClick={disconnect} busy={busy}>Disconnect</Button>
          </div>
        </div>
      ) : state.available.length === 0 ? (
        <p className="m-0 text-[13.5px] text-ash">
          {state.tablet
            ? `This tablet (${state.tablet.name}) has no cameras assigned. Assign them under Tablets.`
            : "No camera you may use is registered. An administrator adds cameras and assigns them to your workspace."}{" "}
          Meanwhile, use the tablet photo.
        </p>
      ) : !live ? (
        <p className="m-0 text-[13.5px] text-ash">Start the lecture to connect a camera.</p>
      ) : (
        <div className="grid gap-3">
          <p className="m-0 text-[13.5px] text-ash">
            {roomCam
              ? `${roomCam.name} in ${roomCam.room} is already watching this room. Connect another camera only if it covers the class better.`
              : "Pick a camera that can see the class. It marks recognised students for this lecture until it ends."}
          </p>
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-[220px] flex-1">
              <SelectField label="Camera" value={choice} onChange={(e) => setChoice(e.target.value)}>
                {state.available.map((c) => (
                  <option key={c.id} value={c.id}>{c.name} · {c.room}{c.running ? " · on" : ""}</option>
                ))}
              </SelectField>
            </div>
            <Button variant="primary" onClick={connect} busy={busy} disabled={!choice}>Connect camera</Button>
          </div>
        </div>
      )}
    </Card>
  );
}

/* ---------------------------------------------------------------- tablet photo */

type Face = {
  box: [number, number, number, number] | null;
  verdict: "match" | "maybe" | "duplicate" | "unclear" | "unknown";
  score?: number | null; user_id?: number; name?: string; roll_number?: string | null;
  photo_url?: string | null; already?: string | null;
};
type Analysis = { faces: Face[]; roster_size: number; enrolled: number; counts: Record<string, number> };
type Shot = { url: string; faces: Face[] };
type Candidate = { user_id: number; name: string; roll: string | null; score: number; verdict: Face["verdict"]; photo_url: string | null; already: string | null };

const BOX_COLOR: Record<Face["verdict"], string> = {
  match: "var(--verdant)", maybe: "var(--amber)", duplicate: "var(--amber)", unclear: "var(--ash)", unknown: "var(--oxide)",
};

/** Shrink to at most `max` px on the long side before upload: faster, and plenty for detection. */
async function downscale(file: Blob, max = 2400): Promise<Blob> {
  const bitmap = await createImageBitmap(file).catch(() => null);
  if (!bitmap) return file;
  const scale = Math.min(1, max / Math.max(bitmap.width, bitmap.height));
  if (scale === 1 && file.size < 6_000_000) return file;
  const c = document.createElement("canvas");
  c.width = Math.round(bitmap.width * scale);
  c.height = Math.round(bitmap.height * scale);
  c.getContext("2d")?.drawImage(bitmap, 0, 0, c.width, c.height);
  return new Promise((res) => c.toBlob((b) => res(b ?? file), "image/jpeg", 0.9));
}

export function TabletPhoto({ sessionId, live, onMarked }: { sessionId: number; live: boolean; onMarked: () => void }) {
  const { toast } = useUi();
  const cam = useCamera({ facing: "environment", width: 1920, height: 1080 });
  const { start: camStart, stop: camStop } = cam;
  const [viewfinder, setViewfinder] = useState(false);
  const [busy, setBusy] = useState(false);
  const [shots, setShots] = useState<Shot[]>([]);
  const [info, setInfo] = useState<{ roster: number; enrolled: number } | null>(null);
  const [ticked, setTicked] = useState<Set<number>>(new Set());
  const fileRef = useRef<HTMLInputElement>(null);
  const gate = useDeviceGate(sessionId);

  useEffect(() => {
    if (viewfinder) camStart();
    else camStop();
  }, [viewfinder, camStart, camStop]);
  useEffect(() => () => shots.forEach((s) => URL.revokeObjectURL(s.url)), [shots]);

  // Best evidence per student across all photos taken.
  const candidates = useMemo(() => {
    const best = new Map<number, Candidate>();
    for (const shot of shots) {
      for (const f of shot.faces) {
        if (f.user_id == null || f.score == null) continue;
        const prev = best.get(f.user_id);
        const rank = (v: Face["verdict"]) => (v === "match" ? 2 : 1);
        if (!prev || rank(f.verdict) > rank(prev.verdict) || (rank(f.verdict) === rank(prev.verdict) && f.score > prev.score)) {
          best.set(f.user_id, { user_id: f.user_id, name: f.name ?? "Student", roll: f.roll_number ?? null, score: f.score,
                                verdict: f.verdict, photo_url: f.photo_url ?? null, already: f.already ?? null });
        }
      }
    }
    return [...best.values()].sort((a, b) => (a.roll ?? a.name).localeCompare(b.roll ?? b.name));
  }, [shots]);
  const others = shots.flatMap((s) => s.faces).filter((f) => f.user_id == null);

  async function analyse(blob: Blob) {
    setBusy(true);
    try {
      const small = await downscale(blob);
      const fd = new FormData();
      fd.append("photo", small, "class.jpg");
      const r = await api.upload<Analysis>(`/api/sessions/${sessionId}/class-photo`, fd);
      setShots((prev) => [...prev, { url: URL.createObjectURL(small), faces: r.faces }]);
      setInfo({ roster: r.roster_size, enrolled: r.enrolled });
      // Confident matches start ticked; "maybe" and duplicates wait for the teacher.
      setTicked((t) => {
        const next = new Set(t);
        r.faces.forEach((f) => { if (f.verdict === "match" && f.user_id != null && !f.already) next.add(f.user_id); });
        return next;
      });
      const found = r.faces.length;
      toast(found ? `${found} face(s) found, ${r.counts.match ?? 0} recognised.` : "No faces found. Step back so the class fills the frame, in good light.",
            found ? "ok" : "bad");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not analyse the photo.", "bad");
    } finally {
      setBusy(false);
    }
  }

  async function snap() {
    const blob = await cam.capture();
    if (blob) await analyse(blob);
  }

  async function confirmMarks() {
    const ids = [...ticked];
    if (!ids.length) return;
    setBusy(true);
    try {
      const scores = Object.fromEntries(candidates.filter((c) => ticked.has(c.user_id)).map((c) => [c.user_id, c.score]));
      const r = await api.post<{ marked: number; already: number; status: string }>(
        `/api/sessions/${sessionId}/class-photo/confirm`, { user_ids: ids, scores });
      toast(`${r.marked} student(s) marked ${r.status}${r.already ? ` · ${r.already} were already marked` : ""}.`);
      setShots([]);
      setTicked(new Set());
      setViewfinder(false);
      onMarked();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not mark attendance.", "bad");
    } finally {
      setBusy(false);
    }
  }

  const toggle = (id: number) => setTicked((t) => {
    const next = new Set(t);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  });

  return (
    <Card>
      <CardHeader title="Tablet photo" meta={info ? `${info.enrolled} of ${info.roster} students have an approved face` : "photograph the class"} />
      {!live ? (
        <p className="m-0 text-[13.5px] text-ash">Start the lecture to take attendance from a photo.</p>
      ) : gate && !gate.allowed ? (
        <TabletNeeded reason={gate.reason} />
      ) : (
        <div className="grid gap-3">
          <p className="m-0 text-[13.5px] text-ash">
            Stand at the front and photograph the class — two or three photos if the room is large. Faces should be clear
            and not too small. Recognised students are ticked for you; check the list, then confirm. Photos are not saved.
          </p>

          {viewfinder ? (
            <div className="grid gap-2">
              {cam.failure ? <Banner bad><CameraHelp reason={cam.failure} /></Banner> : null}
              <video ref={cam.video} muted playsInline className="w-full rounded-[var(--radius)] border border-rule bg-black" style={{ maxHeight: 420, objectFit: "contain" }} />
              <div className="flex flex-wrap gap-2">
                <Button variant="primary" onClick={snap} busy={busy} disabled={!cam.ready}>Take photo</Button>
                <Button onClick={() => setViewfinder(false)}>Close camera</Button>
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" onClick={() => setViewfinder(true)} busy={busy}>Open camera</Button>
              <Button onClick={() => fileRef.current?.click()} busy={busy}>Use the tablet&apos;s camera app / a photo</Button>
              <input
                ref={fileRef} type="file" accept="image/*" capture="environment" className="hidden"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  e.target.value = "";
                  if (f) analyse(f);
                }}
              />
            </div>
          )}

          {info && info.enrolled === 0 ? (
            <Banner>
              <strong className="label mb-0.5 block">No faces to match yet</strong>
              None of the {info.roster} students in this class has an approved face, so nobody can be recognised.
              Ask them to enrol once under <em>Face check</em> in the student portal (you approve it under Approvals),
              and mark today&apos;s class by hand in the list below.
            </Banner>
          ) : null}

          {shots.length ? (
            <div className={`grid gap-2 ${shots.length > 1 ? "md:grid-cols-2" : ""}`}>
              {shots.map((s, i) => (
                <figure key={s.url} className="relative m-0 overflow-hidden rounded-[var(--radius)] border border-rule">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={s.url} alt={`Class photo ${i + 1}`} className="block w-full" />
                  {s.faces.map((f, j) => f.box ? (
                    <span key={j} className="absolute rounded-[var(--radius-sm)]" title={f.name ?? f.verdict}
                          style={{ left: `${f.box[0] * 100}%`, top: `${f.box[1] * 100}%`, width: `${(f.box[2] - f.box[0]) * 100}%`,
                                   height: `${(f.box[3] - f.box[1]) * 100}%`, border: `2px solid ${BOX_COLOR[f.verdict]}` }} />
                  ) : null)}
                  <figcaption className="px-2 py-1 font-mono text-[11px] text-ash">
                    photo {i + 1} · {s.faces.length} face(s) · {s.faces.filter((f) => f.verdict === "match").length} recognised
                  </figcaption>
                </figure>
              ))}
            </div>
          ) : null}

          {candidates.length ? (
            <div>
              <div className="mb-1 flex items-baseline justify-between gap-2">
                <span className="label">In the photo{candidates.length > 1 ? "s" : ""}</span>
                <span className="text-[12px] text-ash">green = recognised · amber = check before ticking</span>
              </div>
              <ul className="m-0 grid list-none gap-1.5 p-0 sm:grid-cols-2">
                {candidates.map((c) => (
                  <li key={c.user_id}>
                    <label className="flex cursor-pointer items-center gap-2.5 rounded-[var(--radius)] border border-rule px-2.5 py-2"
                           style={{ borderLeft: `4px solid ${BOX_COLOR[c.verdict]}`, opacity: c.already ? 0.6 : 1 }}>
                      <input type="checkbox" className="h-5 w-5" checked={ticked.has(c.user_id)} disabled={!!c.already}
                             onChange={() => toggle(c.user_id)} />
                      <span className="h-9 w-9 shrink-0 overflow-hidden rounded-full border border-rule bg-paper">
                        {c.photo_url ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img src={`/api/backend${c.photo_url}`} alt="" className="h-full w-full object-cover" />
                        ) : null}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[14px] font-semibold">{c.name}</span>
                        <span className="font-mono text-[11px] text-ash">
                          {c.roll} · {(c.score * 100).toFixed(0)}% match
                          {c.verdict !== "match" ? " · check" : ""}{c.already ? ` · already ${c.already.replace("_", " ")}` : ""}
                        </span>
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {others.length ? (
            <p className="m-0 text-[12.5px] text-ash">
              {others.filter((f) => f.verdict === "unknown").length} face(s) matched nobody on this class list
              {others.some((f) => f.verdict === "unclear") ? `, ${others.filter((f) => f.verdict === "unclear").length} too blurred or turned away` : ""}.
              Mark those students by hand in the class list.
            </p>
          ) : null}

          {shots.length ? (
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" onClick={confirmMarks} busy={busy} disabled={!ticked.size}>
                Mark {ticked.size} student{ticked.size === 1 ? "" : "s"} as here
              </Button>
              <Button onClick={() => { setShots([]); setTicked(new Set()); }}>Discard photos</Button>
            </div>
          ) : null}
        </div>
      )}
    </Card>
  );
}
