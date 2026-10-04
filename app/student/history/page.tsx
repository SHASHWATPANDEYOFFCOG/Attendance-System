"use client";

import { Suspense, useCallback, useEffect, useMemo, useState } from "react";

import { useRouter, useSearchParams } from "next/navigation";

import { api, download } from "@/lib/client";
import { Page, PageHeader } from "@/components/shell";
import { Card, Mark } from "@/components/ui";
import { Button, SelectField, TextField } from "@/components/forms";
import { EmptyState, PageError, PageLoading } from "@/components/states";
import { useUi } from "@/components/toast";

type Row = { record_id: number; date: string; time: string; subject: string; status: string; method: string; note: string };
type Payload = {
  rows: Row[]; subjects: { id: number; label: string }[]; totals?: Record<string, number>;
  meta: { page: number; total: number; pages: number };
};

const SUMMARY = [
  ["present", "Present", "var(--status-present)"], ["late", "Late", "var(--status-late)"],
  ["absent", "Absent", "var(--status-absent)"], ["on_leave", "On leave", "var(--status-leave)"],
  ["excused", "Excused", "var(--ash)"],
] as const;

const monthLabel = (iso: string) =>
  new Date(`${iso}T00:00:00`).toLocaleDateString([], { month: "long", year: "numeric" });

const STATUSES = ["present", "late", "absent", "on_leave", "excused", "on_duty"];

export default function HistoryPage() {
  return (
    <Suspense fallback={<Page><PageHeader title="Attendance history" /><PageLoading /></Page>}>
      <History />
    </Suspense>
  );
}

