"use client";

/**
 * Bulk import: check first (dry run), see every bad row with its reason, fix, import. The error
 * report downloads as a CSV the office can correct and re-upload.
 */
import { useState } from "react";

import Link from "next/link";

import { api, download, saveBlob } from "@/lib/client";
import { Page, PageHeader } from "@/components/shell";
import { Banner, Card, CardHeader, StatTile } from "@/components/ui";
import { Button, Checkbox, FormError } from "@/components/forms";
import { useUi } from "@/components/toast";

type Result = {
  rows: number;
  valid: number;
  created: number;
  dry_run: boolean;
  errors: { row: number; field: string; value: string; message: string }[];
};

function errorsCsv(errors: Result["errors"]) {
  const esc = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  return ["row,field,value,problem", ...errors.map((e) => [e.row, e.field, e.value, e.message].map(esc).join(","))].join("\n");
}

export default function ImportPage() {
  const { toast } = useUi();
  const [file, setFile] = useState<File | null>(null);
  const [invite, setInvite] = useState(true);
  const [result, setResult] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"check" | "import" | null>(null);

  async function run(dry: boolean) {
    if (!file) return setError("Choose a CSV or Excel file first.");
    setBusy(dry ? "check" : "import");
    setError(null);
    const fd = new FormData();
    fd.append("file", file);
    fd.append("dry_run", String(dry));
    fd.append("send_invites", String(invite));
    try {
      const r = await api.upload<Result>("/api/students/import", fd);
      setResult(r);
      if (!dry) toast(`${r.created} student(s) imported.`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Import failed.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <Page>
      <PageHeader
        title="Import students"
        subtitle="CSV or Excel (.xlsx), up to 2000 rows"
        actions={<Link href="/staff/students" className="display rounded-[3px] border border-ink px-3.5 py-2 text-[12px] text-ink no-underline hover:bg-tint">Back to students</Link>}
      />
      <Card className="mb-4">
        <CardHeader title="1. Get the template" />
        <p className="mt-0 text-[14px]">
          One row per student. Branch is the code (e.g. <code>CSE</code>), batch is the label (e.g.{" "}
          <code>2023-2027</code>), section is the letter. Students can only be imported into classes you teach.
        </p>
        <Button onClick={() => download("/api/students/import/template", "students-template.csv").catch((e) => toast(e.message, "bad"))}>
          Download CSV template
        </Button>
      </Card>

      <Card className="mb-4">
        <CardHeader title="2. Check and import" />
        <FormError>{error}</FormError>
        <div className="grid gap-3">
          <label className="display inline-flex w-fit cursor-pointer rounded-[3px] border border-ink px-3.5 py-2 text-[12px] text-ink hover:bg-tint">
            {file ? `File: ${file.name}` : "Choose file"}
            <input type="file" accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" className="sr-only"
                   onChange={(e) => { setFile(e.target.files?.[0] ?? null); setResult(null); }} />
          </label>
          <Checkbox label="Email each new student a link to set their password" checked={invite} onChange={(e) => setInvite(e.target.checked)} />
          <div className="flex flex-wrap gap-2">
            <Button onClick={() => run(true)} busy={busy === "check"} disabled={!file || busy !== null}>Check file</Button>
            <Button variant="primary" onClick={() => run(false)} busy={busy === "import"} disabled={!file || busy !== null}>
              Import valid rows
            </Button>
          </div>
        </div>
      </Card>

      {result ? (
        <>
          {result.dry_run ? (
            <Banner>This was a check only — nothing was saved. Fix the rows below or import the valid ones.</Banner>
          ) : null}
          <div className="mb-4 grid grid-cols-3 gap-4">
            <StatTile label="Rows read" value={result.rows} />
            <StatTile label={result.dry_run ? "Would import" : "Imported"} value={result.dry_run ? result.valid : result.created} tone="verdant" />
            <StatTile label="Problems" value={result.errors.length} tone={result.errors.length ? "oxide" : "ink"} />
          </div>
          {result.errors.length ? (
            <Card>
              <CardHeader
                title="Rows with problems"
                meta={<Button onClick={() => saveBlob(new Blob([errorsCsv(result.errors)], { type: "text/csv" }), "import-errors.csv")}>Download error report</Button>}
              />
              <div className="overflow-x-auto">
                <table className="w-full min-w-[560px] border-collapse text-[13.5px]">
                  <thead>
                    <tr>
                      {["Row", "Field", "Value", "Problem"].map((h) => (
                        <th key={h} className="label border-b-2 border-ink px-2 pb-1.5 text-left">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {result.errors.map((e, i) => (
                      <tr key={i}>
                        <td className="border-b border-rule px-2 py-1.5 font-mono">{e.row}</td>
                        <td className="border-b border-rule px-2 font-mono">{e.field}</td>
                        <td className="border-b border-rule px-2 font-mono text-ash">{e.value}</td>
                        <td className="border-b border-rule px-2 text-oxide">{e.message}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          ) : null}
        </>
      ) : null}
    </Page>
  );
}
