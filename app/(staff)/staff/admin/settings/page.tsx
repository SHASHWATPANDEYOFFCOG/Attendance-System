"use client";

/**
 * Settings.
 *
 *   My account      everyone: name, mobile, password
 *   Security        everyone: sign out on all devices, this device (tablet) status
 *   Access codes    administrators: change the administrator and authority codes
 *   College & policy  administrators edit; everyone else reads (with who to ask)
 *
 * Every save goes to the server, which validates it; the page shows the server's answer and
 * reloads what was actually stored, so a refresh always shows the saved state.
 */
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { api, ApiFailure } from "@/lib/client";
import { ROLE_LABEL, useMe } from "@/lib/use-me";
import { Page, PageHeader } from "@/components/shell";
import { Banner, Card, CardHeader, Pill } from "@/components/ui";
import { Button, Checkbox, FormError, TextField } from "@/components/forms";
import { PageError, PageLoading } from "@/components/states";
import { useUi } from "@/components/toast";

type Field = { key: string; kind: string; label: string; help: string; min: number | null; max: number | null; group: string };
type Payload = { values: Record<string, string | number | boolean | null>; fields: Field[]; email_delivery: string };

const GROUPS: [string, string][] = [
  ["general", "College"], ["policy", "Attendance policy"], ["mobile", "Mobile & QR attendance"],
  ["devices", "Tablets & cameras"], ["face", "Face recognition"], ["retention", "Data retention"], ["notifications", "Notifications"],
];

const TABS = [
  ["account", "My account"], ["security", "Security"], ["codes", "Access codes"], ["college", "College & policy"],
] as const;
type Tab = (typeof TABS)[number][0];

export default function SettingsPage() {
  return (
    <Suspense fallback={<Page><PageHeader title="Settings" /><PageLoading /></Page>}>
      <Settings />
    </Suspense>
  );
}

function Settings() {
  const params = useSearchParams();
  const router = useRouter();
  const { me, isAdministrator } = useMe();
  const raw = params.get("tab") as Tab | null;
  const tabs = TABS.filter(([k]) => k !== "codes" || isAdministrator);
  const tab: Tab = tabs.some(([k]) => k === raw) ? (raw as Tab) : "account";

  return (
    <Page>
      <PageHeader title="Settings" subtitle={me ? `${me.display_name} · ${ROLE_LABEL[me.role] ?? me.role}` : "loading"} />
      <nav aria-label="Settings sections" className="-mx-1 mb-4 overflow-x-auto pb-1">
        <ul className="m-0 flex min-w-max list-none gap-1 p-0 px-1">
          {tabs.map(([k, label]) => (
            <li key={k}>
              <button type="button" onClick={() => router.replace(`/staff/admin/settings?tab=${k}`)} aria-current={tab === k ? "page" : undefined}
                      className="display cursor-pointer rounded-[var(--radius)] border px-3 py-1.5 text-[12.5px]"
                      style={tab === k ? { background: "var(--grad-primary)", borderColor: "transparent", color: "var(--on-accent)" } : { borderColor: "var(--rule)", color: "var(--ink)", background: "transparent" }}>
                {label}
              </button>
            </li>
          ))}
        </ul>
      </nav>
      {tab === "account" ? <AccountTab /> : tab === "security" ? <SecurityTab /> : tab === "codes" ? <CodesTab /> : <CollegeTab canEdit={isAdministrator} />}
      <Card className="mt-4">
        <CardHeader title="Managed on their own pages" />
        <ul className="m-0 grid list-none gap-1.5 p-0 text-[14px] sm:grid-cols-2">
          <li><Link href="/staff/setup" className="text-ink underline">Academic setup</Link> <span className="text-ash">— academic years, branches, batches, sections, subjects, timetable</span></li>
          <li><Link href="/staff/cameras" className="text-ink underline">CCTV cameras</Link> <span className="text-ash">— add, test, enable, assign to workspaces</span></li>
          <li><Link href="/staff/workspaces" className="text-ink underline">Workspaces</Link> <span className="text-ash">— who may use which cameras and tablets</span></li>
          <li><Link href="/staff/tablets" className="text-ink underline">Tablets</Link> <span className="text-ash">— register, pair, revoke devices</span></li>
          {isAdministrator ? <li><Link href="/staff/admin/users" className="text-ink underline">Staff & roles</Link> <span className="text-ash">— authorities, roles, enable / disable</span></li> : null}
          {isAdministrator ? <li><Link href="/staff/admin/audit" className="text-ink underline">Audit log</Link> <span className="text-ash">— every sensitive action</span></li> : null}
        </ul>
      </Card>
    </Page>
  );
}

