"use client";

/** Leave applications: apply (days or specific lectures), track, edit or cancel while pending. */
import { useCallback, useEffect, useState } from "react";

import { api, ApiFailure } from "@/lib/client";
import { Page, PageHeader } from "@/components/shell";
import { Banner, Card, CardHeader, Pill } from "@/components/ui";
import { Button, Checkbox, FormError, SelectField, TextArea, TextField } from "@/components/forms";
import { EmptyState, PageError, PageLoading } from "@/components/states";
import { AttachmentLink } from "@/components/thread";
import { useUi } from "@/components/toast";

type Leave = {
  id: number; type: string; type_label: string; from_date: string; to_date: string;
  session_ids: number[] | null; lectures?: { id: number; date: string; subject: string }[];
  reason: string; explanation: string | null; status: string; remark: string | null;
  decided_by?: string | null; created_at: string; attachment: { url: string; name: string } | null;
};
type Lecture = { id: number; date: string; subject: string; status: string | null };

const TYPES: [string, string][] = [
  ["medical", "Medical"], ["personal", "Personal"], ["family_emergency", "Family emergency"],
  ["on_duty", "Duty / event"], ["other", "Other"],
];
const today = () => new Date().toLocaleDateString("en-CA");

export default function LeavesPage() {
  const { toast, confirm } = useUi();
  const [rows, setRows] = useState<Leave[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Leave | "new" | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await api.get<Leave[]>("/api/me/leaves"));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load your leaves.");
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  async function cancel(l: Leave) {
    if (!(await confirm({ title: "Cancel this application?", body: `${l.type_label} leave, ${l.from_date}${l.to_date !== l.from_date ? ` to ${l.to_date}` : ""}.`, confirmLabel: "Cancel application", danger: true }))) return;
    try {
      await api.del(`/api/me/leaves/${l.id}`);
      toast("Application cancelled.");
      load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not cancel.", "bad");
    }
  }

  return (
    <Page>
      <PageHeader
        title="Leave"
        subtitle="Apply in advance, or within the allowed days after an absence"
        actions={editing ? null : <Button variant="primary" onClick={() => setEditing("new")}>+ Apply for leave</Button>}
      />
      {editing ? (
        <LeaveForm key={editing === "new" ? "new" : editing.id} leave={editing === "new" ? null : editing}
                   onDone={() => { setEditing(null); load(); }} onCancel={() => setEditing(null)} />
      ) : null}
      {error ? <PageError message={error} retry={load} /> : !rows ? <PageLoading /> : !rows.length ? (
        <EmptyState title="No leave applications yet" />
      ) : (
        <div className="grid gap-3">
          {rows.map((l) => (
            <Card key={l.id}>
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="font-mono text-[13px] tnum">{l.from_date}{l.to_date !== l.from_date ? ` → ${l.to_date}` : ""}</div>
                  <div className="text-[15px] font-semibold">{l.type_label} — {l.reason}</div>
                  {l.lectures?.length ? <div className="text-[12.5px] text-ash">Lectures: {l.lectures.map((x) => `${x.subject} (${x.date})`).join(", ")}</div> : null}
                  {l.explanation ? <p className="mb-0 mt-1 whitespace-pre-wrap text-[13.5px] text-ink/85">{l.explanation}</p> : null}
                  <AttachmentLink a={l.attachment} />
                </div>
                <Pill tone={l.status === "approved" ? "ok" : l.status === "rejected" ? "bad" : l.status === "cancelled" ? "neutral" : "warn"}>{l.status}</Pill>
              </div>
              {l.remark || l.decided_by ? (
                <p className="mb-0 mt-2 rounded-[3px] bg-tint px-2.5 py-1.5 text-[13px]">
                  <strong>{l.decided_by ?? "Teacher"}:</strong> {l.remark ?? "No remark."}
                </p>
              ) : null}
              {l.status === "pending" ? (
                <div className="mt-3 flex gap-2">
                  <Button onClick={() => setEditing(l)}>Edit</Button>
                  <Button variant="ghost" onClick={() => cancel(l)}>Cancel application</Button>
                </div>
              ) : null}
            </Card>
          ))}
        </div>
      )}
    </Page>
  );
}

