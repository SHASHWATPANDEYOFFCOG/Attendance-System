"use client";

/**
 * CCTV cameras: health at a glance (online / offline, frame rate, last heartbeat), and for
 * administrators add / edit / test / start / stop. Credentials go in their own fields, are
 * stored encrypted, and are never shown again — leaving the password empty keeps the old one.
 */
import { useCallback, useEffect, useState } from "react";

import { api, ApiFailure } from "@/lib/client";
import { Page, PageHeader } from "@/components/shell";
import { Banner, Card, Pill } from "@/components/ui";
import { Button, Checkbox, FormError, SelectField, TextField } from "@/components/forms";
import { EmptyState, PageError, PageLoading } from "@/components/states";
import { useUi } from "@/components/toast";

type Cam = {
  id: number; name: string; room: string; source: string; mode: string; status: string;
  status_detail: string | null; last_heartbeat: string | null; measured_fps: number; running: boolean;
  enabled: boolean; auto_start: boolean; has_credentials: boolean;
};
type Test = { ok: boolean; ms: number; width?: number; height?: number; preview?: string; error?: string };

function health(c: Cam): { tone: "ok" | "warn" | "bad" | "neutral"; label: string } {
  if (!c.enabled) return { tone: "neutral", label: "disabled" };
  if (c.status === "running") return { tone: "ok", label: "online" };
  if (c.status === "offline") return { tone: "bad", label: "offline" };
  if (c.status === "error") return { tone: "bad", label: "error" };
  if (c.status === "starting") return { tone: "warn", label: "starting" };
  return { tone: "neutral", label: "idle" };
}