/* ------------------------------------------------------------------ account */

function AccountTab() {
  const { toast } = useUi();
  const { me } = useMe();
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [pw, setPw] = useState({ cur: "", next: "", confirm: "" });
  const [pwErrors, setPwErrors] = useState<Record<string, string>>({});
  const [pwBusy, setPwBusy] = useState(false);

  useEffect(() => {
    if (me) {
      setName(me.display_name);
      setPhone(me.phone ?? "");
    }
  }, [me]);

  async function saveProfile(e: React.FormEvent) {
    e.preventDefault();
    if (name.trim().length < 2) return setErrors({ full_name: "Enter your full name." });
    setBusy(true);
    setErrors({});
    try {
      const r = await api.patch<{ changed: string[] }>("/api/me/account", { full_name: name.trim(), phone: phone.trim() });
      toast(r.changed.length ? "Your details are saved." : "Nothing changed.");
    } catch (err) {
      const d = err instanceof ApiFailure ? err.detail : undefined;
      const field = typeof d?.field === "string" ? (d.field === "mobile" ? "phone" : d.field) : "full_name";
      setErrors({ [field]: err instanceof Error ? err.message : "Could not save." });
    } finally {
      setBusy(false);
    }
  }

  async function changePassword(e: React.FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (!pw.cur) errs.cur = "Enter your current password.";
    if (pw.next.length < 8 || !/[A-Za-z]/.test(pw.next) || !/\d/.test(pw.next)) errs.next = "Use 8+ characters with a letter and a number.";
    if (pw.confirm !== pw.next) errs.confirm = "The passwords do not match.";
    setPwErrors(errs);
    if (Object.keys(errs).length) return;
    setPwBusy(true);
    try {
      await api.post("/api/me/password", { current_password: pw.cur, new_password: pw.next });
      toast("Password changed. Sign in again with the new password.", "info");
      setTimeout(() => (window.location.href = "/authority/login"), 1200);
    } catch (err) {
      const d = err instanceof ApiFailure ? err.detail : undefined;
      const field = typeof d?.field === "string" ? (d.field === "current_password" ? "cur" : "next") : "cur";
      setPwErrors({ [field]: err instanceof Error ? err.message : "Could not change the password." });
    } finally {
      setPwBusy(false);
    }
  }

  if (!me) return <PageLoading rows={2} />;
  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader title="Profile" />
        <form onSubmit={saveProfile} noValidate className="grid gap-3.5 sm:grid-cols-2">
          <TextField label="Full name" value={name} onChange={(e) => setName(e.target.value)} error={errors.full_name} />
          <TextField label="Mobile number" type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} error={errors.phone} />
          <TextField label="Email" value={me.email ?? ""} disabled hint="Your sign-in address. An administrator can change it under Staff & roles." />
          <TextField label="Role" value={ROLE_LABEL[me.role] ?? me.role} disabled hint="Changed by an administrator." />
          <div className="sm:col-span-2"><Button type="submit" variant="primary" busy={busy}>Save details</Button></div>
        </form>
      </Card>
      <Card>
        <CardHeader title="Change password" />
        <form onSubmit={changePassword} noValidate className="grid max-w-[560px] gap-3.5">
          <TextField label="Current password" type="password" autoComplete="current-password" value={pw.cur}
                     onChange={(e) => setPw((p) => ({ ...p, cur: e.target.value }))} error={pwErrors.cur} />
          <div className="grid gap-3.5 sm:grid-cols-2">
            <TextField label="New password" type="password" autoComplete="new-password" value={pw.next}
                       onChange={(e) => setPw((p) => ({ ...p, next: e.target.value }))} error={pwErrors.next} hint="8+ characters, a letter and a number." />
            <TextField label="Repeat new password" type="password" autoComplete="new-password" value={pw.confirm}
                       onChange={(e) => setPw((p) => ({ ...p, confirm: e.target.value }))} error={pwErrors.confirm} />
          </div>
          <div><Button type="submit" variant="primary" busy={pwBusy}>Change password</Button></div>
        </form>
      </Card>
    </div>
  );
}

/* ----------------------------------------------------------------- security */

