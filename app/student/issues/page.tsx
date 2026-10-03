"use client";

import { useCallback, useEffect, useState } from "react";

import Link from "next/link";

import { api, ApiFailure } from "@/lib/client";
import { Page, PageHeader } from "@/components/shell";
import { Card, CardHeader, Pill } from "@/components/ui";
import { Button, FormError, SelectField, TextArea, TextField } from "@/components/forms";
import { EmptyState, PageError, PageLoading } from "@/components/states";
import { useUi } from "@/components/toast";
import { ISSUE_CATEGORIES, issueTone, type IssueRow } from "@/lib/issues";

export default function IssuesPage() {
  const [rows, setRows] = useState<IssueRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    try {
      setRows(await api.get<IssueRow[]>("/api/me/issues"));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load your issues.");
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  return (
    <Page>
      <PageHeader title="Issues & queries" subtitle="Raise a problem with your teacher and track the answer"
                  actions={creating ? null : <Button variant="primary" onClick={() => setCreating(true)}>+ Raise an issue</Button>} />
      {creating ? <NewIssue onDone={() => { setCreating(false); load(); }} onCancel={() => setCreating(false)} /> : null}
      {error ? <PageError message={error} retry={load} /> : !rows ? <PageLoading /> : !rows.length ? (
        <EmptyState title="No issues raised" />
      ) : (
        <Card>
          <ul className="m-0 list-none p-0">
            {rows.map((i) => (
              <li key={i.id} className="flex items-start justify-between gap-3 border-b border-rule py-2.5 last:border-0">
                <div className="min-w-0">
                  <Link href={`/student/issues/${i.id}`} className="text-[15px] font-semibold text-ink">{i.title}</Link>
                  <div className="text-[12.5px] text-ash">
                    {i.category_label} · updated {new Date(i.updated_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}
                    {i.comment_count ? ` · ${i.comment_count} repl${i.comment_count === 1 ? "y" : "ies"}` : ""}
                  </div>
                </div>
                <Pill tone={issueTone(i.status)}>{i.status.replace("_", " ")}</Pill>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </Page>
  );
}

function NewIssue({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const { toast } = useUi();
  const [f, setF] = useState({ category: "", title: "", description: "" });
  const [file, setFile] = useState<File | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (!f.category) errs.category = "Choose a category.";
    if (f.title.trim().length < 3) errs.title = "Write a short title.";
    if (f.description.trim().length < 10) errs.description = "Describe the issue (at least 10 characters).";
    if (file && file.size > 5 * 1024 * 1024) errs.attachment = "The attachment must be under 5 MB.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    const fd = new FormData();
    for (const [k, v] of Object.entries(f)) fd.append(k, v.trim());
    if (file) fd.append("attachment", file);
    setBusy(true);
    setFormError(null);
    try {
      await api.upload("/api/me/issues", fd);
      toast("Issue sent to your teacher.");
      onDone();
    } catch (err) {
      const d = err instanceof ApiFailure ? err.detail : undefined;
      if (d && typeof d.field === "string") setErrors({ [d.field]: err instanceof Error ? err.message : "" });
      else setFormError(err instanceof Error ? err.message : "Could not submit.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mb-4">
      <CardHeader title="Raise an issue" />
      <FormError>{formError}</FormError>
      <form onSubmit={submit} noValidate className="grid gap-3.5">
        <div className="grid gap-3.5 sm:grid-cols-[220px_minmax(0,1fr)]">
          <SelectField label="Category" required value={f.category} error={errors.category}
                       onChange={(e) => setF((x) => ({ ...x, category: e.target.value }))}>
            <option value="">Select…</option>
            {ISSUE_CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </SelectField>
          <TextField label="Title" required maxLength={160} value={f.title} error={errors.title}
                     onChange={(e) => setF((x) => ({ ...x, title: e.target.value }))} />
        </div>
        <TextArea label="Description" required value={f.description} error={errors.description}
                  onChange={(e) => setF((x) => ({ ...x, description: e.target.value }))}
                  hint="For an attendance correction, say which lecture and date." />
        <label className="display inline-flex w-fit cursor-pointer rounded-[3px] border border-ink px-3.5 py-2 text-[12px] text-ink hover:bg-tint">
          {file ? `Attached: ${file.name}` : "Attach file (optional)"}
          <input type="file" accept="application/pdf,image/jpeg,image/png" className="sr-only" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        {errors.attachment ? <p role="alert" className="m-0 text-[12.5px] text-oxide">{errors.attachment}</p> : null}
        <div className="flex gap-2">
          <Button type="submit" variant="primary" busy={busy}>Submit</Button>
          <Button onClick={onCancel}>Cancel</Button>
        </div>
      </form>
    </Card>
  );
}
