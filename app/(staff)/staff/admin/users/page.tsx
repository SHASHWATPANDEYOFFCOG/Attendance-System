"use client";

/** Teachers, HODs and administrators. Role changes are audited and guarded on the server. */
import { useCallback, useEffect, useState } from "react";

import { api, ApiFailure } from "@/lib/client";
import { Page, PageHeader } from "@/components/shell";
import { Card, Pill } from "@/components/ui";
import { Button, FormError, SelectField, TextField } from "@/components/forms";
import { EmptyState, PageError, PageLoading } from "@/components/states";
import { useUi } from "@/components/toast";

type Staff = {
  id: number; full_name: string; email: string | null; phone: string | null; role: string;
  department_id: number | null; department: string | null; is_active: boolean; locked: boolean;
  last_login_at: string | null;
};
type Dept = { id: number; code: string; name: string };
type Me = { id: number; role: string; department_id: number | null };

const ROLE_LABEL: Record<string, string> = { faculty: "Teacher", admin: "HOD", super_admin: "Administrator" };

export default function UsersPage() {
  const { toast, confirm } = useUi();
  const [rows, setRows] = useState<Staff[] | null>(null);
  const [depts, setDepts] = useState<Dept[]>([]);
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState<Staff | "new" | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await api.get<Staff[]>(`/api/admin/users?include_inactive=true${q ? `&q=${encodeURIComponent(q)}` : ""}`));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load staff.");
    }
  }, [q]);
  useEffect(() => {
    const t = setTimeout(load, 250);
    return () => clearTimeout(t);
  }, [load]);
  useEffect(() => {
    api.get<Dept[]>("/api/departments").then(setDepts).catch(() => {});
    api.get<Me>("/api/me").then(setMe).catch(() => {});
  }, []);

  const superAdmin = me?.role === "super_admin";

  async function unlock(u: Staff) {
    try {
      await api.post(`/api/admin/users/${u.id}/unlock`);
      toast(`${u.full_name} unlocked.`);
      load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not unlock.", "bad");
    }
  }

  async function toggleActive(u: Staff) {
    if (u.is_active && !(await confirm({ title: `Disable ${u.full_name}?`, body: "They will be signed out and cannot sign in until re-enabled.", danger: true, confirmLabel: "Disable" }))) return;
    try {
      await api.patch(`/api/admin/users/${u.id}`, { is_active: !u.is_active });
      toast(u.is_active ? "Account disabled." : "Account enabled.");
      load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Action failed.", "bad");
    }
  }

  return (
    <Page wide>
      <PageHeader
        title="Staff & roles"
        subtitle={superAdmin ? "Teachers, HODs and administrators" : "Teachers in your branch"}
        actions={<Button variant="primary" onClick={() => setEditing("new")}>+ Add staff</Button>}
      />
      {editing ? (
        <StaffForm
          key={editing === "new" ? "new" : editing.id}
          staff={editing === "new" ? null : editing}
          depts={depts}
          superAdmin={superAdmin}
          myDept={me?.department_id ?? null}
          onDone={() => { setEditing(null); load(); }}
          onCancel={() => setEditing(null)}
        />
      ) : null}
      <Card className="mb-4">
        <TextField label="Search" type="search" placeholder="Name or email" value={q} onChange={(e) => setQ(e.target.value)} />
      </Card>
      {error ? <PageError message={error} retry={load} /> : !rows ? <PageLoading /> : !rows.length ? <EmptyState title="No staff found" /> : (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[680px] border-collapse text-[13.5px]">
              <thead>
                <tr>
                  {["Name", "Role", "Branch", "Last sign-in", ""].map((h) => (
                    <th key={h} className="label border-b-2 border-ink px-2 pb-1.5 text-left">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((u) => (
                  <tr key={u.id} className={`hover:bg-tint ${u.is_active ? "" : "opacity-60"}`}>
                    <td className="border-b border-rule px-2 py-2">
                      <strong>{u.full_name}</strong>
                      <div className="font-mono text-[11px] text-ash">{u.email}</div>
                    </td>
                    <td className="border-b border-rule px-2">
                      {ROLE_LABEL[u.role] ?? u.role}
                      {!u.is_active ? <> <Pill tone="bad">disabled</Pill></> : null}
                      {u.locked ? <> <Pill tone="warn">locked</Pill></> : null}
                    </td>
                    <td className="border-b border-rule px-2">{u.department ?? "—"}</td>
                    <td className="border-b border-rule px-2 font-mono text-[12px] text-ash">
                      {u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "never"}
                    </td>
                    <td className="whitespace-nowrap border-b border-rule px-2 text-right">
                      {u.locked ? <button type="button" className="cursor-pointer border-0 bg-transparent px-2 text-ink underline" onClick={() => unlock(u)}>Unlock</button> : null}
                      {u.id !== me?.id && (superAdmin || u.role === "faculty") ? (
                        <>
                          <button type="button" className="cursor-pointer border-0 bg-transparent px-2 text-ink underline" onClick={() => setEditing(u)}>Edit</button>
                          <button type="button" className="cursor-pointer border-0 bg-transparent px-2 text-oxide underline" onClick={() => toggleActive(u)}>
                            {u.is_active ? "Disable" : "Enable"}
                          </button>
                        </>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </Page>
  );
}

function StaffForm({
  staff, depts, superAdmin, myDept, onDone, onCancel,
}: {
  staff: Staff | null; depts: Dept[]; superAdmin: boolean; myDept: number | null; onDone: () => void; onCancel: () => void;
}) {
  const { toast } = useUi();
  const [f, setF] = useState({
    full_name: staff?.full_name ?? "", email: staff?.email ?? "", phone: staff?.phone ?? "",
    role: staff?.role ?? "faculty", department_id: String(staff?.department_id ?? (superAdmin ? "" : myDept ?? "")),
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => {
    setF((x) => ({ ...x, [k]: e.target.value }));
    setErrors(({ [k]: _d, ...rest }) => rest);
  };

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setFormError(null);
    const body = {
      full_name: f.full_name, phone: f.phone || null, role: f.role,
      department_id: f.department_id ? Number(f.department_id) : null,
      ...(staff ? {} : { email: f.email }),
    };
    try {
      if (staff) await api.patch(`/api/admin/users/${staff.id}`, body);
      else await api.post("/api/admin/users", body);
      toast(staff ? "Saved." : "Account created. An invite to set a password was emailed.");
      onDone();
    } catch (err) {
      const d = err instanceof ApiFailure ? err.detail : undefined;
      if (d && typeof d.field === "string") setErrors({ [d.field]: err instanceof Error ? err.message : "" });
      else setFormError(err instanceof Error ? err.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mb-4">
      <h2 className="display m-0 mb-3 text-[15px] text-ash">{staff ? `Edit ${staff.full_name}` : "Add staff member"}</h2>
      <FormError>{formError}</FormError>
      <form onSubmit={submit} noValidate className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <TextField label="Full name" required value={f.full_name} onChange={set("full_name")} error={errors.full_name} />
        <TextField label="Email" type="email" required value={f.email} onChange={set("email")} error={errors.email} disabled={Boolean(staff)} />
        <TextField label="Phone" type="tel" value={f.phone} onChange={set("phone")} error={errors.phone ?? errors.mobile} />
        <SelectField label="Role" value={f.role} onChange={set("role")} error={errors.role} disabled={!superAdmin}>
          <option value="faculty">Teacher</option>
          {superAdmin ? <option value="admin">Head of department</option> : null}
          {superAdmin ? <option value="super_admin">Administrator</option> : null}
        </SelectField>
        <SelectField label="Branch" value={f.department_id} onChange={set("department_id")} error={errors.department_id}
                     disabled={!superAdmin || f.role === "super_admin"}>
          <option value="">{f.role === "super_admin" ? "All branches" : "Select…"}</option>
          {depts.map((d) => <option key={d.id} value={d.id}>{d.code} — {d.name}</option>)}
        </SelectField>
        <div className="flex items-end gap-2">
          <Button type="submit" variant="primary" busy={busy}>{staff ? "Save" : "Create & send invite"}</Button>
          <Button onClick={onCancel}>Cancel</Button>
        </div>
      </form>
    </Card>
  );
}
