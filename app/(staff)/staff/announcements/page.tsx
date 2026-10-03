"use client";

import { useState } from "react";

import { api, ApiFailure } from "@/lib/client";
import { Page, PageHeader } from "@/components/shell";
import { Card, CardHeader } from "@/components/ui";
import { Button, Checkbox, FormError, TextArea, TextField } from "@/components/forms";
import { NoticeBoard, type Notice } from "@/components/messages";
import { AudiencePicker, type Audience } from "@/components/audience";
import { useUi } from "@/components/toast";

export default function AnnouncementsPage() {
  const { toast, confirm } = useUi();
  const [creating, setCreating] = useState(false);
  const [key, setKey] = useState(0);

  async function remove(n: Notice) {
    if (!(await confirm({ title: `Remove “${n.title}”?`, confirmLabel: "Remove", danger: true }))) return;
    try {
      await api.del(`/api/announcements/${n.id}`);
      toast("Notice removed.");
      setKey((k) => k + 1);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not remove.", "bad");
    }
  }

  return (
    <Page>
      <PageHeader title="Notice board" subtitle="Announcements to your students"
                  actions={creating ? null : <Button variant="primary" onClick={() => setCreating(true)}>+ Post a notice</Button>} />
      {creating ? <NewNotice onDone={() => { setCreating(false); setKey((k) => k + 1); }} onCancel={() => setCreating(false)} /> : null}
      <NoticeBoard key={key} onDelete={remove} />
    </Page>
  );
}

function NewNotice({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const { toast } = useUi();
  const [aud, setAud] = useState<Audience>({ type: "all", ids: [] });
  const [f, setF] = useState({ title: "", body: "", expires_at: "" });
  const [pinned, setPinned] = useState(false);
  const [email, setEmail] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (f.title.trim().length < 3) errs.title = "Write a title.";
    if (!f.body.trim()) errs.body = "Write the notice.";
    if (aud.type !== "all" && !aud.ids.length) errs.audience_type = "Choose who sees it.";
    if (f.expires_at && new Date(f.expires_at) <= new Date()) errs.expires_at = "The expiry must be in the future.";
    if (file && file.size > 5 * 1024 * 1024) errs.attachment = "The attachment must be under 5 MB.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    const fd = new FormData();
    fd.append("title", f.title.trim());
    fd.append("body", f.body.trim());
    fd.append("audience_type", aud.type);
    fd.append("audience_ids", JSON.stringify(aud.ids));
    fd.append("pinned", String(pinned));
    fd.append("send_email", String(email));
    if (f.expires_at) fd.append("expires_at", new Date(f.expires_at).toISOString());
    if (file) fd.append("attachment", file);
    setBusy(true);
    setFormError(null);
    try {
      const r = await api.upload<{ recipients: number }>("/api/announcements", fd);
      toast(`Posted to ${r.recipients} student(s).`);
      onDone();
    } catch (err) {
      const d = err instanceof ApiFailure ? err.detail : undefined;
      if (d && typeof d.field === "string") setErrors({ [d.field]: err instanceof Error ? err.message : "" });
      else setFormError(err instanceof Error ? err.message : "Could not post.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mb-4">
      <CardHeader title="Post a notice" />
      <FormError>{formError}</FormError>
      <form onSubmit={submit} noValidate className="grid gap-3.5">
        <TextField label="Title" required value={f.title} onChange={(e) => setF((x) => ({ ...x, title: e.target.value }))} error={errors.title} />
        <TextArea label="Notice" required value={f.body} onChange={(e) => setF((x) => ({ ...x, body: e.target.value }))} error={errors.body} />
        <AudiencePicker value={aud} onChange={setAud} error={errors.audience_type ?? errors.audience_ids} />
        <div className="grid gap-3.5 sm:grid-cols-2">
          <TextField label="Expires (optional)" type="datetime-local" value={f.expires_at} error={errors.expires_at}
                     onChange={(e) => setF((x) => ({ ...x, expires_at: e.target.value }))} hint="Hidden from students after this." />
          <div className="grid content-end gap-2 pb-1">
            <Checkbox label="Pin to the top" checked={pinned} onChange={(e) => setPinned(e.target.checked)} />
            <Checkbox label="Also send by email" checked={email} onChange={(e) => setEmail(e.target.checked)} />
          </div>
        </div>
        <label className="display inline-flex w-fit cursor-pointer rounded-[3px] border border-ink px-3.5 py-2 text-[12px] text-ink hover:bg-tint">
          {file ? `Attached: ${file.name}` : "Attach PDF / image (optional)"}
          <input type="file" accept="application/pdf,image/jpeg,image/png" className="sr-only" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        {errors.attachment ? <p role="alert" className="m-0 text-[12.5px] text-oxide">{errors.attachment}</p> : null}
        <div className="flex gap-2">
          <Button type="submit" variant="primary" busy={busy}>Post notice</Button>
          <Button onClick={onCancel}>Cancel</Button>
        </div>
      </form>
    </Card>
  );
}
