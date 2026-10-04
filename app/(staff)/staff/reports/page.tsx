"use client";

/**
 * Summary reports. One table renderer for every report type: the server sends columns + rows,
 * and the export buttons request the SAME report with ?format=, so a download always matches
 * the table on screen.
 */
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { api, download } from "@/lib/client";
import { Page, PageHeader } from "@/components/shell";
import { Card, Mark } from "@/components/ui";
import { Button, SelectField, TextField } from "@/components/forms";
import { EmptyState, PageError, PageLoading } from "@/components/states";
import { useUi } from "@/components/toast";

type Report = { title: string; meta: string[]; columns: { key: string; label: string }[]; rows: Record<string, unknown>[] };
type Opt = { id: number; label: string };

const KINDS = [
  ["daily", "Daily"], ["monthly", "Monthly"], ["subject-wise", "Subject-wise"],
  ["student-wise", "Student-wise"], ["defaulter-list", "Defaulters"],
] as const;
type Kind = (typeof KINDS)[number][0];

export default function SummaryReportsPage() {
  return (
    <Suspense fallback={<Page wide><PageHeader title="Reports" /><PageLoading /></Page>}>
      <Reports />
    </Suspense>
  );
}

function Reports() {
  const router = useRouter();
  const sp = useSearchParams();
  const { toast } = useUi();
  const kind = (KINDS.some(([k]) => k === sp.get("kind")) ? sp.get("kind") : "daily") as Kind;
  const [data, setData] = useState<Report | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sections, setSections] = useState<Opt[]>([]);
  const [subjects, setSubjects] = useState<Opt[]>([]);
  const [studentQuery, setStudentQuery] = useState("");
  const [students, setStudents] = useState<Opt[]>([]);
  const [busy, setBusy] = useState<string | null>(null);

  const params = useMemo(() => {
    const p = new URLSearchParams();
    for (const k of ["date_from", "date_to", "section_id", "subject_id", "month", "threshold"]) {
      const v = sp.get(k);
      if (v) p.set(k, v);
    }
    return p;
  }, [sp]);
  const studentId = sp.get("student_id");
  const path = kind === "student-wise" ? (studentId ? `/api/reports/student-wise/${studentId}` : null) : `/api/reports/${kind}`;

  const load = useCallback(async () => {
    if (!path) return setData(null);
    setData(null);
    try {
      setData(await api.get<Report>(`${path}?${params}`));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load the report.");
    }
  }, [path, params]);
  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    api.get<Opt[]>("/api/sections?mine=true").then(setSections).catch(() => {});
    api.get<{ id: number; code: string; name: string }[]>("/api/subjects")
      .then((s) => setSubjects(s.map((x) => ({ id: x.id, label: `${x.code} ${x.name}` })))).catch(() => {});
  }, []);
  useEffect(() => {
    if (kind !== "student-wise" || studentQuery.trim().length < 2) return setStudents([]);
    const t = setTimeout(() => {
      api.get<{ rows: { id: number; full_name: string; roll_number: string | null }[] }>(`/api/students?q=${encodeURIComponent(studentQuery)}&page_size=20`)
        .then((r) => setStudents(r.rows.map((s) => ({ id: s.id, label: `${s.full_name} · ${s.roll_number ?? ""}` })))).catch(() => {});
    }, 250);
    return () => clearTimeout(t);
  }, [studentQuery, kind]);

  function set(k: string, v: string) {
    const p = new URLSearchParams(sp.toString());
    if (v) p.set(k, v);
    else p.delete(k);
    router.replace(`/staff/reports?${p}`);
  }

  async function exportAs(fmt: string) {
    if (!path) return;
    setBusy(fmt);
    try {
      const p = new URLSearchParams(params);
      p.set("format", fmt);
      await download(`${path}?${p}`, `${kind}.${fmt}`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Export failed.", "bad");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Page wide>
      <PageHeader title="Reports" subtitle={data?.title ?? ""}
                  actions={<Link href="/reports" className="display rounded-[var(--radius)] border border-ink px-3.5 py-2 text-[13px] text-ink no-underline hover:bg-tint">Record-level report</Link>} />
      <nav aria-label="Report type" className="-mx-1 mb-4 overflow-x-auto pb-1">
        <ul className="m-0 flex min-w-max list-none gap-1 p-0 px-1">
          {KINDS.map(([k, l]) => (
            <li key={k}>
              <button type="button" onClick={() => set("kind", k)} aria-current={kind === k ? "page" : undefined}
                      className="display cursor-pointer rounded-[var(--radius)] border px-3 py-1.5 text-[12.5px]"
                      style={kind === k ? { background: "var(--grad-primary)", borderColor: "transparent", color: "var(--on-accent)" } : { borderColor: "var(--rule)", color: "var(--ink)", background: "transparent" }}>
                {l}
              </button>
            </li>
          ))}
        </ul>
      </nav>
      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {kind === "monthly" ? (
            <TextField label="Month" type="month" value={sp.get("month") ?? ""} onChange={(e) => set("month", e.target.value)} />
          ) : (
            <>
              <TextField label="From" type="date" value={sp.get("date_from") ?? ""} onChange={(e) => set("date_from", e.target.value)} />
              <TextField label="To" type="date" value={sp.get("date_to") ?? ""} onChange={(e) => set("date_to", e.target.value)} />
            </>
          )}
          {kind === "student-wise" ? (
            <>
              <TextField label="Find student" type="search" value={studentQuery} onChange={(e) => setStudentQuery(e.target.value)} placeholder="Name or roll number" />
              <SelectField label="Student" value={studentId ?? ""} onChange={(e) => set("student_id", e.target.value)}>
                <option value="">{students.length ? "Select…" : "Search first"}</option>
                {students.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
              </SelectField>
            </>
          ) : (
            <SelectField label="Class" value={sp.get("section_id") ?? ""} onChange={(e) => set("section_id", e.target.value)}>
              <option value="">All my classes</option>
              {sections.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
            </SelectField>
          )}
          {kind === "daily" || kind === "monthly" ? (
            <SelectField label="Subject" value={sp.get("subject_id") ?? ""} onChange={(e) => set("subject_id", e.target.value)}>
              <option value="">All subjects</option>
              {subjects.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
            </SelectField>
          ) : null}
          {kind === "defaulter-list" ? (
            <TextField label="Below %" type="number" value={sp.get("threshold") ?? ""} placeholder="minimum" onChange={(e) => set("threshold", e.target.value)} />
          ) : null}
        </div>
      </Card>

      {!path ? <EmptyState title="Choose a student">Search for a student above to see their report.</EmptyState>
        : error ? <PageError message={error} retry={load} /> : !data ? <PageLoading /> : (
        <Card>
          <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
            <div className="text-[12.5px] text-ash">{data.meta.map((m) => <div key={m}>{m}</div>)}</div>
            <div className="flex gap-2">
              {(["csv", "xlsx", "pdf"] as const).map((f) => (
                <Button key={f} busy={busy === f} onClick={() => exportAs(f)}>{f === "xlsx" ? "Excel" : f.toUpperCase()}</Button>
              ))}
            </div>
          </div>
          {!data.rows.length ? <EmptyState title="No data for these filters" /> : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] border-collapse text-[13.5px]">
                <thead>
                  <tr>{data.columns.map((c) => <th key={c.key} className="label border-b border-[color-mix(in_srgb,var(--ink)_20%,transparent)] px-2 pb-1.5 text-left">{c.label}</th>)}</tr>
                </thead>
                <tbody>
                  {data.rows.map((r, i) => (
                    <tr key={i} className={`hover:bg-tint ${r.subject === "OVERALL" ? "font-semibold" : ""}`}>
                      {data.columns.map((c) => {
                        const v = r[c.key];
                        const isPct = c.key === "pct" && typeof v === "number";
                        return (
                          <td key={c.key} className={`border-b border-rule px-2 py-1.5 ${typeof v === "number" ? "font-mono tnum" : ""}`}
                              style={isPct && (v as number) < 75 ? { color: "var(--oxide)" } : undefined}>
                            {c.key === "status" && typeof v === "string" ? <Mark status={v} /> : c.key === "student" && r.student_id ? (
                              <Link href={`/staff/students/${r.student_id}`} className="text-ink">{String(v)}</Link>
                            ) : v == null ? "—" : isPct ? `${v}%` : String(v)}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}
    </Page>
  );
}