function LeaveForm({ leave, onDone, onCancel }: { leave: Leave | null; onDone: () => void; onCancel: () => void }) {
  const { toast } = useUi();
  const [f, setF] = useState({
    type: leave?.type ?? "", from_date: leave?.from_date ?? today(), to_date: leave?.to_date ?? today(),
    reason: leave?.reason ?? "", explanation: leave?.explanation ?? "",
  });
  const [specific, setSpecific] = useState(Boolean(leave?.session_ids?.length));
  const [chosen, setChosen] = useState<number[]>(leave?.session_ids ?? []);
  const [lectures, setLectures] = useState<Lecture[] | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [removeFile, setRemoveFile] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!specific || !f.from_date || !f.to_date || f.to_date < f.from_date) return setLectures(null);
    api.get<Lecture[]>(`/api/me/leaves/lectures?from_date=${f.from_date}&to_date=${f.to_date}`)
      .then(setLectures).catch(() => setLectures([]));
  }, [specific, f.from_date, f.to_date]);

  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => {
    setF((x) => ({ ...x, [k]: e.target.value }));
    setErrors(({ [k]: _d, ...rest }) => rest);
  };

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (!f.type) errs.type = "Choose a leave type.";
    if (!f.from_date) errs.from_date = "Choose the first day.";
    if (!f.to_date) errs.to_date = "Choose the last day.";
    else if (f.to_date < f.from_date) errs.to_date = "The end date cannot be before the start date.";
    if (f.reason.trim().length < 3) errs.reason = "Give a short reason.";
    if (specific && !chosen.length) errs.session_ids = "Choose at least one lecture, or untick “specific lectures”.";
    if (file && file.size > 5 * 1024 * 1024) errs.attachment = "The attachment must be under 5 MB.";
    if (file && !["application/pdf", "image/jpeg", "image/png"].includes(file.type)) errs.attachment = "Use PDF, JPG or PNG.";
    setErrors(errs);
    if (Object.keys(errs).length) return;

    const fd = new FormData();
    for (const [k, v] of Object.entries(f)) fd.append(k, v.trim());
    if (specific) fd.append("session_ids", JSON.stringify(chosen));
    if (file) fd.append("attachment", file);
    if (removeFile) fd.append("remove_attachment", "true");
    setBusy(true);
    setFormError(null);
    try {
      await api.upload(leave ? `/api/me/leaves/${leave.id}` : "/api/me/leaves", fd);
      toast(leave ? "Application updated." : "Leave application sent to your teacher.");
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
      <CardHeader title={leave ? "Edit application" : "Apply for leave"} />
      <FormError>{formError}</FormError>
      <form onSubmit={submit} noValidate className="grid gap-3.5">
        <div className="grid gap-3.5 sm:grid-cols-3">
          <SelectField label="Leave type" required value={f.type} onChange={set("type")} error={errors.type}>
            <option value="">Select…</option>
            {TYPES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </SelectField>
          <TextField label="From" type="date" required value={f.from_date} onChange={set("from_date")} error={errors.from_date} />
          <TextField label="To" type="date" required value={f.to_date} min={f.from_date} onChange={set("to_date")} error={errors.to_date} />
        </div>
        <Checkbox label="Only specific lectures in these dates" checked={specific} onChange={(e) => setSpecific(e.target.checked)} />
        {specific ? (
          <fieldset className="m-0 rounded-[3px] border border-rule p-3">
            <legend className="label px-1">Lectures</legend>
            {lectures === null ? <p className="m-0 text-[13px] text-ash">Loading lectures…</p> : !lectures.length ? (
              <p className="m-0 text-[13px] text-ash">No lectures recorded or scheduled in these dates yet. Apply for the whole days instead.</p>
            ) : (
              <div className="grid gap-1.5 sm:grid-cols-2">
                {lectures.map((l) => (
                  <Checkbox key={l.id} checked={chosen.includes(l.id)}
                            onChange={(e) => setChosen((c) => e.target.checked ? [...c, l.id] : c.filter((x) => x !== l.id))}
                            label={<>{l.date} · <strong>{l.subject}</strong>{l.status ? <span className="text-ash"> ({l.status.replace("_", " ")})</span> : null}</>} />
                ))}
              </div>
            )}
            {errors.session_ids ? <p role="alert" className="mb-0 mt-1 text-[12.5px] text-oxide">{errors.session_ids}</p> : null}
          </fieldset>
        ) : null}
        <TextField label="Reason" required maxLength={200} value={f.reason} onChange={set("reason")} error={errors.reason}
                   hint="One line, e.g. “Fever, doctor advised rest”." />
        <TextArea label="Detailed explanation" value={f.explanation} onChange={set("explanation")} error={errors.explanation}
                  hint="Anything your teacher should know about the absence." />
        <div>
          <label className="display inline-flex w-fit cursor-pointer rounded-[3px] border border-ink px-3.5 py-2 text-[12px] text-ink hover:bg-tint">
            {file ? `Attached: ${file.name}` : "Attach certificate (PDF / JPG / PNG, max 5 MB)"}
            <input type="file" accept="application/pdf,image/jpeg,image/png" className="sr-only"
                   onChange={(e) => { setFile(e.target.files?.[0] ?? null); setErrors(({ attachment: _a, ...r }) => r); }} />
          </label>
          {leave?.attachment && !file ? (
            <div className="mt-1.5"><Checkbox label={`Remove current attachment (${leave.attachment.name})`} checked={removeFile} onChange={(e) => setRemoveFile(e.target.checked)} /></div>
          ) : null}
          {errors.attachment ? <p role="alert" className="m-0 mt-1 text-[12.5px] text-oxide">{errors.attachment}</p> : null}
        </div>
        <Banner>An approved leave turns the covered lectures into “On leave”, which does not count against your percentage.</Banner>
        <div className="flex gap-2">
          <Button type="submit" variant="primary" busy={busy}>{leave ? "Save changes" : "Submit application"}</Button>
          <Button onClick={onCancel}>Cancel</Button>
        </div>
      </form>
    </Card>
  );
}
