"use client";

import { useCallback, useEffect, useState } from "react";

import Link from "next/link";

import { api } from "@/lib/client";
import { ISSUE_CATEGORIES, issueTone, type IssueRow } from "@/lib/issues";
import { Page, PageHeader } from "@/components/shell";
import { Card, Pill } from "@/components/ui";
import { Button, SelectField, TextField } from "@/components/forms";
import { EmptyState, PageError, PageLoading } from "@/components/states";

export default function StaffIssuesPage() {
  const [f, setF] = useState({ status: "active", category: "", assigned: "", q: "", page: 1 });
  const [data, setData] = useState<{ rows: IssueRow[]; meta: { total: number; pages: number } } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(f)) if (v) p.set(k, String(v));
    try {
      setData(await api.get(`/api/issues?${p}`));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load issues.");
    }
  }, [f]);
  useEffect(() => {
    const t = setTimeout(load, 200);
    return () => clearTimeout(t);
  }, [load]);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value, page: 1 }));

  return (
    <Page wide>
      <PageHeader title="Issues" subtitle={data ? `${data.meta.total} matching` : ""} />
      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <SelectField label="Status" value={f.status} onChange={set("status")}>
            <option value="active">Open & in progress</option>
            <option value="">All</option>
            {["open", "in_progress", "resolved", "closed"].map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
          </SelectField>
          <SelectField label="Category" value={f.category} onChange={set("category")}>
            <option value="">All</option>
            {ISSUE_CATEGORIES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </SelectField>
          <SelectField label="Assigned" value={f.assigned} onChange={set("assigned")}>
            <option value="">Anyone</option>
            <option value="me">Assigned to me</option>
            <option value="none">Unassigned</option>
          </SelectField>
          <TextField label="Search" type="search" value={f.q} onChange={set("q")} placeholder="Title, student, roll no" />
        </div>
      </Card>
      {error ? <PageError message={error} retry={load} /> : !data ? <PageLoading /> : !data.rows.length ? (
        <EmptyState title="No issues match" />
      ) : (
        <Card>
          <ul className="m-0 list-none p-0">
            {data.rows.map((i) => (
              <li key={i.id} className="flex items-start justify-between gap-3 border-b border-rule py-2.5 last:border-0">
                <div className="min-w-0">
                  <Link href={`/staff/issues/${i.id}`} className="text-[15px] font-semibold text-ink">{i.title}</Link>
                  <div className="text-[12.5px] text-ash">
                    {i.student.name} ({i.student.roll_number}) · {i.student.section} · {i.category_label}
                    {i.assigned_to ? ` · ${i.assigned_to.name}` : ""} · {new Date(i.updated_at).toLocaleDateString()}
                  </div>
                </div>
                <Pill tone={issueTone(i.status)}>{i.status.replace("_", " ")}</Pill>
              </li>
            ))}
          </ul>
          {data.meta.pages > 1 ? (
            <nav className="mt-3 flex items-center justify-between" aria-label="Pages">
              <Button disabled={f.page <= 1} onClick={() => setF((x) => ({ ...x, page: x.page - 1 }))}>Previous</Button>
              <span className="font-mono text-[12px] text-ash">page {f.page} of {data.meta.pages}</span>
              <Button disabled={f.page >= data.meta.pages} onClick={() => setF((x) => ({ ...x, page: x.page + 1 }))}>Next</Button>
            </nav>
          ) : null}
        </Card>
      )}
    </Page>
  );
}
