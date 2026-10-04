"use client";

/**
 * CCTV cameras.
 *
 * Administrators add, edit, enable / disable, remove and test cameras and put each one in a
 * workspace. Authorities see only the cameras of their own workspaces and can test, start and
 * stop them. Credentials go in their own fields, are stored encrypted and never shown again;
 * leaving the password empty when editing keeps the old one.
 */
import { useCallback, useEffect, useState } from "react";

import Link from "next/link";

import { api, ApiFailure } from "@/lib/client";
import { useMe } from "@/lib/use-me";
import { Page, PageHeader } from "@/components/shell";
import { Banner, Card, CardHeader, Pill } from "@/components/ui";
import { Button, Checkbox, FormError, SelectField, TextArea, TextField } from "@/components/forms";
import { EmptyState, PageError, PageLoading } from "@/components/states";
import { useUi } from "@/components/toast";

type Cam = {
  id: number; name: string; code: string | null; camera_type: string; description: string | null;
  room: string; source: string; mode: string; status: string; state: "online" | "offline" | "connecting" | "idle" | "disabled";
  status_detail: string | null; last_heartbeat: string | null; measured_fps: number; running: boolean;
  enabled: boolean; auto_start: boolean; has_credentials: boolean; workspace_id: number | null; workspace: string | null;
};
type Test = { ok: boolean; ms: number; width?: number; height?: number; preview?: string; error?: string };
type Ws = { id: number; name: string };

const TYPES: [string, string][] = [
  ["rtsp", "IP camera (RTSP)"], ["onvif", "ONVIF camera (RTSP address)"], ["http", "HTTP / MJPEG stream"],
  ["usb", "USB webcam on the server"], ["file", "Video file (testing)"],
];
const TYPE_LABEL = Object.fromEntries(TYPES);
const STATE: Record<Cam["state"], { tone: "ok" | "warn" | "bad" | "neutral"; label: string }> = {
  online: { tone: "ok", label: "online" }, offline: { tone: "bad", label: "offline" },
  connecting: { tone: "warn", label: "connecting" }, idle: { tone: "neutral", label: "idle" },
  disabled: { tone: "neutral", label: "disabled" },
};

