"use client";

/**
 * Student directory. Every row returned is already scoped by the server to the classes this
 * teacher teaches (or the HOD's branch); filters narrow it further.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { api, ApiFailure } from "@/lib/client";
import { Page, PageHeader } from "@/components/shell";
import { Card, Pill } from "@/components/ui";
import { Button, FormError, SelectField, TextField } from "@/components/forms";
import { EmptyState, PageError, PageLoading } from "@/components/states";
import { useUi } from "@/components/toast";
import { Suspense } from "react";

type Row = {
  id: number; full_name: string; email: string | null; phone: string | null; roll_number: string | null;
  department: string | null; batch: string | null; year: number | null; section: string | null;
  status: string; email_verified: boolean; has_face: boolean; attendance_pct: number | null;
};
type Listing = { rows: Row[]; meta: { page: number; total: number; pages: number }; threshold_pct: number };
type Opt = { id: number; label?: string; code?: string };

const FILTERS = ["q", "department_id", "batch_id", "year", "section_id", "status", "min_pct", "max_pct"] as const;

export default function StudentsPage() {
  return (
    <Suspense fallback={<Page wide><PageHeader title="Students" /><PageLoading /></Page>}>
      <Students />
    </Suspense>
  );
}

function Students() {
  const router = useRouter();
  const sp = useSearchParams();
  const [data, setData] = useState<Listing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [depts, setDepts] = useState<Opt[]>([]);
  const [batches, setBatches] = useState<Opt[]>([]);
  const [sections, setSections] = useState<Opt[]>([]);
  const [adding, setAdding] = useState(false);
  const [q, setQ] = useState(sp.get("q") ?? "");

  const query = useMemo(() => {
    const p = new URLSearchParams();
    for (const k of FILTERS) {
      const v = sp.get(k);
      if (v) p.set(k, v);
    }
    p.set("page", sp.get("page") ?? "1");
    return p.toString();
  }, [sp]);

  const load = useCallback(async () => {
    try {
      setData(await api.get<Listing>(`/api/students?${query}`));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load students.");
    }
  }, [query]);

  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    api.get<Opt[]>("/api/departments").then(setDepts).catch(() => {});
    api.get<Opt[]>("/api/batches").then(setBatches).catch(() => {});
    api.get<Opt[]>("/api/sections?mine=true").then(setSections).catch(() => {});
  }, []);

  function setFilter(key: string, value: string) {
    const p = new URLSearchParams(sp.toString());
    if (value) p.set(key, value);
    else p.delete(key);
    p.delete("page");
    router.replace(`/staff/students?${p.toString()}`);
  }

  // Debounced search so typing a roll number does not fire a request per keystroke.
  useEffect(() => {
    if ((sp.get("q") ?? "") === q) return;
    const t = setTimeout(() => setFilter("q", q.trim()), 350);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [q]);

  const page = Number(sp.get("page") ?? 1);

  return (
    <Page wide>
      <PageHeader
        title="Students"
        subtitle={data ? `${data.meta.total} student(s) in your classes` : "loading"}
        actions={
          <>
            <Link href="/staff/students/import" className="display rounded-[var(--radius)] border border-ink px-3.5 py-2 text-[13px] text-ink no-underline hover:bg-tint">
              Import CSV / Excel
            </Link>
            <Button variant="primary" onClick={() => setAdding((a) => !a)}>
              {adding ? "Close" : "+ Add student"}
            </Button>
          </>
        }
      />

      {adding ? <AddStudent sections={sections} onDone={() => { setAdding(false); load(); }} /> : null}

      <Card className="mb-4">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <TextField label="Search" placeholder="Name, roll no, email" value={q} onChange={(e) => setQ(e.target.value)} type="search" />
          <SelectField label="Branch" value={sp.get("department_id") ?? ""} onChange={(e) => setFilter("department_id", e.target.value)}>
            <option value="">All</option>
            {depts.map((d) => <option key={d.id} value={d.id}>{d.code}</option>)}
          </SelectField>
          <SelectField label="Batch" value={sp.get("batch_id") ?? ""} onChange={(e) => setFilter("batch_id", e.target.value)}>
            <option value="">All</option>
            {batches.map((b) => <option key={b.id} value={b.id}>{b.label}</option>)}
          </SelectField>
          <SelectField label="Year" value={sp.get("year") ?? ""} onChange={(e) => setFilter("year", e.target.value)}>
            <option value="">All</option>
            {[1, 2, 3, 4, 5].map((y) => <option key={y} value={y}>Year {y}</option>)}
          </SelectField>
          <SelectField label="Class" value={sp.get("section_id") ?? ""} onChange={(e) => setFilter("section_id", e.target.value)}>
            <option value="">All my classes</option>
            {sections.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
          </SelectField>
          <SelectField label="Status" value={sp.get("status") ?? ""} onChange={(e) => setFilter("status", e.target.value)}>
            <option value="">Any</option>
            <option value="approved">Approved</option>
            <option value="pending">Pending</option>
            <option value="rejected">Rejected</option>
          </SelectField>
          <SelectField label="Attendance" value={sp.get("max_pct") ? `below:${sp.get("max_pct")}` : sp.get("min_pct") ? `above:${sp.get("min_pct")}` : ""}
                       onChange={(e) => {
                         const [kind, v] = e.target.value.split(":");
                         const p = new URLSearchParams(sp.toString());
                         p.delete("min_pct"); p.delete("max_pct"); p.delete("page");
                         if (kind === "below") p.set("max_pct", String(Number(v) - 0.01));
                         if (kind === "above") p.set("min_pct", v);
                         router.replace(`/staff/students?${p.toString()}`);
                       }}>
            <option value="">Any</option>
            <option value={`below:${data?.threshold_pct ?? 75}`}>Below {data?.threshold_pct ?? 75}% (defaulters)</option>
            <option value={`above:${data?.threshold_pct ?? 75}`}>{data?.threshold_pct ?? 75}% and above</option>
          </SelectField>
        </div>
      </Card>

      {error ? <PageError message={error} retry={load} /> : !data ? <PageLoading /> : data.rows.length === 0 ? (
        <EmptyState title="No students match">Try clearing a filter, or add students to your classes.</EmptyState>
      ) : (
        <Card>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[720px] border-collapse text-[13.5px]">
              <thead>
                <tr>
                  {["Student", "Roll no", "Class", "Status", "Face", "Attendance"].map((h) => (
                    <th key={h} className={`label border-b border-[color-mix(in_srgb,var(--ink)_20%,transparent)] px-2 pb-1.5 ${h === "Attendance" ? "text-right" : "text-left"}`}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.id} className="hover:bg-tint">
                    <td className="border-b border-rule px-2 py-2">
                      <Link href={`/staff/students/${r.id}`} className="font-semibold text-ink">{r.full_name}</Link>
                      <div className="font-mono text-[11px] text-ash">{r.email}</div>
                    </td>
                    <td className="border-b border-rule px-2 font-mono">{r.roll_number}</td>
                    <td className="border-b border-rule px-2">{r.section ?? "—"}</td>
                    <td className="border-b border-rule px-2">
                      <Pill tone={r.status === "approved" ? "ok" : r.status === "rejected" ? "bad" : "warn"}>{r.status}</Pill>
                      {r.status === "pending" && !r.email_verified ? <span className="ml-1 text-[11px] text-ash">email unverified</span> : null}
                    </td>
                    <td className="border-b border-rule px-2">{r.has_face ? <Pill tone="ok">enrolled</Pill> : <span className="text-ash">—</span>}</td>
                    <td className={`border-b border-rule px-2 text-right font-mono tnum ${r.attendance_pct != null && r.attendance_pct < data.threshold_pct ? "text-oxide" : ""}`}>
                      {r.attendance_pct == null ? "—" : `${r.attendance_pct}%`}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {data.meta.pages > 1 ? (
            <nav aria-label="Pages" className="mt-3 flex items-center justify-between text-[13px]">
              <Button disabled={page <= 1} onClick={() => setFilter("page", String(page - 1))}>Previous</Button>
              <span className="font-mono text-ash">page {page} of {data.meta.pages}</span>
              <Button disabled={page >= data.meta.pages} onClick={() => {
                const p = new URLSearchParams(sp.toString()); p.set("page", String(page + 1)); router.replace(`/staff/students?${p}`);
              }}>Next</Button>
            </nav>
          ) : null}
        </Card>
      )}
    </Page>
  );
}

function AddStudent({ sections, onDone }: { sections: Opt[]; onDone: () => void }) {
  const { toast } = useUi();
  const [f, setF] = useState({ full_name: "", email: "", mobile: "", roll_number: "", enrollment_no: "", section_id: "" });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => {
    setF((x) => ({ ...x, [k]: e.target.value }));
    setErrors(({ [k]: _d, ...rest }) => rest);
  };
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    for (const [k, v] of Object.entries(f)) if (!v.trim()) errs[k] = "Required.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    setFormError(null);
    try {
      await api.post("/api/students", { ...f, section_id: Number(f.section_id) });
      toast("Student added. They were emailed a link to set their password.");
      onDone();
    } catch (err) {
      const d = err instanceof ApiFailure ? err.detail : undefined;
      if (d && typeof d.field === "string" && d.field in f) setErrors({ [d.field]: err instanceof Error ? err.message : "" });
      else setFormError(err instanceof Error ? err.message : "Could not add the student.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card className="mb-4">
      <h2 className="display m-0 mb-3 text-[15px] text-ash">Add a student</h2>
      <FormError>{formError}</FormError>
      <form onSubmit={submit} noValidate className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <TextField label="Full name" required value={f.full_name} onChange={set("full_name")} error={errors.full_name} />
        <TextField label="Email" type="email" required value={f.email} onChange={set("email")} error={errors.email} />
        <TextField label="Mobile" type="tel" required value={f.mobile} onChange={set("mobile")} error={errors.mobile} />
        <TextField label="Roll number" required value={f.roll_number} onChange={set("roll_number")} error={errors.roll_number} />
        <TextField label="Enrollment no." required value={f.enrollment_no} onChange={set("enrollment_no")} error={errors.enrollment_no} />
        <SelectField label="Class" required value={f.section_id} onChange={set("section_id")} error={errors.section_id}>
          <option value="">Select…</option>
          {sections.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
        </SelectField>
        <div className="sm:col-span-2 lg:col-span-3">
          <Button type="submit" variant="primary" busy={busy}>Add student</Button>
        </div>
      </form>
    </Card>
  );
}