function SecurityTab() {
  const { confirm, toast } = useUi();
  const [device, setDevice] = useState<{ paired: boolean; tablet?: { name: string; code: string; workspace: string | null } } | null>(null);
  useEffect(() => {
    api.get<typeof device>("/api/tablets/this-device").then(setDevice).catch(() => setDevice({ paired: false }));
  }, []);

  async function everywhere() {
    if (!(await confirm({ title: "Sign out on all devices?", body: "Every browser and tablet signed in to your account is signed out, including this one. Paired tablets stay registered; you just sign in again.", confirmLabel: "Sign out everywhere", danger: true }))) return;
    try {
      await api.post("/api/me/sessions/revoke-all");
      await fetch("/api/auth/logout", { method: "POST" });
      toast("Signed out everywhere.", "info");
      window.location.href = "/authority/login";
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not sign out everywhere.", "bad");
    }
  }

  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader title="Sessions" />
        <p className="mt-0 text-[14px]">
          If you signed in on a shared computer, lost a phone or tablet, or think someone knows your password, sign out
          everywhere — then change your password under <em>My account</em>.
        </p>
        <Button variant="danger" onClick={everywhere}>Sign out on all devices</Button>
      </Card>
      <Card>
        <CardHeader title="This device" meta={device?.paired ? <Pill tone="ok">registered tablet</Pill> : undefined} />
        {!device ? <p className="m-0 text-[13.5px] text-ash">Checking…</p> : device.paired && device.tablet ? (
          <p className="m-0 text-[14px]">This browser is the tablet <strong>{device.tablet.name}</strong> ({device.tablet.code}) in {device.tablet.workspace}. Manage it under <Link href="/staff/tablets" className="text-ink underline">Tablets</Link>.</p>
        ) : (
          <p className="m-0 text-[14px]">This browser is not a registered tablet. To take class-photo attendance or control cameras from it, register and pair it under <Link href="/staff/tablets" className="text-ink underline">Tablets</Link>.</p>
        )}
      </Card>
    </div>
  );
}

/* -------------------------------------------------------------- access codes */

type CodeStatus = Record<"administrator" | "authority", { is_default: boolean; changed_at: string | null; changed_by: string | null }>;

function CodesTab() {
  const [status, setStatus] = useState<CodeStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(() => {
    api.get<CodeStatus>("/api/admin/access-codes").then(setStatus).catch((e) => setError(e instanceof Error ? e.message : "Could not load."));
  }, []);
  useEffect(() => {
    load();
  }, [load]);
  if (error) return <PageError message={error} retry={load} />;
  if (!status) return <PageLoading rows={2} />;
  return (
    <div className="grid gap-4">
      <Banner>
        <strong className="label mb-0.5 block">How the codes work</strong>
        The <strong>authority code</strong> is needed to register as staff at the authority register page. The{" "}
        <strong>administrator code</strong> lets a signed-in authority become an administrator (Administration → Administrator access).
        Codes are stored only as one-way hashes, so nobody — not even an administrator — can read the current code here: changing it
        is the only way to know it. The old code stops working the moment you save.
      </Banner>
      <CodeCard kind="authority" title="Authority code" info={status.authority} onSaved={load}
                use="Give it to teachers and HODs who should be able to register." />
      <CodeCard kind="administrator" title="Administrator code" info={status.administrator} onSaved={load}
                use="Give it only to the people who run the system." />
    </div>
  );
}

