"use client";

/**
 * Tablets: the devices allowed to take class-photo attendance and control cameras.
 *
 *   1. Register a tablet here (any device): choose its workspace and cameras. You get a one-time
 *      pairing code, valid for 15 minutes.
 *   2. On the tablet itself, sign in and enter the code under "This device".
 *   3. The tablet is now active. Disable it for a while, revoke it for good, or issue a new code
 *      to replace the device.
 */
import { useCallback, useEffect, useState } from "react";

import Link from "next/link";

import { api, ApiFailure } from "@/lib/client";
import { useMe } from "@/lib/use-me";
import { Page, PageHeader } from "@/components/shell";
import { Banner, Card, CardHeader, Pill } from "@/components/ui";
import { Button, Checkbox, FormError, SelectField, TextField } from "@/components/forms";
import { EmptyState, PageError, PageLoading } from "@/components/states";
import { useUi } from "@/components/toast";

type Cam = { id: number; name: string; code: string | null };
type Tablet = {
  id: number; code: string; name: string; status: "pending" | "active" | "disabled" | "revoked";
  workspace_id: number; workspace: string | null; owner: string | null; paired: boolean; device_info: string | null;
  paired_at: string | null; last_seen_at: string | null; pairing_pending: boolean; cameras: Cam[];
};
type Ws = { id: number; name: string; code: string; is_active: boolean; cameras: { id: number; name: string; code: string | null; room: string }[] };
type Pairing = { tablet: string; code: string; expires: string };
type ThisDevice = { paired: false } | { paired: true; usable: boolean; tablet: Tablet };

const TONE: Record<Tablet["status"], "ok" | "warn" | "neutral" | "bad"> = { active: "ok", pending: "warn", disabled: "neutral", revoked: "bad" };
const STATUS_LABEL: Record<Tablet["status"], string> = { active: "active", pending: "waiting for pairing", disabled: "disabled", revoked: "revoked" };

const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "never");

