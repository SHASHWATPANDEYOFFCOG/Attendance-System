"use client";

import { Suspense, useState } from "react";

import { useSearchParams } from "next/navigation";

import { api } from "@/lib/client";
import { Page, PageHeader } from "@/components/shell";
import { Card, CardHeader } from "@/components/ui";
import { Button, Checkbox, FormError, TextArea } from "@/components/forms";
import { ConversationList } from "@/components/messages";
import { AudiencePicker, type Audience } from "@/components/audience";
import { PageLoading } from "@/components/states";
import { useUi } from "@/components/toast";

export default function StaffMessagesPage() {
  return (
    <Suspense fallback={<Page><PageHeader title="Messages" /><PageLoading /></Page>}>
      <Inner />
    </Suspense>
  );
}

function Inner() {
  const sp = useSearchParams();
  const preset = sp.get("student");
  const [composing, setComposing] = useState(Boolean(preset));
  const [key, setKey] = useState(0);
  return (
    <Page>
      <PageHeader title="Messages" subtitle="Direct messages with students"
                  actions={composing ? null : <Button variant="primary" onClick={() => setComposing(true)}>+ New message</Button>} />
      {composing ? (
        <Compose initial={preset ? { type: "students", ids: [Number(preset)] } : undefined}
                 onDone={() => { setComposing(false); setKey((k) => k + 1); }} onCancel={() => setComposing(false)} />
      ) : null}
      <ConversationList key={key} base="/staff/messages" />
    </Page>
  );
}

function Compose({ initial, onDone, onCancel }: { initial?: Audience; onDone: () => void; onCancel: () => void }) {
  const { toast } = useUi();
  const [aud, setAud] = useState<Audience>(initial ?? { type: "students", ids: [] });
  const [body, setBody] = useState("");
  const [email, setEmail] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function send(e: React.FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (aud.type !== "all" && !aud.ids.length) errs.audience = "Choose at least one recipient.";
    if (!body.trim()) errs.body = "Write the message.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    setFormError(null);
    try {
      const r = await api.post<{ sent: number }>("/api/messages/broadcast", { audience: aud.type, ids: aud.ids, body: body.trim(), email });
      toast(`Sent to ${r.sent} student${r.sent === 1 ? "" : "s"}. Each can reply to you privately.`);
      onDone();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "Could not send.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="mb-4">
      <CardHeader title="New message" />
      <FormError>{formError}</FormError>
      <form onSubmit={send} noValidate className="grid gap-3.5">
        <AudiencePicker value={aud} onChange={setAud} error={errors.audience} />
        <TextArea label="Message" required value={body} onChange={(e) => setBody(e.target.value)} error={errors.body} />
        <Checkbox label="Also send by email" checked={email} onChange={(e) => setEmail(e.target.checked)} />
        <div className="flex gap-2">
          <Button type="submit" variant="primary" busy={busy}>Send</Button>
          <Button onClick={onCancel}>Cancel</Button>
        </div>
      </form>
    </Card>
  );
}
