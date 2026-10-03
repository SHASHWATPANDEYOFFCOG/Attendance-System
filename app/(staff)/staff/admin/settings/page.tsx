"use client";

/**
 * System settings, rendered from the server's own field metadata (label, type, min/max), so the
 * form can never offer a value the server would refuse. Saved as one validated batch; every
 * change is audited with its old and new value.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { api } from "@/lib/client";
import { Page, PageHeader } from "@/components/shell";
import { Banner, Card, CardHeader } from "@/components/ui";
import { Button, Checkbox, FormError, TextField } from "@/components/forms";
import { PageError, PageLoading } from "@/components/states";
import { useUi } from "@/components/toast";

type Field = { key: string; kind: string; label: string; help: string; min: number | null; max: number | null; group: string };
type Payload = { values: Record<string, string | number | boolean | null>; fields: Field[]; email_delivery: string };

const GROUPS: [string, string][] = [
  ["general", "College"], ["policy", "Attendance policy"], ["mobile", "Mobile & QR attendance"],
  ["face", "Face recognition"], ["retention", "Data retention"], ["notifications", "Notifications"],
];

export default function SettingsPage() {
  const { toast } = useUi();
  const [data, setData] = useState<Payload | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [canEdit, setCanEdit] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [locating, setLocating] = useState(false);

  const load = useCallback(async () => {
    try {
      const d = await api.get<Payload>("/api/admin/settings");
      setData(d);
      setForm(Object.fromEntries(Object.entries(d.values).map(([k, v]) => [k, v == null ? "" : String(v)])));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load settings.");
    }
  }, []);
  useEffect(() => {
    load();
    api.get<{ role: string }>("/api/me").then((m) => setCanEdit(m.role === "super_admin")).catch(() => {});
  }, [load]);

  const dirty = useMemo(() => {
    if (!data) return {};
    const out: Record<string, string> = {};
    for (const [k, v] of Object.entries(form)) {
      const orig = data.values[k];
      if ((orig == null ? "" : String(orig)) !== v) out[k] = v;
    }
    return out;
  }, [form, data]);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setSaveError(null);
    try {
      await api.patch("/api/admin/settings", dirty);
      toast("Settings saved.");
      load();
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  function useMyLocation() {
    if (!navigator.geolocation) return toast("This browser cannot share location.", "bad");
    setLocating(true);
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        setForm((f) => ({ ...f, campus_lat: pos.coords.latitude.toFixed(6), campus_lng: pos.coords.longitude.toFixed(6) }));
        toast(`Location captured (±${Math.round(pos.coords.accuracy)} m). Save to apply.`, "info");
        setLocating(false);
      },
      (err) => {
        toast(err.code === err.PERMISSION_DENIED ? "Location permission was denied." : "Could not get your location.", "bad");
        setLocating(false);
      },
      { enableHighAccuracy: true, timeout: 15000 },
    );
  }

  if (error) return <Page><PageHeader title="Settings" /><PageError message={error} retry={load} /></Page>;
  if (!data) return <Page><PageHeader title="Settings" /><PageLoading /></Page>;

  return (
    <Page>
      <PageHeader title="Settings" subtitle={canEdit ? "Changes take effect immediately and are audited" : "Read-only — only an administrator can change these"} />
      {data.email_delivery !== "smtp" ? (
        <Banner bad>
          <strong className="label mb-0.5 block">Email is not being delivered</strong>
          SMTP is not configured, so emails (OTP codes, approvals, alerts) are written to the server&apos;s
          <code> var/outbox</code> folder instead of being sent. Set SMTP_HOST and related variables.
        </Banner>
      ) : null}
      <FormError>{saveError}</FormError>
      <form onSubmit={save} noValidate className="grid gap-4">
        {GROUPS.map(([group, title]) => {
          const fields = data.fields.filter((f) => f.group === group);
          if (!fields.length) return null;
          return (
            <Card key={group}>
              <CardHeader
                title={title}
                meta={group === "mobile" && canEdit ? <Button onClick={useMyLocation} busy={locating}>Use my current location as campus</Button> : undefined}
              />
              <div className="grid gap-3.5 sm:grid-cols-2">
                {fields.map((f) =>
                  f.kind === "bool" ? (
                    <div key={f.key} className="sm:col-span-2">
                      <Checkbox
                        label={<><strong>{f.label}</strong>{f.help ? <span className="block text-[12.5px] text-ash">{f.help}</span> : null}</>}
                        checked={form[f.key] === "true"}
                        disabled={!canEdit}
                        onChange={(e) => setForm((x) => ({ ...x, [f.key]: e.target.checked ? "true" : "false" }))}
                      />
                    </div>
                  ) : (
                    <TextField
                      key={f.key}
                      label={f.label}
                      type={f.kind === "str" ? "text" : "number"}
                      step={f.kind.startsWith("float") ? "any" : "1"}
                      min={f.min ?? undefined}
                      max={f.max ?? undefined}
                      value={form[f.key] ?? ""}
                      disabled={!canEdit}
                      hint={[f.help, f.min != null && f.max != null ? `Range ${f.min}–${f.max}.` : ""].filter(Boolean).join(" ")}
                      onChange={(e) => setForm((x) => ({ ...x, [f.key]: e.target.value }))}
                    />
                  ),
                )}
              </div>
            </Card>
          );
        })}
        {canEdit ? (
          <div className="sticky bottom-3 z-10 flex items-center gap-3 rounded-[3px] border border-rule bg-card p-3 shadow-lift">
            <Button type="submit" variant="primary" busy={busy} disabled={!Object.keys(dirty).length}>Save changes</Button>
            <span className="text-[13px] text-ash">{Object.keys(dirty).length ? `${Object.keys(dirty).length} unsaved change(s)` : "No changes"}</span>
          </div>
        ) : null}
      </form>
    </Page>
  );
}
