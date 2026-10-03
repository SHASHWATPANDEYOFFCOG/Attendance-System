/**
 * Reports: filter builder, paginated table, exports.
 *
 * Filter state lives in the URL, not in React state. That makes a filtered report
 * bookmarkable and shareable, survives a reload, and lets the export links carry the exact
 * same query string — so an export can never disagree with the table above it.
 *
 * Next 16: `searchParams` is a Promise.
 */
import Link from "next/link";

import { apiGet } from "@/lib/api";
import { Banner, Card, CardHeader, Empty, Mark, Pill } from "@/components/ui";

export const dynamic = "force-dynamic";

type Row = {
  record_id: number;
  date: string | null;
  time: string | null;
  student: string;
  roll_number: string | null;
  subject_code: string | null;
  section: string | null;
  status: string;
  overridden: boolean;
  confidence: number | null;
  source: string | null;
};

type Report = { rows: Row[]; meta: { page: number; page_size: number; total: number; pages: number } };
type Options = {
  departments: { id: number; label: string }[];
  subjects: { id: number; label: string }[];
  sections: { id: number; label: string }[];
  statuses: string[];
};

/** Mirrors EXPORT_ROW_LIMITS["pdf"] in app/reports_service.py. */
const PDF_ROW_LIMIT = 1000;

const FILTER_KEYS = [
  "date_from", "date_to", "department_id", "section_id", "subject_id",
  "student_id", "status", "search",
] as const;

function buildQuery(sp: Record<string, string | undefined>, extra: Record<string, string> = {}) {
  const q = new URLSearchParams();
  for (const k of FILTER_KEYS) if (sp[k]) q.set(k, sp[k]!);
  for (const [k, v] of Object.entries(extra)) q.set(k, v);
  return q.toString();
}