export default function CamerasPage() {
  const { toast, confirm } = useUi();
  const { isAdministrator } = useMe();
  const [rows, setRows] = useState<Cam[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rooms, setRooms] = useState<{ name: string }[]>([]);
  const [spaces, setSpaces] = useState<Ws[]>([]);
  const [editing, setEditing] = useState<Cam | "new" | null>(null);
  const [open, setOpen] = useState<number | null>(null);
  const [tests, setTests] = useState<Record<number, Test | "running">>({});
  const [q, setQ] = useState("");

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
    api.get<{ name: string }[]>("/api/rooms").then(setRooms).catch(() => {});
    api.get<Ws[]>("/api/workspaces").then(setSpaces).catch(() => {});
    return () => clearInterval(t);
  }, [load]);

  async function test(c: Cam) {
    setOpen(c.id);
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
      toast(c.running ? `${c.name} stopped.` : `${c.name} starting…`);
      load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Action failed.", "bad");
    }
  }

  async function setEnabled(c: Cam, enabled: boolean) {
    try {
      await api.patch(`/api/cameras/${c.id}`, { enabled });
      if (!enabled && c.running) await api.post(`/api/cameras/${c.id}/stop`).catch(() => {});
      toast(enabled ? `${c.name} enabled.` : `${c.name} disabled. It will not start until enabled again.`);
      load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Action failed.", "bad");
    }
  }

  async function remove(c: Cam) {
    if (!(await confirm({ title: `Remove camera ${c.name}?`, body: "Lectures connected to it are disconnected. Attendance already recorded is kept.", danger: true, confirmLabel: "Remove" }))) return;
    try {
      await api.del(`/api/cameras/${c.id}`);
      toast("Camera removed.");
      load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not remove.", "bad");
    }
  }

  const shown = (rows ?? []).filter((c) => !q || `${c.name} ${c.code} ${c.room} ${c.workspace}`.toLowerCase().includes(q.toLowerCase()));

  return (
    <Page wide>
      <PageHeader title="CCTV cameras" subtitle={isAdministrator ? "All cameras · add, edit and assign them to workspaces" : "Cameras of your workspaces"}
                  actions={isAdministrator && !editing ? <Button variant="primary" onClick={() => setEditing("new")}>+ Add camera</Button> : null} />

      {isAdministrator ? (
        <details className="mb-4 rounded-[var(--radius)] border border-rule bg-card shadow-card" open={rows?.length === 0}>
          <summary className="cursor-pointer px-4 py-3"><span className="label text-[12px]">How to add a camera</span></summary>
          <ol className="m-0 grid list-decimal gap-1.5 border-t border-rule py-3 pl-9 pr-4 text-[13.5px]">
            <li>Create a <Link href="/staff/workspaces" className="text-ink underline">workspace</Link> (e.g. &quot;CSE Block&quot;) and add the authorities who should use its cameras.</li>
            <li>Find the camera&apos;s stream address: the camera&apos;s label or manual, or its web page / NVR (&quot;Network → RTSP&quot;). Common forms: Hikvision <code>rtsp://IP:554/Streams/Channels/102</code>, Dahua / CP Plus <code>rtsp://IP:554/cam/realmonitor?channel=1&amp;subtype=1</code>. Check it opens in VLC first.</li>
            <li>Press <strong>Add camera</strong>: name, room, the address <em>without</em> username and password, the login in its own fields, and the workspace.</li>
            <li>Press <strong>Test connection</strong>: you should see a frame from the camera.</li>
            <li>Leave &quot;Start automatically&quot; on: the camera then watches lectures in its room. Teachers can also connect it to any lecture from the lecture page.</li>
          </ol>
        </details>
      ) : null}

      <Banner>
        Video is analysed in memory and never recorded. Only students of the lecture being watched are looked for;
        unknown faces are ignored and not stored. Near matches go to the review queue with a face crop that is deleted after the retention period.
      </Banner>

      {editing ? (
        <CameraForm cam={editing === "new" ? null : editing} rooms={rooms} spaces={spaces}
                    onDone={() => { setEditing(null); load(); }} onCancel={() => setEditing(null)} />
      ) : null}

      {rows && rows.length > 4 ? (
        <div className="mb-3 max-w-[360px]"><TextField label="Search cameras" value={q} onChange={(e) => setQ(e.target.value)} placeholder="name, ID, room or workspace" /></div>
      ) : null}

      {error ? <PageError message={error} retry={load} /> : !rows ? <PageLoading /> : !rows.length ? (
        <EmptyState title="No cameras yet">
          {isAdministrator ? "Add one with Add camera; the steps above explain how to find its address." : "No camera is assigned to your workspaces yet. An administrator assigns cameras to workspaces."}
        </EmptyState>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {shown.map((c) => {
            const h = STATE[c.state] ?? STATE.idle;
            const t = tests[c.id];
            const expanded = open === c.id;
            return (
              <Card key={c.id}>
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="text-[16px] font-semibold">{c.name}</div>
                    <div className="font-mono text-[12px] text-ash">{c.code ?? "—"} · {TYPE_LABEL[c.camera_type] ?? c.camera_type}</div>
                    <div className="text-[13px] text-ash">Room {c.room} · {c.workspace ?? <em>no workspace (administrators only)</em>}</div>
                  </div>
                  <Pill tone={h.tone}>{h.label}</Pill>
                </div>
                <div className="mt-2 font-mono text-[12px] text-ash">
                  {c.running ? `${c.measured_fps.toFixed(1)} fps · ` : ""}
                  {c.last_heartbeat ? `last seen ${new Date(c.last_heartbeat).toLocaleTimeString()}` : "never connected"}
                  {c.status_detail ? <div className="truncate">{c.status_detail}</div> : null}
                </div>
                {expanded ? (
                  <dl className="m-0 mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 border-t border-rule pt-2 text-[13px]">
                    <dt className="label pt-[2px] text-[11px]">Address</dt><dd className="m-0 break-all font-mono text-[12px]">{c.source}</dd>
                    <dt className="label pt-[2px] text-[11px]">Login</dt><dd className="m-0">{c.has_credentials ? "stored, encrypted" : "none"}</dd>
                    <dt className="label pt-[2px] text-[11px]">Starts</dt><dd className="m-0">{c.auto_start ? "automatically during lectures in its room" : "only when started or connected by hand"}</dd>
                    {c.description ? <><dt className="label pt-[2px] text-[11px]">Notes</dt><dd className="m-0">{c.description}</dd></> : null}
                  </dl>
                ) : null}
                {t && t !== "running" ? (
                  t.ok ? (
                    <figure className="m-0 mt-3">
                      {/* eslint-disable-next-line @next/next/no-img-element */}
                      <img src={t.preview} alt={`Live frame from ${c.name}`} className="w-full rounded-[var(--radius)] border border-rule" />
                      <figcaption className="font-mono text-[11.5px] text-ash">connected in {t.ms} ms · {t.width}×{t.height} · not stored</figcaption>
                    </figure>
                  ) : <div className="mt-3"><Banner bad>{t.error}</Banner></div>
                ) : null}
                <div className="mt-3 flex flex-wrap gap-1.5">
                  <Button onClick={() => setOpen(expanded ? null : c.id)}>{expanded ? "Hide details" : "View"}</Button>
                  <Button busy={t === "running"} onClick={() => test(c)}>Test connection</Button>
                  <Button onClick={() => startStop(c)} disabled={!c.enabled}>{c.running ? "Stop" : "Start now"}</Button>
                  {isAdministrator ? (
                    <>
                      <Button onClick={() => setEditing(c)}>Edit</Button>
                      <Button onClick={() => setEnabled(c, !c.enabled)}>{c.enabled ? "Disable" : "Enable"}</Button>
                      <Button variant="ghost" onClick={() => remove(c)}>Remove</Button>
                    </>
                  ) : null}
                </div>
              </Card>
            );
          })}
        </div>
      )}
    </Page>
  );
}

