"use client";

/**
 * One list/create/edit/delete screen, configured by data.
 *
 * Every Setup entity (branches, batches, sections, subjects, rooms, holidays, terms,
 * assignments, timetable) is the same shape of problem, so it is solved once: a table, an
 * inline form that doubles as the editor, inline field errors from the server, and a delete that
 * asks first and shows the server's own refusal ("Branch CSE still has 120 students").
 */
import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";

import { api, ApiFailure } from "@/lib/client";
import { Button, Checkbox, FormError, SelectField, TextField } from "@/components/forms";
import { useUi } from "@/components/toast";
import { EmptyState, PageError, PageLoading } from "@/components/states";
import { Card, CardHeader } from "@/components/ui";

export type Option = { value: string | number; label: string };

export type FieldDef = {
  name: string;
  label: string;
  type?: "text" | "number" | "date" | "time" | "select" | "checkbox" | "email" | "tel";
  options?: Option[] | ((form: Record<string, string>) => Option[]);
  required?: boolean;
  hint?: string;
  placeholder?: string;
  /** Not shown when editing (e.g. a code that is the identity). */
  createOnly?: boolean;
  /** Only shown when this returns true. */
  when?: (form: Record<string, string>) => boolean;
  /** Changing this field clears these others (dependent dropdowns). */
  clears?: string[];
};

export type Column<T> = { key: string; label: string; render?: (row: T) => ReactNode; className?: string };

type Props<T extends { id: number }> = {
  title: string;
  endpoint: string;
  listQuery?: string;
  columns: Column<T>[];
  fields: FieldDef[];
  toForm?: (row: T) => Record<string, string>;
  toPayload?: (form: Record<string, string>) => Record<string, unknown>;
  canCreate?: boolean;
  canEdit?: boolean | ((row: T) => boolean);
  canDelete?: boolean | ((row: T) => boolean);
  deleteLabel?: (row: T) => string;
  empty?: ReactNode;
  onChange?: () => void;
  intro?: ReactNode;
};

function fieldValue(def: FieldDef, raw: string): unknown {
  if (def.type === "checkbox") return raw === "true";
  if (raw === "") return null;
  if (def.type === "number" || (def.type === "select" && /^\d+$/.test(raw) && def.name.endsWith("_id")))
    return Number(raw);
  if (def.type === "select" && def.name === "day_of_week") return Number(raw);
  return raw;
}