function History() {
  const router = useRouter();
  const sp = useSearchParams();
  const { toast } = useUi();
  const [data, setData] = useState<Payload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const filters = useMemo(() => {
    const p = new URLSearchParams();
    for (const k of ["subject_id", "month", "status"]) {
      const v = sp.get(k);
      if (v) p.set(k, v);
    }
    return p;
  }, [sp]);

  const load = useCallback(async () => {
    const p = new URLSearchParams(filters);
    p.set("page", sp.get("page") ?? "1");
    try {
      setData(await api.get<Payload>(`/api/me/history?${p}`));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load your history.");
    }
  }, [filters, sp]);
  useEffect(() => {
    load();
  }, [load]);

  function setFilter(k: string, v: string) {
    const p = new URLSearchParams(sp.toString());
    if (v) p.set(k, v);
    else p.delete(k);
    p.delete("page");
    router.replace(`/student/history?${p}`);
  }

  const page = Number(sp.get("page") ?? 1);

  return (
    <Page>
      <PageHeader
        title="Attendance history"
        subtitle={data ? `${data.meta.total} lecture(s)` : ""}
        actions={
          <Button
            variant="primary"
            busy={busy}
            onClick={async () => {
              setBusy(true);
              try {
                const p = new URLSearchParams(filters);
                p.set("format", "pdf");
                await download(`/api/me/history?${p}`, "attendance-history.pdf");
              } catch (e) {
                toast(e instanceof Error ? e.message : "Could not create the PDF.", "bad");
              } finally {
                setBusy(false);
              }
            }}
          >
            Download PDF
          </Button>
        }
      />
      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <SelectField label="Subject" value={sp.get("subject_id") ?? ""} onChange={(e) => setFilter("subject_id", e.target.value)}>
            <option value="">All subjects</option>
            {data?.subjects.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
          </SelectField>
          <TextField label="Month" type="month" value={sp.get("month") ?? ""} onChange={(e) => setFilter("month", e.target.value)} />
          <SelectField label="Status" value={sp.get("status") ?? ""} onChange={(e) => setFilter("status", e.target.value)}>
            <option value="">Any</option>
            {STATUSES.map((s) => <option key={s} value={s}>{s.replace("_", " ")}</option>)}
          </SelectField>
        </div>
      </Card>
      {error ? <PageError message={error} retry={load} /> : !data ? <PageLoading /> : !data.rows.length ? (
        <EmptyState title="No lectures match">Try a different month or clear the filters.</EmptyState>
      ) : (
        <>
        {data.totals ? (
          <div className="mb-4 grid grid-cols-3 gap-2 sm:grid-cols-5" aria-label="Totals for the lectures shown">
            {SUMMARY.filter(([k]) => k === "present" || k === "late" || k === "absent" || (data.totals?.[k] ?? 0) > 0).map(([k, label, col]) => (
              <div key={k} className="rounded-[3px] border border-rule bg-card py-2 text-center shadow-card">
                <div className="label text-[10.5px]">{label}</div>
                <div className="font-mono text-[22px] font-semibold tnum" style={{ color: col }}>{data.totals?.[k] ?? 0}</div>
              </div>
            ))}
          </div>
        ) : null}
        <Card>
          <ul className="m-0 list-none p-0 md:hidden">
            {data.rows.map((r, i) => (
              <li key={r.record_id}>
              {i === 0 || data.rows[i - 1].date.slice(0, 7) !== r.date.slice(0, 7) ? (
                <div className="label sticky top-[52px] z-[1] -mx-1 mt-2 bg-card px-1 py-1.5 text-[11px] first:mt-0">{monthLabel(r.date)}</div>
              ) : null}
              <div className="flex items-start justify-between gap-3 border-b border-rule py-2.5">
                <div className="min-w-0">
                  <div className="font-mono text-[12px] text-ash">{r.date} · {r.time}</div>
                  <div className="text-[14px] font-semibold">{r.subject}</div>
                  <div className="text-[12.5px] text-ash">{r.method}{r.note ? ` — ${r.note}` : ""}</div>
                </div>
                <Mark status={r.status} />
              </div>
              </li>
            ))}
          </ul>
          <div className="hidden overflow-x-auto md:block">
            <table className="w-full border-collapse text-[13.5px]">
              <thead>
                <tr>
                  {["Date", "Time", "Subject", "Status", "Marked by", "Note"].map((h) => (
                    <th key={h} className="label border-b-2 border-ink px-2 pb-1.5 text-left">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r, i) => [
                  i === 0 || data.rows[i - 1].date.slice(0, 7) !== r.date.slice(0, 7) ? (
                    <tr key={`m-${r.date.slice(0, 7)}`}>
                      <td colSpan={6} className="label border-b border-rule bg-tint px-2 py-1.5 text-[11px]">{monthLabel(r.date)}</td>
                    </tr>
                  ) : null,
                  <tr key={r.record_id} className="hover:bg-tint">
                    <td className="border-b border-rule px-2 py-1.5 font-mono tnum">{r.date}</td>
                    <td className="border-b border-rule px-2 font-mono tnum">{r.time}</td>
                    <td className="border-b border-rule px-2">{r.subject}</td>
                    <td className="border-b border-rule px-2"><span className="inline-flex items-center gap-1.5"><Mark status={r.status} />{r.status.replace("_", " ")}</span></td>
                    <td className="border-b border-rule px-2 text-ash">{r.method}</td>
                    <td className="border-b border-rule px-2 text-ash">{r.note}</td>
                  </tr>,
                ])}
              </tbody>
            </table>
          </div>
          {data.meta.pages > 1 ? (
            <nav className="mt-3 flex items-center justify-between" aria-label="Pages">
              <Button disabled={page <= 1} onClick={() => setFilter("page", String(page - 1))}>Previous</Button>
              <span className="font-mono text-[12px] text-ash">page {page} of {data.meta.pages}</span>
              <Button disabled={page >= data.meta.pages} onClick={() => { const p = new URLSearchParams(sp.toString()); p.set("page", String(page + 1)); router.replace(`/student/history?${p}`); }}>Next</Button>
            </nav>
          ) : null}
        </Card>
        </>
      )}
    </Page>
  );
}
