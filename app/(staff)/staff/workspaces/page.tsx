"use client";

/**
 * Workspaces: a group of cameras and tablets with the authorities allowed to use them.
 * Administrators create, edit, deactivate and delete workspaces and choose their members;
 * members can edit the description and location of their own workspaces.
 */
import { useCallback, useEffect, useState } from "react";

import Link from "next/link";

import { api, ApiFailure } from "@/lib/client";
import { ROLE_LABEL, useMe } from "@/lib/use-me";
import { Page, PageHeader } from "@/components/shell";
import { Banner, Card, CardHeader, Pill } from "@/components/ui";
import { Button, Checkbox, FormError, TextArea, TextField } from "@/components/forms";
import { EmptyState, PageError, PageLoading } from "@/components/states";
import { useUi } from "@/components/toast";

type Member = { id: number; name: string; email: string | null; role: string };
type Ws = {
  id: number; code: string; name: string; description: string | null; location: string | null; is_active: boolean;
  members: Member[]; cameras: { id: number; name: string; code: string | null; room: string }[]; tablets: number;
};
type Staff = { id: number; full_name: string; email: string; role: string; department: string | null; is_active: boolean };
type Form = { name: string; code: string; location: string; description: string; member_ids: number[]; is_active: boolean };

const EMPTY: Form = { name: "", code: "", location: "", description: "", member_ids: [], is_active: true };

export default function WorkspacesPage() {
  const { toast, confirm } = useUi();
  const { isAdministrator } = useMe();
  const [rows, setRows] = useState<Ws[] | null>(null);
  const [staff, setStaff] = useState<Staff[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Ws | "new" | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await api.get<Ws[]>("/api/workspaces"));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load workspaces.");
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    if (isAdministrator) api.get<Staff[]>("/api/admin/users").then(setStaff).catch(() => {});
  }, [isAdministrator]);

  async function remove(w: Ws) {
    if (!(await confirm({ title: `Delete ${w.name}?`, body: "Its cameras become administrator-only. A workspace that still has tablets cannot be deleted.", confirmLabel: "Delete", danger: true }))) return;
    try {
      await api.del(`/api/workspaces/${w.id}`);
      toast(`${w.name} deleted.`);
      load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not delete.", "bad");
    }
  }

  async function toggle(w: Ws) {
    try {
      await api.patch(`/api/workspaces/${w.id}`, { is_active: !w.is_active });
      toast(w.is_active ? `${w.name} deactivated: its members lose access to its cameras and tablets.` : `${w.name} activated.`);
      load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not change the status.", "bad");
    }
  }

  return (
    <Page wide>
      <PageHeader
        title="Workspaces"
        subtitle="Groups of cameras and tablets, and the authorities who may use them"
        actions={isAdministrator && !editing ? <Button variant="primary" onClick={() => setEditing("new")}>+ New workspace</Button> : null}
      />
      <Banner>
        <strong className="label mb-0.5 block">How access works</strong>
        An authority sees only the cameras and tablets of the workspaces they are a member of. Administrators create
        workspaces, add members here, and put cameras into a workspace under{" "}
        <Link href="/staff/cameras" className="text-ink underline">CCTV cameras</Link>. Members then register their tablets under{" "}
        <Link href="/staff/tablets" className="text-ink underline">Tablets</Link>.
      </Banner>

      {editing ? (
        <WorkspaceForm
          key={editing === "new" ? "new" : editing.id}
          ws={editing === "new" ? null : editing}
          staff={staff}
          isAdministrator={isAdministrator}
          onDone={() => { setEditing(null); load(); }}
          onCancel={() => setEditing(null)}
        />
      ) : null}

      {error ? <PageError message={error} retry={load} /> : !rows ? <PageLoading /> : !rows.length ? (
        <EmptyState title={isAdministrator ? "No workspaces yet" : "You are not in a workspace yet"}>
          {isAdministrator ? "Create one, add its members, then assign cameras to it." : "Ask an administrator to add you to a workspace."}
        </EmptyState>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {rows.map((w) => (
            <Card key={w.id}>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <strong className="text-[16px]">{w.name}</strong>
                  <div className="font-mono text-[12px] text-ash">{w.code}{w.location ? ` · ${w.location}` : ""}</div>
                </div>
                <Pill tone={w.is_active ? "ok" : "neutral"}>{w.is_active ? "active" : "inactive"}</Pill>
              </div>
              {w.description ? <p className="mb-0 mt-2 text-[13.5px]">{w.description}</p> : null}
              <dl className="m-0 mt-3 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-[13px]">
                <dt className="label pt-[2px] text-[11px]">Authorities</dt>
                <dd className="m-0">{w.members.length ? w.members.map((m) => `${m.name} (${ROLE_LABEL[m.role] ?? m.role})`).join(", ") : <span className="text-ash">none yet</span>}</dd>
                <dt className="label pt-[2px] text-[11px]">Cameras</dt>
                <dd className="m-0">{w.cameras.length ? w.cameras.map((c) => c.name).join(", ") : <span className="text-ash">none yet</span>}</dd>
                <dt className="label pt-[2px] text-[11px]">Tablets</dt>
                <dd className="m-0">{w.tablets}</dd>
              </dl>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button onClick={() => setEditing(w)}>Edit</Button>
                {isAdministrator ? (
                  <>
                    <Button onClick={() => toggle(w)}>{w.is_active ? "Deactivate" : "Activate"}</Button>
                    <Button variant="ghost" onClick={() => remove(w)}>Delete</Button>
                  </>
                ) : null}
              </div>
            </Card>
          ))}
        </div>
      )}
    </Page>
  );
}