function CameraForm({ cam, rooms, spaces, onDone, onCancel }: {
  cam: Cam | null; rooms: { name: string }[]; spaces: Ws[]; onDone: () => void; onCancel: () => void;
}) {
  const { toast } = useUi();
  const [f, setF] = useState({
    name: cam?.name ?? "", code: cam?.code ?? "", camera_type: cam?.camera_type ?? "rtsp", room: cam?.room ?? "",
    source: cam?.source ?? "", username: "", password: "", description: cam?.description ?? "",
    workspace_id: cam?.workspace_id ? String(cam.workspace_id) : "",
  });
  const [autoStart, setAutoStart] = useState(cam?.auto_start ?? true);
  const [enabled, setEnabled] = useState(cam?.enabled ?? true);
  const [clear, setClear] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const missing: Record<string, string> = {};
    if (!f.name.trim()) missing.name = "Give the camera a name.";
    if (!f.room.trim()) missing.room = "Choose the room it watches.";
    if (!f.source.trim()) missing.source = "Enter the stream address.";
    if (/^[a-z]+:\/\/[^/@\s]+:[^/@\s]+@/i.test(f.source)) missing.source = "Remove the username and password from the address; use the fields below.";
    setErrors(missing);
    if (Object.keys(missing).length) return;
    setBusy(true);
    setError(null);
    const body: Record<string, unknown> = {
      name: f.name, room: f.room, auto_start: autoStart, enabled, camera_type: f.camera_type,
      description: f.description, code: f.code || undefined,
    };
    if (f.workspace_id) body.workspace_id = Number(f.workspace_id);
    else if (cam?.workspace_id) body.clear_workspace = true;
    if (!cam || f.source !== cam.source) body.source = f.source;
    if (f.username) body.username = f.username;
    if (f.password) body.password = f.password;
    if (clear) body.clear_credentials = true;
    try {
      if (cam) await api.patch(`/api/cameras/${cam.id}`, body);
      else await api.post("/api/cameras", { ...body, source: f.source });
      toast(cam ? "Camera saved." : "Camera added. Press Test connection to check it.");
      onDone();
    } catch (err) {
      const detail = err instanceof ApiFailure ? err.detail : undefined;
      const field = typeof detail?.field === "string" ? detail.field : undefined;
      const message = err instanceof Error ? err.message : "Could not save.";
      if (field) setErrors({ [field]: message });
      else setError(message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mb-4">
      <CardHeader title={cam ? `Edit ${cam.name}` : "Add camera"} />
      <FormError>{error}</FormError>
      <form onSubmit={submit} noValidate className="grid gap-3 sm:grid-cols-2">
        <TextField label="Camera name" required value={f.name} onChange={set("name")} error={errors.name} placeholder="LH-101 front" />
        <TextField label="Camera ID (optional)" value={f.code} onChange={set("code")} error={errors.code} hint="Empty: numbered automatically (CAM-0001)." />
        <SelectField label="Camera type" value={f.camera_type} onChange={set("camera_type")} error={errors.camera_type}>
          {TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
        </SelectField>
        <SelectField label="Workspace" value={f.workspace_id} onChange={set("workspace_id")} error={errors.workspace_id}
                     hint={spaces.length ? "Only this workspace's authorities can see and use the camera." : "Create a workspace first, under Workspaces."}>
          <option value="">No workspace (administrators only)</option>
          {spaces.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </SelectField>
        {rooms.length ? (
          <SelectField label="Location (room)" required value={f.room} onChange={set("room")} error={errors.room}>
            <option value="">Select…</option>
            {rooms.map((r) => <option key={r.name} value={r.name}>{r.name}</option>)}
          </SelectField>
        ) : <TextField label="Location (room)" required value={f.room} onChange={set("room")} error={errors.room} hint="Add rooms under Academic setup → Rooms to pick from a list." />}
        <TextField label="Stream address (URL / IP)" required value={f.source} onChange={set("source")} error={errors.source} className="font-mono"
                   placeholder="rtsp://192.168.1.64:554/Streams/Channels/102"
                   hint={f.camera_type === "usb" ? "The webcam number on the server, usually 0." : "Without the username and password."} />
        <TextField label="Username" autoComplete="off" value={f.username} onChange={set("username")} placeholder={cam?.has_credentials ? "(unchanged)" : ""} />
        <TextField label="Password" type="password" autoComplete="new-password" value={f.password} onChange={set("password")} placeholder={cam?.has_credentials ? "(unchanged)" : ""} />
        <div className="sm:col-span-2"><TextArea label="Description (optional)" rows={2} value={f.description} onChange={set("description")} /></div>
        <div className="grid gap-2 sm:col-span-2">
          <Checkbox label="Start automatically during lectures in this room" checked={autoStart} onChange={(e) => setAutoStart(e.target.checked)} />
          <Checkbox label="Enabled" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
          {cam?.has_credentials ? <Checkbox label="Remove stored username and password" checked={clear} onChange={(e) => setClear(e.target.checked)} /> : null}
        </div>
        <div className="flex gap-2 sm:col-span-2">
          <Button type="submit" variant="primary" busy={busy}>{cam ? "Save" : "Add camera"}</Button>
          <Button onClick={onCancel}>Cancel</Button>
        </div>
      </form>
    </Card>
  );
}