export function CrudTable<T extends { id: number }>({
  title,
  endpoint,
  listQuery = "",
  columns,
  fields,
  toForm,
  toPayload,
  canCreate = true,
  canEdit = true,
  canDelete = true,
  deleteLabel,
  empty,
  onChange,
  intro,
}: Props<T>) {
  const { toast, confirm } = useUi();
  const [rows, setRows] = useState<T[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<T | "new" | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setRows(await api.get<T[]>(`${endpoint}${listQuery}`));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load.");
    }
  }, [endpoint, listQuery]);

  useEffect(() => {
    load();
  }, [load]);

  const blank = () =>
    Object.fromEntries(fields.map((f) => [f.name, f.type === "checkbox" ? "false" : ""]));

  function open(row: T | "new") {
    setEditing(row);
    setErrors({});
    setFormError(null);
    if (row === "new") setForm(blank());
    else
      setForm(
        toForm
          ? toForm(row)
          : Object.fromEntries(
              fields.map((f) => [f.name, String((row as Record<string, unknown>)[f.name] ?? "")]),
            ),
      );
  }

  const allowed = (rule: boolean | ((r: T) => boolean), row: T) =>
    typeof rule === "function" ? rule(row) : rule;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    for (const f of fields) {
      if (f.when && !f.when(form)) continue;
      if (editing !== "new" && f.createOnly) continue;
      if (f.required && f.type !== "checkbox" && !String(form[f.name] ?? "").trim())
        errs[f.name] = `${f.label} is required.`;
    }
    setErrors(errs);
    if (Object.keys(errs).length) return;

    const payload = toPayload
      ? toPayload(form)
      : Object.fromEntries(
          fields
            .filter((f) => (!f.when || f.when(form)) && !(editing !== "new" && f.createOnly))
            .map((f) => [f.name, fieldValue(f, form[f.name] ?? "")]),
        );
    setBusy(true);
    setFormError(null);
    try {
      if (editing === "new") await api.post(endpoint, payload);
      else if (editing) await api.patch(`${endpoint}/${editing.id}`, payload);
      toast(editing === "new" ? `${title.replace(/s$/, "")} added.` : "Saved.");
      setEditing(null);
      await load();
      onChange?.();
    } catch (err) {
      const d = err instanceof ApiFailure ? err.detail : undefined;
      const msg = err instanceof Error ? err.message : "Could not save.";
      if (d && typeof d.field === "string" && fields.some((f) => f.name === d.field))
        setErrors({ [d.field as string]: msg });
      else setFormError(msg);
    } finally {
      setBusy(false);
    }
  }

  async function remove(row: T) {
    const name = deleteLabel ? deleteLabel(row) : `this ${title.replace(/s$/, "").toLowerCase()}`;
    const ok = await confirm({
      title: `Delete ${name}?`,
      body: "This cannot be undone. If anything still depends on it, the deletion is refused and nothing changes.",
      confirmLabel: "Delete",
      danger: true,
    });
    if (!ok) return;
    try {
      await api.del(`${endpoint}/${row.id}`);
      toast("Deleted.");
      await load();
      onChange?.();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Could not delete.", "bad");
    }
  }

  const visible = fields.filter((f) => (!f.when || f.when(form)) && !(editing !== "new" && f.createOnly));

  return (
    <Card>
      <CardHeader
        title={title}
        meta={
          canCreate && editing === null ? (
            <Button variant="primary" onClick={() => open("new")}>
              + Add
            </Button>
          ) : rows ? `${rows.length} total` : undefined
        }
      />
      {intro ? <div className="mb-3 text-[13.5px] text-ash">{intro}</div> : null}

      {editing !== null ? (
        <form
          onSubmit={submit}
          noValidate
          className="mb-4 rounded-[3px] border border-rule bg-paper p-3.5"
          aria-label={editing === "new" ? `Add ${title}` : `Edit ${title}`}
        >
          <FormError>{formError}</FormError>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {visible.map((f) => {
              const opts = typeof f.options === "function" ? f.options(form) : f.options ?? [];
              const onChangeValue = (v: string) => {
                setForm((x) => {
                  const nx = { ...x, [f.name]: v };
                  for (const c of f.clears ?? []) nx[c] = "";
                  return nx;
                });
                setErrors(({ [f.name]: _d, ...rest }) => rest);
              };
              if (f.type === "checkbox")
                return (
                  <div key={f.name} className="flex items-end pb-2">
                    <Checkbox
                      label={f.label}
                      checked={form[f.name] === "true"}
                      onChange={(e) => onChangeValue(e.target.checked ? "true" : "false")}
                    />
                  </div>
                );
              if (f.type === "select")
                return (
                  <SelectField
                    key={f.name}
                    label={f.label}
                    required={f.required}
                    value={form[f.name] ?? ""}
                    error={errors[f.name]}
                    hint={f.hint}
                    onChange={(e) => onChangeValue(e.target.value)}
                  >
                    <option value="">{f.required ? "Select…" : "—"}</option>
                    {opts.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </SelectField>
                );
              return (
                <TextField
                  key={f.name}
                  label={f.label}
                  type={f.type ?? "text"}
                  required={f.required}
                  placeholder={f.placeholder}
                  value={form[f.name] ?? ""}
                  error={errors[f.name]}
                  hint={f.hint}
                  inputMode={f.type === "number" ? "decimal" : undefined}
                  onChange={(e) => onChangeValue(e.target.value)}
                />
              );
            })}
          </div>
          <div className="mt-3 flex gap-2">
            <Button type="submit" variant="primary" busy={busy}>
              {editing === "new" ? "Add" : "Save"}
            </Button>
            <Button onClick={() => setEditing(null)}>Cancel</Button>
          </div>
        </form>
      ) : null}

      {error ? (
        <PageError message={error} retry={load} />
      ) : rows === null ? (
        <PageLoading rows={2} />
      ) : rows.length === 0 ? (
        <EmptyState title={`No ${title.toLowerCase()} yet`}>{empty}</EmptyState>
      ) : (
        <div className="relative -mx-1 overflow-x-auto">
          <table className="w-full min-w-[520px] border-collapse text-[13.5px]">
            <thead>
              <tr>
                {columns.map((c) => (
                  <th key={c.key} className="label border-b-2 border-ink px-2 pb-1.5 text-left">
                    {c.label}
                  </th>
                ))}
                <th className="relative label border-b-2 border-ink px-2 pb-1.5 text-right">
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="hover:bg-tint">
                  {columns.map((c) => (
                    <td key={c.key} className={`border-b border-rule px-2 py-2 align-top ${c.className ?? ""}`}>
                      {c.render ? c.render(row) : String((row as Record<string, unknown>)[c.key] ?? "—")}
                    </td>
                  ))}
                  <td className="whitespace-nowrap border-b border-rule px-2 py-1.5 text-right">
                    {allowed(canEdit, row) ? (
                      <button
                        type="button"
                        onClick={() => open(row)}
                        className="cursor-pointer border-0 bg-transparent px-2 py-1 text-[13px] text-ink underline-offset-2 hover:underline"
                      >
                        Edit
                      </button>
                    ) : null}
                    {allowed(canDelete, row) ? (
                      <button
                        type="button"
                        onClick={() => remove(row)}
                        className="cursor-pointer border-0 bg-transparent px-2 py-1 text-[13px] text-oxide underline-offset-2 hover:underline"
                      >
                        Delete
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