function WorkspaceForm({ ws, staff, isAdministrator, onDone, onCancel }: {
  ws: Ws | null; staff: Staff[]; isAdministrator: boolean; onDone: () => void; onCancel: () => void;
}) {
  const { toast } = useUi();
  const [f, setF] = useState<Form>(ws ? {
    name: ws.name, code: ws.code, location: ws.location ?? "", description: ws.description ?? "",
    member_ids: ws.members.map((m) => m.id), is_active: ws.is_active,
  } : EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof Form) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value }));

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (f.name.trim().length < 2) return setErrors({ name: "Give the workspace a name (2+ characters)." });
    setBusy(true);
    setErrors({});
    setFormError(null);
    const body: Record<string, unknown> = { name: f.name.trim(), location: f.location, description: f.description };
    if (isAdministrator) Object.assign(body, { code: f.code || undefined, member_ids: f.member_ids, is_active: f.is_active });
    try {
      if (ws) await api.patch(`/api/workspaces/${ws.id}`, body);
      else await api.post("/api/workspaces", body);
      toast(ws ? "Workspace saved." : "Workspace created.");
      onDone();
    } catch (err) {
      const detail = err instanceof ApiFailure ? err.detail : undefined;
      const field = typeof detail?.field === "string" ? detail.field : undefined;
      const message = err instanceof Error ? err.message : "Could not save.";
      if (field) setErrors({ [field]: message });
      else setFormError(message);
    } finally {
      setBusy(false);
    }
  }

  const toggleMember = (id: number) => setF((x) => ({
    ...x, member_ids: x.member_ids.includes(id) ? x.member_ids.filter((m) => m !== id) : [...x.member_ids, id],
  }));

  return (
    <Card className="mb-4">
      <CardHeader title={ws ? `Edit ${ws.name}` : "New workspace"} />
      <form onSubmit={save} noValidate className="grid gap-3.5">
        <div className="grid gap-3.5 sm:grid-cols-2">
          <TextField label="Workspace name" required value={f.name} onChange={set("name")} error={errors.name} placeholder="e.g. CSE Block" />
          {isAdministrator ? (
            <TextField label="Workspace ID (optional)" value={f.code} onChange={set("code")} error={errors.code}
                       hint="Leave empty to number it automatically (WS-0001)." />
          ) : null}
          <TextField label="Location" value={f.location} onChange={set("location")} placeholder="e.g. Block A, ground floor" />
        </div>
        <TextArea label="Description" value={f.description} onChange={set("description")} rows={2} />
        {isAdministrator ? (
          <fieldset className="m-0 border-0 p-0">
            <legend className="label mb-1.5">Authorities in this workspace</legend>
            {staff.length ? (
              <div className="grid max-h-[260px] gap-1.5 overflow-y-auto rounded-[var(--radius)] border border-rule p-2.5 sm:grid-cols-2">
                {staff.map((s) => (
                  <Checkbox key={s.id} checked={f.member_ids.includes(s.id)} onChange={() => toggleMember(s.id)}
                            label={<>{s.full_name} <span className="text-[12px] text-ash">{ROLE_LABEL[s.role] ?? s.role}{s.department ? ` · ${s.department}` : ""}</span></>} />
                ))}
              </div>
            ) : <p className="m-0 text-[13px] text-ash">No staff accounts yet.</p>}
            {errors.member_ids ? <p className="mt-1 text-[12.5px] text-oxide">{errors.member_ids}</p> : null}
          </fieldset>
        ) : null}
        {isAdministrator && ws ? (
          <Checkbox checked={f.is_active} onChange={(e) => setF((x) => ({ ...x, is_active: e.target.checked }))} label="Active" />
        ) : null}
        <FormError>{formError}</FormError>
        <div className="flex gap-2">
          <Button type="submit" variant="primary" busy={busy}>{ws ? "Save" : "Create workspace"}</Button>
          <Button onClick={onCancel}>Cancel</Button>
        </div>
      </form>
    </Card>
  );
}