export default async function ReportsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const sp = await searchParams;
  const page = Math.max(1, Number(sp.page ?? 1) || 1);
  const pageSize = Math.min(200, Math.max(10, Number(sp.page_size ?? 50) || 50));

  const query = buildQuery(sp, { page: String(page), page_size: String(pageSize) });
  const exportQuery = buildQuery(sp);

  let report: Report | null = null;
  let options: Options | null = null;
  let error: string | null = null;
  try {
    [report, options] = await Promise.all([
      apiGet(`/api/reports/attendance?${query}`) as Promise<Report>,
      apiGet("/api/reports/options") as Promise<Options>,
    ]);
  } catch (e) {
    error = e instanceof Error ? e.message : "Could not load the report.";
  }

  const meta = report?.meta;
  const pageLink = (n: number) => `/reports?${buildQuery(sp, { page: String(n), page_size: String(pageSize) })}`;

  return (
    <main className="relative z-[1] mx-auto max-w-[1240px] px-4 pb-16 pt-6 md:px-5">
      <header className="mb-5 flex flex-wrap items-end justify-between gap-4 border-b-2 border-ink pb-3">
        <div>
          <h1 className="display m-0 text-[26px]">Reports</h1>
          <p className="mt-0.5 font-mono text-xs text-ash">
            {meta ? `${meta.total} row(s) · page ${meta.page} of ${Math.max(1, meta.pages)}` : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href="/dashboard"
            className="display rounded-[3px] border border-ink px-3.5 py-2 text-[12px] text-ink hover:bg-tint"
          >
            Dashboard
          </Link>
        </div>
      </header>

      {error ? (
        <Banner bad>
          <strong className="label mb-0.5 block">Could not load</strong>
          {error}
        </Banner>
      ) : null}

      {/* ------------------------------------------------------------ filters */}
      <Card className="mb-4">
        <CardHeader title="Filters" />
        {/* A plain GET form: no JavaScript, and the resulting URL is the shareable report. */}
        <form method="GET" action="/reports" className="grid gap-3 md:grid-cols-3 lg:grid-cols-4">
          <label className="block">
            <span className="label block">From</span>
            <input type="date" name="date_from" defaultValue={sp.date_from ?? ""}
                   className="w-full rounded-[3px] border border-rule bg-card px-2.5 py-2 text-[14px] text-ink" />
          </label>
          <label className="block">
            <span className="label block">To</span>
            <input type="date" name="date_to" defaultValue={sp.date_to ?? ""}
                   className="w-full rounded-[3px] border border-rule bg-card px-2.5 py-2 text-[14px] text-ink" />
          </label>

          <label className="block">
            <span className="label block">Department</span>
            <select name="department_id" defaultValue={sp.department_id ?? ""}
                    className="w-full rounded-[3px] border border-rule bg-card px-2.5 py-2 text-[14px] text-ink">
              <option value="">All</option>
              {options?.departments.map((d) => (
                <option key={d.id} value={d.id}>{d.label}</option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="label block">Subject</span>
            <select name="subject_id" defaultValue={sp.subject_id ?? ""}
                    className="w-full rounded-[3px] border border-rule bg-card px-2.5 py-2 text-[14px] text-ink">
              <option value="">All</option>
              {options?.subjects.map((s) => (
                <option key={s.id} value={s.id}>{s.label}</option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="label block">Section</span>
            <select name="section_id" defaultValue={sp.section_id ?? ""}
                    className="w-full rounded-[3px] border border-rule bg-card px-2.5 py-2 text-[14px] text-ink">
              <option value="">All</option>
              {options?.sections.map((s) => (
                <option key={s.id} value={s.id}>{s.label}</option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="label block">Status</span>
            <select name="status" defaultValue={sp.status ?? ""}
                    className="w-full rounded-[3px] border border-rule bg-card px-2.5 py-2 text-[14px] text-ink">
              <option value="">Any</option>
              {options?.statuses.map((s) => (
                <option key={s} value={s}>{s.replace(/_/g, " ")}</option>
              ))}
            </select>
          </label>

          <label className="block">
            <span className="label block">Student</span>
            <input name="search" defaultValue={sp.search ?? ""} placeholder="name or roll"
                   className="w-full rounded-[3px] border border-rule bg-card px-2.5 py-2 text-[14px] text-ink" />
          </label>

          <div className="flex items-end gap-2">
            <button type="submit"
                    className="display cursor-pointer rounded-[3px] border px-3.5 py-2 text-[12px]"
                    style={{ background: "var(--ink)", borderColor: "var(--ink)", color: "var(--card)" }}>
              Apply
            </button>
            <Link href="/reports"
                  className="display rounded-[3px] border border-rule px-3.5 py-2 text-[12px] text-ash hover:bg-tint">
              Clear
            </Link>
          </div>
        </form>
      </Card>

      {/* ------------------------------------------------------------- table */}
      <Card ruled>
        <header className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <h2 className="display m-0 text-[15px] text-ash">Attendance records</h2>
          <div className="flex flex-wrap items-center gap-2">
            <span className="label">Export</span>
            {(["csv", "xlsx", "pdf"] as const).map((fmt) => {
              // PDF rendering is superlinear in row count, so the server caps it at 1 000.
              // Say so here rather than let the click return a 413.
              const tooBig = fmt === "pdf" && (meta?.total ?? 0) > PDF_ROW_LIMIT;
              return (
                <a
                  key={fmt}
                  // Same filters as the table above, so the two can never disagree.
                  href={`/api/backend/api/reports/export?format=${fmt}&${exportQuery}`}
                  aria-disabled={tooBig}
                  title={
                    tooBig
                      ? `PDF is limited to ${PDF_ROW_LIMIT.toLocaleString()} rows — narrow the filters, or use XLSX`
                      : undefined
                  }
                  className={
                    "display rounded-[3px] border border-rule px-3 py-1.5 text-[11px] hover:bg-tint " +
                    (tooBig ? "pointer-events-none opacity-40 text-ash" : "text-ink")
                  }
                >
                  {fmt.toUpperCase()}
                </a>
              );
            })}
            {(meta?.total ?? 0) > PDF_ROW_LIMIT ? (
              <span className="text-[11.5px] text-ash">
                PDF needs ≤ {PDF_ROW_LIMIT.toLocaleString()} rows
              </span>
            ) : null}
          </div>
        </header>

        {report && report.rows.length ? (
          <>
            <div className="overflow-x-auto">
              <table className="w-full border-collapse text-[13.5px]">
                <thead>
                  <tr>
                    {["", "Date", "Time", "Roll", "Student", "Subject", "Section", "Status", "Source"].map((h) => (
                      <th key={h} className="label border-b-2 border-ink px-2 pb-1.5 text-left whitespace-nowrap">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {report.rows.map((r) => (
                    <tr key={r.record_id} className="hover:bg-tint">
                      <td className="h-[30px] border-b border-rule px-2"><Mark status={r.status} /></td>
                      <td className="border-b border-rule px-2 font-mono text-[12.5px] tnum">{r.date}</td>
                      <td className="border-b border-rule px-2 font-mono text-[12.5px] tnum">{r.time}</td>
                      <td className="border-b border-rule px-2 font-mono text-[12.5px]">{r.roll_number}</td>
                      <td className="border-b border-rule px-2">{r.student}</td>
                      <td className="border-b border-rule px-2 font-mono text-[12.5px]">{r.subject_code}</td>
                      <td className="border-b border-rule px-2">{r.section}</td>
                      <td className="border-b border-rule px-2 whitespace-nowrap">
                        {r.status.replace(/_/g, " ")}
                        {r.overridden ? <span className="ml-1"><Pill>overridden</Pill></span> : null}
                      </td>
                      <td className="border-b border-rule px-2 text-ash">{r.source}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {meta && meta.pages > 1 ? (
              <nav className="mt-3 flex flex-wrap items-center gap-2" aria-label="Pagination">
                <Link
                  href={pageLink(Math.max(1, meta.page - 1))}
                  aria-disabled={meta.page <= 1}
                  className="display rounded-[3px] border border-rule px-3 py-1.5 text-[11px] text-ink hover:bg-tint aria-disabled:opacity-40"
                >
                  Previous
                </Link>
                <span className="font-mono text-[12px] tnum text-ash">
                  page {meta.page} of {meta.pages}
                </span>
                <Link
                  href={pageLink(Math.min(meta.pages, meta.page + 1))}
                  aria-disabled={meta.page >= meta.pages}
                  className="display rounded-[3px] border border-rule px-3 py-1.5 text-[11px] text-ink hover:bg-tint aria-disabled:opacity-40"
                >
                  Next
                </Link>
              </nav>
            ) : null}
          </>
        ) : (
          <Empty>
            No records match these filters. Try widening the date range, or{" "}
            <Link href="/reports" className="underline">clear the filters</Link>.
          </Empty>
        )}
      </Card>
    </main>
  );
}
