"use client";

/** The append-only audit log: who did what, to which record, why, when, from where. */
import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/client";
import { Page, PageHeader } from "@/components/shell";
import { Card } from "@/components/ui";
import { Button, SelectField, TextField } from "@/components/forms";
import { EmptyState, PageError, PageLoading } from "@/components/states";

type Row = {
  id: number; at: string; action: string; actor: string; target_type: string | null; target_id: string | null;
  reason: string | null; detail: string | null; ip: string | null;
};
type Payload = { rows: Row[]; meta: { page: number; total: number; pages: number }; actions: string[] };

function pretty(detail: string | null) {
  if (!detail) return null;
  try {
    const obj = JSON.parse(detail);
    return Object.entries(obj)
      .map(([k, v]) => `${k}: ${Array.isArray(v) && v.length === 2 ? `${v[0] ?? "—"} → ${v[1] ?? "—"}` : typeof v === "object" ? JSON.stringify(v) : v}`)
      .join(" · ");
  } catch {
    return detail;
  }
}

export default function AuditPage() {
  const [f, setF] = useState({ action: "", q: "", date_from: "", date_to: "", page: 1 });
  const [data, setData] = useState<Payload | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(f)) if (v) p.set(k, String(v));
    try {
      setData(await api.get<Payload>(`/api/admin/audit?${p}`));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load the audit log.");
    }
  }, [f]);
  useEffect(() => {
    const t = setTimeout(load, 250);
    return () => clearTimeout(t);
  }, [load]);

  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF((x) => ({ ...x, [k]: e.target.value, page: 1 }));

  return (
    <Page wide>
      <PageHeader title="Audit log" subtitle={data ? `${data.meta.total} entr${data.meta.total === 1 ? "y" : "ies"}` : ""} />
      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <SelectField label="Action" value={f.action} onChange={set("action")}>
            <option value="">All actions</option>
            {data?.actions.map((a) => <option key={a} value={a}>{a.replace(/_/g, " ")}</option>)}
          </SelectField>
          <TextField label="Search detail / reason" type="search" value={f.q} onChange={set("q")} />
          <TextField label="From" type="date" value={f.date_from} onChange={set("date_from")} />
          <TextField label="To" type="date" value={f.date_to} onChange={set("date_to")} />
        </div>
      </Card>
      {error ? <PageError message={error} retry={load} /> : !data ? <PageLoading /> : !data.rows.length ? <EmptyState title="No entries match" /> : (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] border-collapse text-[13px]">
              <thead>
                <tr>
                  {["When", "Who", "Action", "Target", "Reason / detail"].map((h) => (
                    <th key={h} className="label border-b-2 border-ink px-2 pb-1.5 text-left">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.id} className="align-top hover:bg-tint">
                    <td className="whitespace-nowrap border-b border-rule px-2 py-1.5 font-mono text-[12px]">{new Date(r.at).toLocaleString()}</td>
                    <td className="border-b border-rule px-2">{r.actor}{r.ip ? <div className="font-mono text-[11px] text-ash">{r.ip}</div> : null}</td>
                    <td className="border-b border-rule px-2 font-mono">{r.action}</td>
                    <td className="border-b border-rule px-2 font-mono text-[12px]">{r.target_type ? `${r.target_type} #${r.target_id ?? ""}` : "—"}</td>
                    <td className="border-b border-rule px-2">
                      {r.reason ? <div><strong>Reason:</strong> {r.reason}</div> : null}
                      <div className="break-words text-ash">{pretty(r.detail)}</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
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