export default function CamerasPage() {
  const { toast, confirm } = useUi();
  const [rows, setRows] = useState<Cam[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [admin, setAdmin] = useState(false);
  const [rooms, setRooms] = useState<{ name: string }[]>([]);
  const [editing, setEditing] = useState<Cam | "new" | null>(null);
  const [tests, setTests] = useState<Record<number, Test | "running">>({});

  const load = useCallback(async () => {
    try {
      setRows(await api.get<Cam[]>("/api/cameras"));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load cameras.");
    }
  }, []);
  useEffect(() => {
    load();
    const t = setInterval(load, 10000);
    api.get<{ role: string }>("/api/me").then((m) => setAdmin(m.role === "admin" || m.role === "super_admin")).catch(() => {});
    api.get<{ name: string }[]>("/api/rooms").then(setRooms).catch(() => {});
    return () => clearInterval(t);
  }, [load]);

  async function test(c: Cam) {
    setTests((t) => ({ ...t, [c.id]: "running" }));
    try {
      const r = await api.post<Test>(`/api/cameras/${c.id}/test`);
      setTests((t) => ({ ...t, [c.id]: r }));
    } catch (e) {
      setTests((t) => ({ ...t, [c.id]: { ok: false, ms: 0, error: e instanceof Error ? e.message : "Test failed." } }));
    }
  }

  async function startStop(c: Cam) {
    try {
      await api.post(`/api/cameras/${c.id}/${c.running ? "stop" : "start"}`);
      toast(c.running ? "Camera stopped." : "Camera starting…");
      load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Action failed.", "bad");
    }
  }

  async function remove(c: Cam) {
    if (!(await confirm({ title: `Delete camera ${c.name}?`, danger: true, confirmLabel: "Delete" }))) return;
    try {
      await api.del(`/api/cameras/${c.id}`);
      toast("Camera deleted.");
      load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not delete.", "bad");
    }
  }

  return (
    <Page wide>
      <PageHeader title="CCTV cameras" subtitle="Cameras start on their own during lectures in their room"
                  actions={admin && !editing ? <Button variant="primary" onClick={() => setEditing("new")}>+ Add camera</Button> : null} />
      <Banner>
        Video is analysed in memory and never recorded. Only students of the lecture running in the room are looked for;
        unknown faces are ignored and not stored. Near matches go to the review queue with a face crop that is deleted after the
        retention period.
      </Banner>
      {editing ? <CameraForm cam={editing === "new" ? null : editing} rooms={rooms} onDone={() => { setEditing(null); load(); }} onCancel={() => setEditing(null)} /> : null}
      {error ? <PageError message={error} retry={load} /> : !rows ? <PageLoading /> : !rows.length ? (
        <EmptyState title="No cameras yet">{admin ? "Add one with its RTSP address. See the README for how to find it." : "An administrator adds cameras."}</EmptyState>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {rows.map((c) => {
            const h = health(c);
            const t = tests[c.id];
            return (
              <Card key={c.id}>
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="text-[16px] font-semibold">{c.name}</div>
                    <div className="text-[13px] text-ash">Room {c.room}{c.auto_start ? " · auto" : " · manual"}</div>
                    <div className="truncate font-mono text-[11.5px] text-ash">{c.source}{c.has_credentials ? " · credentials stored" : ""}</div>
                  </div>
                  <Pill tone={h.tone}>{h.label}</Pill>
                </div>
                <div className="mt-2 font-mono text-[12px] text-ash">
                  {c.running ? `${c.measured_fps.toFixed(1)} fps · ` : ""}
                  {c.last_heartbeat ? `last seen ${new Date(c.last_heartbeat).toLocaleTimeString()}` : "never connected"}
                  {c.status_detail ? <div className="truncate">{c.status_detail}</div> : null}
                </div>
                {t && t !== "running" ? (
                  t.ok ? (
                    <figure className="m-0 mt-3">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={t.preview} alt={`Live frame from ${c.name}`} className="w-full rounded-[3px] border border-rule" />
                      <figcaption className="font-mono text-[11.5px] text-ash">connected in {t.ms} ms · {t.width}×{t.height} · not stored</figcaption>
                    </figure>
                  ) : <Banner bad>{t.error}</Banner>
                ) : null}
                {admin ? (
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Button busy={t === "running"} onClick={() => test(c)}>Test connection</Button>
                    <Button onClick={() => startStop(c)} disabled={!c.enabled}>{c.running ? "Stop" : "Start now"}</Button>
                    <Button variant="ghost" onClick={() => setEditing(c)}>Edit</Button>
                    <Button variant="ghost" onClick={() => remove(c)}>Delete</Button>
                  </div>
                ) : null}
              </Card>
            );
          })}
        </div>
      )}
    </Page>
  );
}

function CameraForm({ cam, rooms, onDone, onCancel }: { cam: Cam | null; rooms: { name: string }[]; onDone: () => void; onCancel: () => void }) {
  const { toast } = useUi();
  const [f, setF] = useState({ name: cam?.name ?? "", room: cam?.room ?? "", source: cam?.source ?? "", username: "", password: "" });
  const [autoStart, setAutoStart] = useState(cam?.auto_start ?? true);
  const [enabled, setEnabled] = useState(cam?.enabled ?? true);
  const [clear, setClear] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!f.name.trim() || !f.room.trim() || !f.source.trim()) return setError("Name, room and stream address are required.");
    setBusy(true);
    setError(null);
    const body: Record<string, unknown> = { name: f.name, room: f.room, auto_start: autoStart, enabled };
    if (!cam || f.source !== cam.source) body.source = f.source;
    if (f.username) body.username = f.username;
    if (f.password) body.password = f.password;
    if (clear) body.clear_credentials = true;
    try {
      if (cam) await api.patch(`/api/cameras/${cam.id}`, body);
      else await api.post("/api/cameras", { ...body, source: f.source });
      toast(cam ? "Camera saved." : "Camera added. Use Test connection to check it.");
      onDone();
    } catch (err) {
      setError(err instanceof ApiFailure || err instanceof Error ? err.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mb-4">
      <h2 className="display m-0 mb-3 text-[15px] text-ash">{cam ? `Edit ${cam.name}` : "Add camera"}</h2>
      <FormError>{error}</FormError>
      <form onSubmit={submit} noValidate className="grid gap-3 sm:grid-cols-2">
        <TextField label="Name" required value={f.name} onChange={set("name")} placeholder="LH-101 front" />
        {rooms.length ? (
          <SelectField label="Room" required value={f.room} onChange={set("room")}>
            <option value="">Select…</option>
            {rooms.map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}
          </SelectField>
        ) : <TextField label="Room" required value={f.room} onChange={set("room")} />}
        <TextField label="Stream address" required value={f.source} onChange={set("source")} className="font-mono"
                   placeholder="rtsp://192.168.1.64:554/Streaming/Channels/101"
                   hint="RTSP or HTTP URL without the username/password, or 0 for a webcam on the server." />
        <div className="grid gap-3 sm:grid-cols-2">
          <TextField label="Username" autoComplete="off" value={f.username} onChange={set("username")}
                     placeholder={cam?.has_credentials ? "(unchanged)" : ""} />
          <TextField label="Password" type="password" autoComplete="new-password" value={f.password} onChange={set("password")}
                     placeholder={cam?.has_credentials ? "(unchanged)" : ""} />
        </div>
        <div className="grid gap-2 sm:col-span-2">
          <Checkbox label="Start automatically during lectures in this room" checked={autoStart} onChange={(e) => setAutoStart(e.target.checked)} />
          <Checkbox label="Enabled" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          {cam?.has_credentials ? <Checkbox label="Remove stored credentials" checked={clear} onChange={(e) => setClear(e.target.checked)} /> : null}
        </div>
        <div className="flex gap-2 sm:col-span-2">
          <Button type="submit" variant="primary" busy={busy}>{cam ? "Save" : "Add camera"}</Button>
          <Button onClick={onCancel}>Cancel</Button>
        </div>
      </form>
    </Card>
  );
}