export default function TabletsPage() {
  const { toast, confirm, askReason } = useUi();
  const { isAdministrator } = useMe();
  const [rows, setRows] = useState<Tablet[] | null>(null);
  const [spaces, setSpaces] = useState<Ws[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [pairing, setPairing] = useState<Pairing | null>(null);
  const [camsFor, setCamsFor] = useState<Tablet | null>(null);

  const load = useCallback(async () => {
    try {
      const [t, w] = await Promise.all([api.get<Tablet[]>("/api/tablets"), api.get<Ws[]>("/api/workspaces")]);
      setRows(t);
      setSpaces(w.filter((x) => x.is_active));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load tablets.");
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  async function act(t: Tablet, what: "enable" | "disable" | "code" | "revoke" | "remove") {
    try {
      if (what === "enable" || what === "disable") {
        await api.patch(`/api/tablets/${t.id}`, { status: what === "enable" ? "active" : "disabled" });
        toast(what === "enable" ? `${t.name} enabled.` : `${t.name} disabled. It cannot be used until enabled again.`);
      } else if (what === "code") {
        if (t.paired && !(await confirm({ title: `New pairing code for ${t.name}?`, body: "The device currently paired stops working until the new code is entered on a device.", confirmLabel: "Issue code" }))) return;
        const r = await api.post<Tablet & { pairing_code: string; pairing_expires_at: string }>(`/api/tablets/${t.id}/pairing-code`);
        setPairing({ tablet: r.name, code: r.pairing_code, expires: r.pairing_expires_at });
      } else if (what === "revoke") {
        if (!(await confirm({ title: `Revoke ${t.name}?`, body: "The device loses access immediately. To use it again you will need a new pairing code.", confirmLabel: "Revoke", danger: true }))) return;
        await api.post(`/api/tablets/${t.id}/revoke`);
        toast(`${t.name} revoked.`);
      } else {
        if (!(await confirm({ title: `Remove ${t.name}?`, body: "It is deleted from the list and loses access.", confirmLabel: "Remove", danger: true }))) return;
        await api.del(`/api/tablets/${t.id}`);
        toast(`${t.name} removed.`);
      }
      load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Action failed.", "bad");
    }
  }

  async function rename(t: Tablet) {
    const name = (await askReason({ title: `Rename ${t.name}`, confirmLabel: "Save name",
                                    reason: { label: "New name", minLength: 2 } }))?.trim();
    if (!name || name === t.name) return;
    try {
      await api.patch(`/api/tablets/${t.id}`, { name });
      toast("Renamed.");
      load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not rename.", "bad");
    }
  }

  return (
    <Page wide>
      <PageHeader
        title="Tablets"
        subtitle="Devices allowed to take class-photo attendance and use cameras"
        actions={!adding && spaces.length ? <Button variant="primary" onClick={() => setAdding(true)}>+ Register a tablet</Button> : null}
      />

      <ThisDevicePanel onChange={load} />

      {pairing ? (
        <Card className="mb-4">
          <CardHeader title={`Pairing code for ${pairing.tablet}`} meta={`valid until ${new Date(pairing.expires).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}`} />
          <p className="m-0 font-mono text-[34px] font-semibold tracking-[0.25em]">{pairing.code.slice(0, 4)}-{pairing.code.slice(4)}</p>
          <p className="mb-0 mt-2 text-[13.5px] text-ash">
            On the tablet: open this website, sign in with your authority account, go to <strong>Tablets</strong>, and
            enter this code under <strong>This device</strong>. The code works once and expires in 15 minutes.
          </p>
          <div className="mt-3"><Button onClick={() => setPairing(null)}>Done</Button></div>
        </Card>
      ) : null}

      {adding ? (
        <RegisterForm spaces={spaces} onCancel={() => setAdding(false)}
                      onDone={(p) => { setAdding(false); setPairing(p); load(); }} />
      ) : null}

      {camsFor ? (
        <CameraPicker tablet={camsFor} space={spaces.find((s) => s.id === camsFor.workspace_id)}
                      onDone={() => { setCamsFor(null); load(); }} onCancel={() => setCamsFor(null)} />
      ) : null}

      {error ? <PageError message={error} retry={load} /> : !rows ? <PageLoading /> : !spaces.length && !rows.length ? (
        <EmptyState title={isAdministrator ? "No workspaces yet" : "You are not in a workspace yet"}>
          Tablets belong to a workspace.{" "}
          {isAdministrator ? "Create one under " : "Ask an administrator to add you to one under "}
          <Link href="/staff/workspaces" className="text-ink underline">Workspaces</Link>.
        </EmptyState>
      ) : !rows.length ? (
        <EmptyState title="No tablets registered">Register the tablets you will use in class.</EmptyState>
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {rows.map((t) => (
            <Card key={t.id}>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <strong className="text-[15px]">{t.name}</strong>
                  <div className="font-mono text-[12px] text-ash">{t.code} · {t.workspace}</div>
                </div>
                <Pill tone={TONE[t.status]}>{STATUS_LABEL[t.status]}</Pill>
              </div>
              <dl className="m-0 mt-2.5 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-0.5 text-[13px]">
                <dt className="label pt-[2px] text-[11px]">Cameras</dt>
                <dd className="m-0">{t.cameras.length ? t.cameras.map((c) => c.name).join(", ") : <span className="text-ash">none (photo attendance only)</span>}</dd>
                <dt className="label pt-[2px] text-[11px]">Registered by</dt><dd className="m-0">{t.owner}</dd>
                <dt className="label pt-[2px] text-[11px]">Paired</dt><dd className="m-0">{t.paired ? when(t.paired_at) : "not yet"}</dd>
                <dt className="label pt-[2px] text-[11px]">Last used</dt><dd className="m-0">{when(t.last_seen_at)}</dd>
              </dl>
              <div className="mt-3 flex flex-wrap gap-1.5">
                <Button onClick={() => setCamsFor(t)} disabled={t.status === "revoked"}>Cameras</Button>
                <Button onClick={() => rename(t)}>Rename</Button>
                {t.status === "active" ? <Button onClick={() => act(t, "disable")}>Disable</Button> : null}
                {t.status === "disabled" ? <Button onClick={() => act(t, "enable")}>Enable</Button> : null}
                <Button onClick={() => act(t, "code")}>{t.paired ? "Re-pair" : "Pairing code"}</Button>
                {t.status !== "revoked" ? <Button variant="ghost" onClick={() => act(t, "revoke")}>Revoke</Button> : null}
                <Button variant="ghost" onClick={() => act(t, "remove")}>Remove</Button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </Page>
  );
}

function ThisDevicePanel({ onChange }: { onChange: () => void }) {
  const { toast, confirm } = useUi();
  const [state, setState] = useState<ThisDevice | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api.get<ThisDevice>("/api/tablets/this-device").then(setState).catch(() => setState({ paired: false }));
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  async function pair(e: React.FormEvent) {
    e.preventDefault();
    if (code.replace(/[\s-]/g, "").length !== 8) return setError("Enter the 8-character pairing code.");
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/device/pair", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pairing_code: code }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) {
        const d = body?.detail;
        throw new Error(typeof d === "string" ? d : d?.message ?? "Pairing failed.");
      }
      toast(`This device is now ${body.tablet?.name ?? "a registered tablet"}.`);
      setCode("");
      load();
      onChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Pairing failed.");
    } finally {
      setBusy(false);
    }
  }

  async function forget() {
    if (!(await confirm({ title: "Forget this device?", body: "This browser stops acting as the tablet. The tablet stays registered; pair it again with a new code.", confirmLabel: "Forget" }))) return;
    await fetch("/api/device/pair", { method: "DELETE" });
    toast("This device is no longer paired.");
    load();
  }

  return (
    <Card className="mb-4">
      <CardHeader title="This device" meta={state?.paired ? <Pill tone={state.usable ? "ok" : "warn"}>{state.usable ? "registered tablet" : "not yours"}</Pill> : undefined} />
      {!state ? <p className="m-0 text-[13.5px] text-ash">Checking…</p> : state.paired ? (
        <div className="grid gap-2">
          <p className="m-0 text-[14px]">
            This browser is <strong>{state.tablet.name}</strong> ({state.tablet.code}) in {state.tablet.workspace}.
            {state.tablet.cameras.length ? ` It may use: ${state.tablet.cameras.map((c) => c.name).join(", ")}.` : " No cameras assigned; it can take class photos."}
          </p>
          {!state.usable ? <Banner bad>You are not a member of this tablet&apos;s workspace, so you cannot use it.</Banner> : null}
          <div><Button onClick={forget}>Forget this device</Button></div>
        </div>
      ) : (
        <form onSubmit={pair} noValidate className="grid gap-3">
          <p className="m-0 text-[13.5px] text-ash">
            This browser is not a registered tablet. If this is the tablet you will use in class, enter the pairing code
            shown when the tablet was registered (or issue a new one from the list below).
          </p>
          <div className="flex flex-wrap items-end gap-2">
            <div className="w-[220px]">
              <TextField label="Pairing code" value={code} onChange={(e) => { setCode(e.target.value.toUpperCase()); setError(null); }}
                         autoComplete="one-time-code" maxLength={9} className="font-mono tracking-[0.2em]" error={error} />
            </div>
            <Button type="submit" variant="primary" busy={busy}>Pair this device</Button>
          </div>
        </form>
      )}
    </Card>
  );
}

function RegisterForm({ spaces, onDone, onCancel }: { spaces: Ws[]; onDone: (p: Pairing) => void; onCancel: () => void }) {
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [wsId, setWsId] = useState(String(spaces[0]?.id ?? ""));
  const [cams, setCams] = useState<number[]>([]);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const space = spaces.find((s) => String(s.id) === wsId);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (name.trim().length < 2) return setErrors({ name: "Give the tablet a name, e.g. \"Room 101 tablet\"." });
    if (!wsId) return setErrors({ workspace_id: "Choose a workspace." });
    setBusy(true);
    setErrors({});
    setFormError(null);
    try {
      const r = await api.post<Tablet & { pairing_code: string; pairing_expires_at: string }>("/api/tablets", {
        name: name.trim(), code: code || undefined, workspace_id: Number(wsId), camera_ids: cams,
      });
      onDone({ tablet: r.name, code: r.pairing_code, expires: r.pairing_expires_at });
    } catch (err) {
      const detail = err instanceof ApiFailure ? err.detail : undefined;
      const field = typeof detail?.field === "string" ? detail.field : undefined;
      const message = err instanceof Error ? err.message : "Could not register.";
      if (field) setErrors({ [field]: message });
      else setFormError(message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mb-4">
      <CardHeader title="Register a tablet" />
      <form onSubmit={save} noValidate className="grid gap-3.5">
        <div className="grid gap-3.5 sm:grid-cols-3">
          <TextField label="Tablet name" required value={name} onChange={(e) => setName(e.target.value)} error={errors.name} placeholder="Room 101 tablet" />
          <TextField label="Tablet ID (optional)" value={code} onChange={(e) => setCode(e.target.value)} error={errors.code} hint="Empty: numbered automatically (TAB-0001)." />
          <SelectField label="Workspace" required value={wsId} onChange={(e) => { setWsId(e.target.value); setCams([]); }} error={errors.workspace_id}>
            {spaces.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
          </SelectField>
        </div>
        <fieldset className="m-0 border-0 p-0">
          <legend className="label mb-1.5">Cameras this tablet may use</legend>
          {space?.cameras.length ? (
            <div className="grid gap-1.5 sm:grid-cols-3">
              {space.cameras.map((c) => (
                <Checkbox key={c.id} checked={cams.includes(c.id)} label={`${c.name} · ${c.room}`}
                          onChange={() => setCams((x) => x.includes(c.id) ? x.filter((i) => i !== c.id) : [...x, c.id])} />
              ))}
            </div>
          ) : <p className="m-0 text-[13px] text-ash">This workspace has no cameras; the tablet can still take class photos.</p>}
          {errors.camera_ids ? <p className="mt-1 text-[12.5px] text-oxide">{errors.camera_ids}</p> : null}
        </fieldset>
        <FormError>{formError}</FormError>
        <div className="flex gap-2">
          <Button type="submit" variant="primary" busy={busy}>Register and get pairing code</Button>
          <Button onClick={onCancel}>Cancel</Button>
        </div>
      </form>
    </Card>
  );
}

function CameraPicker({ tablet, space, onDone, onCancel }: { tablet: Tablet; space: Ws | undefined; onDone: () => void; onCancel: () => void }) {
  const { toast } = useUi();
  const [cams, setCams] = useState<number[]>(tablet.cameras.map((c) => c.id));
  const [busy, setBusy] = useState(false);

  async function save() {
    setBusy(true);
    try {
      await api.put(`/api/tablets/${tablet.id}/cameras`, { camera_ids: cams });
      toast(`Cameras for ${tablet.name} saved.`);
      onDone();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not save.", "bad");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mb-4">
      <CardHeader title={`Cameras for ${tablet.name}`} meta={space?.name} />
      {space?.cameras.length ? (
        <div className="grid gap-1.5 sm:grid-cols-3">
          {space.cameras.map((c) => (
            <Checkbox key={c.id} checked={cams.includes(c.id)} label={`${c.name} · ${c.room}`}
                      onChange={() => setCams((x) => x.includes(c.id) ? x.filter((i) => i !== c.id) : [...x, c.id])} />
          ))}
        </div>
      ) : <p className="m-0 text-[13.5px] text-ash">This workspace has no cameras yet. An administrator adds them under CCTV cameras.</p>}
      <div className="mt-3 flex gap-2">
        <Button variant="primary" onClick={save} busy={busy} disabled={!space?.cameras.length}>Save cameras</Button>
        <Button onClick={onCancel}>Cancel</Button>
      </div>
    </Card>
  );
}
