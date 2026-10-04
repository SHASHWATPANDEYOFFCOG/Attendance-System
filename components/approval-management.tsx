"use client";

/**
 * Approval management: every student in your scope by status (pending, approved, rejected,
 * revoked), filtered by academic year, branch, batch, year and section, with single and bulk
 * decisions. The server decides what each authority may see and do; every decision is
 * recorded in the audit log with the old and new status.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import Link from "next/link";

import { api } from "@/lib/client";
import { Card, Pill } from "@/components/ui";
import { Button, Checkbox, SelectField, TextField } from "@/components/forms";
import { EmptyState, PageError, PageLoading } from "@/components/states";
import { useUi } from "@/components/toast";

type Row = {
  id: number; full_name: string; email: string | null; roll_number: string | null; department: string | null;
  batch: string | null; year: number | null; section_name: string | null; academic_year: string | null;
  status: "pending" | "approved" | "rejected" | "revoked"; email_verified: boolean; photo_url: string | null;
  reason: string | null; decided_at: string | null;
};
type Opt = { id: number; label: string };
type Status = Row["status"];
type Action = "approve" | "reject" | "revoke" | "restore";

const STATUSES: [Status, string][] = [["pending", "Pending"], ["approved", "Approved"], ["rejected", "Rejected"], ["revoked", "Revoked"]];
const TONE: Record<Status, "warn" | "ok" | "bad" | "neutral"> = { pending: "warn", approved: "ok", rejected: "bad", revoked: "neutral" };
const ACTIONS_FOR: Record<Status, Action[]> = { pending: ["approve", "reject"], approved: ["revoke", "reject"], rejected: ["approve"], revoked: ["restore"] };
const VERB: Record<Action, string> = { approve: "Approve", reject: "Reject", revoke: "Revoke", restore: "Restore" };

export function ApprovalManagement({ onChange }: { onChange: () => void }) {
  const { toast, confirm, askReason } = useUi();
  const [status, setStatus] = useState<Status>("pending");
  const [filters, setFilters] = useState({ academic_year_id: "", department_id: "", batch_id: "", year: "", section_id: "", q: "" });
  const [qInput, setQInput] = useState("");
  const [rows, setRows] = useState<Row[] | null>(null);
  const [total, setTotal] = useState(0);
  const [counts, setCounts] = useState<Partial<Record<Status, number>>>({});
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  const [opts, setOpts] = useState<{ years: Opt[]; branches: Opt[]; batches: Opt[]; sections: (Opt & { department_id: number | null; year: number; batch_id: number | null })[] }>({ years: [], branches: [], batches: [], sections: [] });

  useEffect(() => {
    Promise.all([
      api.get<{ id: number; label: string; is_current: boolean }[]>("/api/academic-years").catch(() => []),
      api.get<{ id: number; code: string; name: string }[]>("/api/departments").catch(() => []),
      api.get<{ id: number; label: string }[]>("/api/batches").catch(() => []),
      api.get<{ id: number; label: string; name: string; department_id: number | null; year: number; batch_id: number | null }[]>("/api/sections").catch(() => []),
    ]).then(([y, d, b, s]) => setOpts({
      years: y.map((x) => ({ id: x.id, label: x.label + (x.is_current ? " (current)" : "") })),
      branches: d.map((x) => ({ id: x.id, label: `${x.code} — ${x.name}` })),
      batches: b.map((x) => ({ id: x.id, label: x.label })),
      sections: s.map((x) => ({ id: x.id, label: x.label, department_id: x.department_id, year: x.year, batch_id: x.batch_id })),
    }));
  }, []);

  const query = useCallback((st: Status, size = 200) => {
    const p = new URLSearchParams({ status: st, page_size: String(size) });
    for (const [k, v] of Object.entries(filters)) if (v) p.set(k, v);
    return `/api/students?${p}`;
  }, [filters]);

  const load = useCallback(async () => {
    try {
      const r = await api.get<{ rows: Row[]; meta: { total: number } }>(query(status));
      setRows(r.rows);
      setTotal(r.meta.total);
      setSelected(new Set());
      setError(null);
      const all = await Promise.all(STATUSES.map(([s]) => api.get<{ meta: { total: number } }>(query(s, 10)).then((x) => [s, x.meta.total] as const)));
      setCounts(Object.fromEntries(all));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load students.");
    }
  }, [query, status]);
  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    const t = setTimeout(() => setFilters((f) => (f.q === qInput ? f : { ...f, q: qInput })), 350);
    return () => clearTimeout(t);
  }, [qInput]);

  const sections = useMemo(() => opts.sections.filter((s) =>
    (!filters.department_id || String(s.department_id) === filters.department_id) &&
    (!filters.year || String(s.year) === filters.year) &&
    (!filters.batch_id || String(s.batch_id) === filters.batch_id)), [opts.sections, filters]);
  const setF = (k: keyof typeof filters) => (e: { target: { value: string } }) =>
    setFilters((f) => ({ ...f, [k]: e.target.value, ...(k !== "section_id" && k !== "q" ? { section_id: "" } : {}) }));

  async function decide(ids: number[], action: Action, who: string) {
    let reason: string | null = null;
    if (action === "reject" || action === "revoke") {
      reason = await askReason({
        title: `${VERB[action]} ${who}?`, confirmLabel: VERB[action], danger: true,
        body: action === "revoke" ? "They can still sign in but can no longer mark attendance. You can restore access later." : undefined,
        reason: { label: "Reason (the student sees it)", minLength: 3 },
      });
      if (!reason) return;
    } else if (!(await confirm({ title: `${VERB[action]} ${who}?`, confirmLabel: VERB[action],
      body: action === "approve" ? "Check the details against college records first. Approving also confirms an unverified email." : undefined }))) {
      return;
    }
    setBusy(true);
    try {
      if (ids.length === 1) {
        await api.post(`/api/students/${ids[0]}/${action}`, reason ? { reason } : undefined);
        toast(`${who}: ${VERB[action].toLowerCase()}d.`);
      } else {
        const r = await api.post<{ done: number[]; failed: { id: number; message: string }[] }>("/api/students/bulk-decision", { ids, action, reason });
        toast(`${r.done.length} done${r.failed.length ? `, ${r.failed.length} skipped (${r.failed[0].message})` : ""}.`, r.failed.length ? "bad" : "ok");
      }
      await load();
      onChange();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Action failed.", "bad");
    } finally {
      setBusy(false);
    }
  }

  const allTicked = !!rows?.length && rows.every((r) => selected.has(r.id));
  const toggle = (id: number) => setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });

  return (
    <div className="grid gap-3">
      <nav aria-label="Status" className="flex flex-wrap gap-1">
        {STATUSES.map(([s, label]) => (
          <button key={s} type="button" onClick={() => setStatus(s)} aria-pressed={status === s}
                  className="display cursor-pointer rounded-[var(--radius)] border px-3 py-1.5 text-[12.5px]"
                  style={status === s ? { background: "var(--grad-primary)", borderColor: "transparent", color: "var(--on-accent)" } : { borderColor: "var(--rule)", color: "var(--ink)", background: "transparent" }}>
            {label}{counts[s] != null ? ` (${counts[s]})` : ""}
          </button>
        ))}
      </nav>

      <Card>
        <div className="grid gap-3 sm:grid-cols-3 lg:grid-cols-6">
          <TextField label="Search" value={qInput} onChange={(e) => setQInput(e.target.value)} placeholder="name, roll, email" />
          <SelectField label="Academic year" value={filters.academic_year_id} onChange={setF("academic_year_id")}>
            <option value="">All</option>
            {opts.years.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
          </SelectField>
          <SelectField label="Branch" value={filters.department_id} onChange={setF("department_id")}>
            <option value="">All</option>
            {opts.branches.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
          </SelectField>
          <SelectField label="Batch" value={filters.batch_id} onChange={setF("batch_id")}>
            <option value="">All</option>
            {opts.batches.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
          </SelectField>
          <SelectField label="Year" value={filters.year} onChange={setF("year")}>
            <option value="">All</option>
            {[1, 2, 3, 4, 5].map((y) => <option key={y} value={y}>Year {y}</option>)}
          </SelectField>
          <SelectField label="Section" value={filters.section_id} onChange={setF("section_id")}>
            <option value="">All</option>
            {sections.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
          </SelectField>
        </div>
      </Card>

      {selected.size ? (
        <div className="sticky top-[60px] z-10 flex flex-wrap items-center gap-2 rounded-[var(--radius-lg)] border border-rule glass p-2.5 shadow-lift">
          <span className="text-[13px]"><strong>{selected.size}</strong> selected</span>
          {ACTIONS_FOR[status].map((a) => (
            <Button key={a} variant={a === "approve" || a === "restore" ? "primary" : "secondary"} busy={busy}
                    onClick={() => decide([...selected], a, `${selected.size} student(s)`)}>{VERB[a]} selected</Button>
          ))}
          <Button variant="ghost" onClick={() => setSelected(new Set())}>Clear</Button>
        </div>
      ) : null}

      {error ? <PageError message={error} retry={load} /> : !rows ? <PageLoading /> : !rows.length ? (
        <EmptyState title={`No ${status} students`}>
          {status === "pending" ? "New registrations of your branch appear here." : "Nothing matches these filters."}
        </EmptyState>
      ) : (
        <Card>
          <div className="mb-2 font-mono text-[12px] text-ash">{total} student(s){total > rows.length ? `, showing ${rows.length}` : ""}</div>
          {/* Phones: one card per student, actions in reach of a thumb. */}
          <ul className="m-0 grid list-none gap-2 p-0 md:hidden">
            {rows.map((r) => (
              <li key={r.id} className="rounded-[var(--radius)] border border-rule p-3">
                <div className="flex items-start gap-2.5">
                  <Checkbox aria-label={`Select ${r.full_name}`} label="" checked={selected.has(r.id)} onChange={() => toggle(r.id)} />
                  <span className="h-10 w-10 shrink-0 overflow-hidden rounded-full border border-rule bg-paper">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    {r.photo_url ? <img src={`/api/backend${r.photo_url}`} alt="" className="h-full w-full object-cover" /> : null}
                  </span>
                  <span className="min-w-0 flex-1">
                    <Link href={`/staff/students/${r.id}`} className="block truncate font-semibold text-ink">{r.full_name}</Link>
                    <span className="block font-mono text-[11.5px] text-ash">
                      {r.roll_number} · {r.department ?? "—"} · {r.year ? `Y${r.year}` : "—"}{r.section_name ? `-${r.section_name}` : ""}
                      {r.academic_year ? ` · ${r.academic_year}` : ""}
                    </span>
                    {r.reason && (r.status === "rejected" || r.status === "revoked") ? <span className="block text-[12px] text-ash">{r.reason}</span> : null}
                  </span>
                  <Pill tone={TONE[r.status]}>{r.status}</Pill>
                </div>
                <div className="mt-2.5 flex flex-wrap gap-1.5">
                  {ACTIONS_FOR[r.status].map((a) => (
                    <Button key={a} variant={a === "approve" || a === "restore" ? "primary" : "secondary"} busy={busy}
                            onClick={() => decide([r.id], a, r.full_name)}>{VERB[a]}</Button>
                  ))}
                </div>
              </li>
            ))}
          </ul>
          <div className="hidden overflow-x-auto md:block">
            <table className="w-full min-w-[860px] border-collapse text-[13.5px]">
              <thead>
                <tr>
                  <th className="border-b border-[color-mix(in_srgb,var(--ink)_20%,transparent)] px-2 pb-1.5 text-left">
                    <input type="checkbox" aria-label="Select all" className="h-4 w-4" checked={allTicked}
                           onChange={() => setSelected(allTicked ? new Set() : new Set(rows.map((r) => r.id)))} />
                  </th>
                  {["Student", "Roll no.", "Class / year", "Branch", "Section", "Academic year", "Status", ""].map((h) => (
                    <th key={h} className="label border-b border-[color-mix(in_srgb,var(--ink)_20%,transparent)] px-2 pb-1.5 text-left">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id} className="hover:bg-tint">
                    <td className="border-b border-rule px-2 py-2"><Checkbox aria-label={`Select ${r.full_name}`} label="" checked={selected.has(r.id)} onChange={() => toggle(r.id)} /></td>
                    <td className="border-b border-rule px-2">
                      <div className="flex items-center gap-2.5">
                        <span className="h-9 w-9 shrink-0 overflow-hidden rounded-full border border-rule bg-paper">
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          {r.photo_url ? <img src={`/api/backend${r.photo_url}`} alt="" className="h-full w-full object-cover" /> : null}
                        </span>
                        <span className="min-w-0">
                          <Link href={`/staff/students/${r.id}`} className="block truncate font-semibold text-ink">{r.full_name}</Link>
                          <span className="block truncate text-[12px] text-ash">{r.email}{!r.email_verified ? " · email unverified" : ""}</span>
                        </span>
                      </div>
                    </td>
                    <td className="border-b border-rule px-2 font-mono">{r.roll_number}</td>
                    <td className="border-b border-rule px-2">{r.year ? `Year ${r.year}` : "—"}{r.batch ? <span className="text-ash"> · {r.batch}</span> : null}</td>
                    <td className="border-b border-rule px-2">{r.department ?? "—"}</td>
                    <td className="border-b border-rule px-2">{r.section_name ?? "—"}</td>
                    <td className="border-b border-rule px-2">{r.academic_year ?? "—"}</td>
                    <td className="border-b border-rule px-2">
                      <Pill tone={TONE[r.status]}>{r.status}</Pill>
                      {r.reason && (r.status === "rejected" || r.status === "revoked") ? <div className="max-w-[200px] truncate text-[11.5px] text-ash" title={r.reason}>{r.reason}</div> : null}
                    </td>
                    <td className="border-b border-rule px-2 text-right">
                      <div className="flex justify-end gap-1">
                        {ACTIONS_FOR[r.status].map((a) => (
                          <Button key={a} variant={a === "approve" || a === "restore" ? "primary" : "secondary"} busy={busy}
                                  onClick={() => decide([r.id], a, r.full_name)}>{VERB[a]}</Button>
                        ))}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