function CodeCard({ kind, title, info, use, onSaved }: {
  kind: "administrator" | "authority"; title: string; use: string;
  info: CodeStatus["authority"]; onSaved: () => void;
}) {
  const { toast } = useUi();
  const [code, setCode] = useState("");
  const [confirmCode, setConfirmCode] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (code.trim().length < 8) errs.code = "Use at least 8 characters.";
    else if (/\s/.test(code)) errs.code = "Do not use spaces.";
    if (confirmCode !== code) errs.confirm = "The two entries do not match.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    try {
      await api.put(`/api/admin/access-codes/${kind}`, { code, confirm: confirmCode });
      toast(`${title} changed. The old code no longer works.`);
      setCode("");
      setConfirmCode("");
      onSaved();
    } catch (err) {
      const d = err instanceof ApiFailure ? err.detail : undefined;
      setErrors({ [typeof d?.field === "string" ? d.field : "code"]: err instanceof Error ? err.message : "Could not save." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader title={title} meta={<Pill tone={info.is_default ? "warn" : "ok"}>{info.is_default ? "default code in use" : "custom code"}</Pill>} />
      <p className="mt-0 text-[13.5px] text-ash">
        {use}{" "}
        {info.is_default
          ? "The documented default is still active: change it before giving the system to real users."
          : `Last changed ${info.changed_at ? new Date(info.changed_at).toLocaleString() : ""}${info.changed_by ? ` by ${info.changed_by}` : ""}.`}
      </p>
      <form onSubmit={save} noValidate className="grid max-w-[620px] gap-3 sm:grid-cols-2">
        <TextField label="New code" type="password" autoComplete="new-password" value={code} onChange={(e) => setCode(e.target.value)} error={errors.code} hint="8-64 characters, no spaces." />
        <TextField label="Repeat new code" type="password" autoComplete="new-password" value={confirmCode} onChange={(e) => setConfirmCode(e.target.value)} error={errors.confirm} />
        <div className="sm:col-span-2"><Button type="submit" variant="primary" busy={busy}>Change {title.toLowerCase()}</Button></div>
      </form>
    </Card>
  );
}

/* ---------------------------------------------------------- college & policy */

function CollegeTab({ canEdit }: { canEdit: boolean }) {
  const { toast } = useUi();
  const [data, setData] = useState<Payload | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
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
      toast(`${Object.keys(dirty).length} setting(s) saved.`);
      await load();
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

  if (error) return <PageError message={error} retry={load} />;
  if (!data) return <PageLoading />;

  if (!canEdit) {
    // Not a disabled form: a plain read-out, so nothing looks clickable that is not.
    return (
      <div className="grid gap-4">
        <Banner>These college-wide settings are changed by an administrator. If something here is wrong, ask your administrator (or use Administration → Administrator access if you have the administrator code).</Banner>
        {GROUPS.map(([group, title]) => {
          const fields = data.fields.filter((f) => f.group === group);
          if (!fields.length) return null;
          return (
            <Card key={group}>
              <CardHeader title={title} />
              <dl className="m-0 grid gap-x-4 gap-y-2 sm:grid-cols-[minmax(0,1fr)_auto]">
                {fields.map((f) => (
                  <div key={f.key} className="contents">
                    <dt className="text-[13.5px]">{f.label}</dt>
                    <dd className="m-0 font-mono text-[13.5px] sm:text-right">
                      {f.kind === "bool" ? (data.values[f.key] ? "On" : "Off") : (data.values[f.key] ?? "not set")}
                    </dd>
                  </div>
                ))}
              </dl>
            </Card>
          );
        })}
      </div>
    );
  }

  return (
    <>
      {data.email_delivery !== "smtp" ? (
        <Banner bad>
          <strong className="label mb-0.5 block">Email is not being delivered</strong>
          SMTP is not configured, so emails are written to the server&apos;s <code>var/outbox</code> folder instead of being sent.
        </Banner>
      ) : null}
      <FormError>{saveError}</FormError>
      <form onSubmit={save} noValidate className="grid gap-4">
        {GROUPS.map(([group, title]) => {
          const fields = data.fields.filter((f) => f.group === group);
          if (!fields.length) return null;
          return (
            <Card key={group}>
              <CardHeader title={title} meta={group === "mobile" ? <Button onClick={useMyLocation} busy={locating}>Use my current location as campus</Button> : undefined} />
              <div className="grid gap-3.5 sm:grid-cols-2">
                {fields.map((f) =>
                  f.kind === "bool" ? (
                    <div key={f.key} className="sm:col-span-2">
                      <Checkbox
                        label={<><strong>{f.label}</strong>{f.help ? <span className="block text-[12.5px] text-ash">{f.help}</span> : null}</>}
                        checked={form[f.key] === "true"}
                        onChange={(e) => setForm((x) => ({ ...x, [f.key]: e.target.checked ? "true" : "false" }))}
                      />
                    </div>
                  ) : (
                    <TextField key={f.key} label={f.label} type={f.kind === "str" ? "text" : "number"}
                               step={f.kind.startsWith("float") ? "any" : "1"} min={f.min ?? undefined} max={f.max ?? undefined}
                               value={form[f.key] ?? ""}
                               hint={[f.help, f.min != null && f.max != null ? `Range ${f.min}–${f.max}.` : ""].filter(Boolean).join(" ")}
                               onChange={(e) => setForm((x) => ({ ...x, [f.key]: e.target.value }))} />
                  ),
                )}
              </div>
            </Card>
          );
        })}
        <div className="sticky bottom-3 z-10 flex flex-wrap items-center gap-3 rounded-[var(--radius-lg)] border border-rule glass p-3 shadow-lift">
          <Button type="submit" variant="primary" busy={busy} disabled={!Object.keys(dirty).length}>Save changes</Button>
          {Object.keys(dirty).length ? <Button onClick={() => load()}>Discard</Button> : null}
          <span className="text-[13px] text-ash">{Object.keys(dirty).length ? `${Object.keys(dirty).length} unsaved change(s)` : "All changes saved"}</span>
        </div>
      </form>
    </>
  );
}
