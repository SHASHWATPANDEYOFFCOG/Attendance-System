"use client";

/**
 * The student's own profile. Contact details are editable directly; identity details (roll no,
 * branch, batch, year, section, name) lock once a teacher approves the account, after which a
 * change goes through an edit request the teacher reviews.
 */
import { useCallback, useEffect, useMemo, useState } from "react";

import { api, ApiFailure, publicApi } from "@/lib/client";
import { Page, PageHeader } from "@/components/shell";
import { Banner, Card, CardHeader, Pill } from "@/components/ui";
import { Button, FormError, SelectField, TextArea, TextField } from "@/components/forms";
import { useUi } from "@/components/toast";
import { PageError, PageLoading } from "@/components/states";

type Profile = {
  id: number;
  full_name: string;
  email: string | null;
  email_verified: boolean;
  phone: string | null;
  consent_given: boolean;
  has_biometrics: boolean;
  student: null | {
    status: "pending" | "approved" | "rejected";
    rejection_reason: string | null;
    roll_number: string | null;
    enrollment_no: string | null;
    department_id: number | null;
    department: string | null;
    batch_id: number | null;
    batch: string | null;
    year: number | null;
    section_id: number | null;
    section: string | null;
    dob: string | null;
    gender: string | null;
    guardian_name: string | null;
    guardian_phone: string | null;
    guardian_email: string | null;
    address: string | null;
    photo_url: string | null;
    locked_fields: string[];
    pending_edit_request: null | { id: number; changes: Record<string, unknown>; reason: string; created_at: string };
  };
};

type Options = {
  departments: { id: number; code: string; name: string; years: number }[];
  batches: { id: number; label: string }[];
  sections: { id: number; name: string; year: number; department_id: number; batch_id: number | null; label: string }[];
};

const GENDERS: [string, string][] = [
  ["female", "Female"], ["male", "Male"], ["non_binary", "Non-binary"], ["other", "Other"],
  ["prefer_not_to_say", "Prefer not to say"],
];

export default function ProfilePage() {
  const { toast } = useUi();
  const [p, setP] = useState<Profile | null>(null);
  const [opts, setOpts] = useState<Options | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setP(await api.get<Profile>("/api/me/profile"));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load your profile.");
    }
  }, []);

  useEffect(() => {
    load();
    publicApi.get<Options>("public/academic-options").then(setOpts).catch(() => setOpts(null));
  }, [load]);

  if (error) return <Page><PageHeader title="My profile" /><PageError message={error} retry={load} /></Page>;
  if (!p) return <Page><PageHeader title="My profile" /><PageLoading /></Page>;
  const s = p.student;

  return (
    <Page>
      <PageHeader
        title="My profile"
        subtitle={`${p.full_name}${s?.roll_number ? ` · ${s.roll_number}` : ""}`}
        actions={s ? <StatusPill status={s.status} /> : null}
      />

      {s?.status === "rejected" ? (
        <Banner bad>
          <strong className="label mb-0.5 block">Registration rejected</strong>
          {s.rejection_reason ?? "No reason was recorded."} Fix the details below, then resubmit.
          <div className="mt-2">
            <Button
              variant="primary"
              onClick={async () => {
                try {
                  await api.post("/api/me/resubmit");
                  toast("Resubmitted for approval.");
                  load();
                } catch (e) {
                  toast(e instanceof Error ? e.message : "Could not resubmit.", "bad");
                }
              }}
            >
              Resubmit for approval
            </Button>
          </div>
        </Banner>
      ) : null}
      {s?.status === "pending" ? (
        <Banner>
          <strong className="label mb-0.5 block">Awaiting approval</strong>
          You can still correct any detail below until a teacher approves your registration.
        </Banner>
      ) : null}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="grid content-start gap-4">
          {s ? <DetailsForm profile={p} opts={opts} onSaved={load} /> : null}
          {s && s.status === "approved" ? <EditRequestCard profile={p} opts={opts} onSaved={load} /> : null}
        </div>
        <div className="grid content-start gap-4">
          {s ? <PhotoCard profile={p} onSaved={load} /> : null}
          <PasswordCard />
        </div>
      </div>
    </Page>
  );
}

function StatusPill({ status }: { status: string }) {
  const tone = status === "approved" ? "ok" : status === "rejected" ? "bad" : "warn";
  return <Pill tone={tone}>{status}</Pill>;
}

function DetailsForm({ profile, opts, onSaved }: { profile: Profile; opts: Options | null; onSaved: () => void }) {
  const { toast } = useUi();
  const s = profile.student!;
  const locked = new Set(s.locked_fields);
  const [f, setF] = useState({
    full_name: profile.full_name, phone: profile.phone ?? "", roll_number: s.roll_number ?? "",
    enrollment_no: s.enrollment_no ?? "", department_id: String(s.department_id ?? ""),
    batch_id: String(s.batch_id ?? ""), year: String(s.year ?? ""), section_id: String(s.section_id ?? ""),
    dob: s.dob ?? "", gender: s.gender ?? "", guardian_name: s.guardian_name ?? "",
    guardian_phone: s.guardian_phone ?? "", guardian_email: s.guardian_email ?? "", address: s.address ?? "",
  });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => {
    setF((x) => ({ ...x, [k]: e.target.value, ...(k === "department_id" || k === "year" || k === "batch_id" ? { section_id: "" } : {}) }));
    setErrors(({ [k]: _d, ...rest }) => rest);
  };
  const sections = useMemo(
    () => (opts?.sections ?? []).filter((x) => String(x.department_id) === f.department_id &&
      String(x.year) === f.year && (x.batch_id === null || String(x.batch_id) === f.batch_id)),
    [opts, f.department_id, f.year, f.batch_id],
  );

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setFormError(null);
    const body: Record<string, unknown> = {
      phone: f.phone, dob: f.dob || undefined, gender: f.gender || undefined,
      guardian_name: f.guardian_name, guardian_phone: f.guardian_phone,
      guardian_email: f.guardian_email || null, address: f.address,
    };
    if (!locked.size) {
      Object.assign(body, {
        full_name: f.full_name, roll_number: f.roll_number, enrollment_no: f.enrollment_no,
        department_id: Number(f.department_id), batch_id: Number(f.batch_id), year: Number(f.year),
        section_id: Number(f.section_id),
      });
    }
    try {
      await api.patch("/api/me/profile", body);
      toast("Profile saved.");
      onSaved();
    } catch (err) {
      const d = err instanceof ApiFailure ? err.detail : undefined;
      if (d && typeof d.field === "string") setErrors({ [d.field === "mobile" ? "phone" : d.field]: err instanceof Error ? err.message : "" });
      else setFormError(err instanceof Error ? err.message : "Could not save.");
    } finally {
      setBusy(false);
    }
  }

  const dept = opts?.departments.find((d) => String(d.id) === f.department_id);
  const lockedHint = locked.size ? "Locked after approval — use an edit request below." : undefined;

  return (
    <Card>
      <CardHeader title="Details" meta={profile.email ?? undefined} />
      <FormError>{formError}</FormError>
      <form onSubmit={save} className="grid gap-3.5" noValidate>
        <div className="grid gap-3.5 sm:grid-cols-2">
          <TextField label="Full name" value={f.full_name} onChange={set("full_name")}
                     disabled={locked.has("full_name")} error={errors.full_name} hint={lockedHint} />
          <TextField label="Mobile" type="tel" inputMode="tel" value={f.phone} onChange={set("phone")}
                     error={errors.phone} />
          <TextField label="Roll number" value={f.roll_number} onChange={set("roll_number")}
                     disabled={locked.has("roll_number")} error={errors.roll_number} />
          <TextField label="Enrollment no." value={f.enrollment_no} onChange={set("enrollment_no")}
                     disabled={locked.has("enrollment_no")} error={errors.enrollment_no} />
          <SelectField label="Branch" value={f.department_id} onChange={set("department_id")}
                       disabled={locked.has("department_id")} error={errors.department_id}>
            <option value="">Select…</option>
            {opts?.departments.map((d) => <option key={d.id} value={d.id}>{d.code} — {d.name}</option>)}
          </SelectField>
          <SelectField label="Year" value={f.year} onChange={set("year")} disabled={locked.has("year")}
                       error={errors.year}>
            <option value="">Select…</option>
            {Array.from({ length: dept?.years ?? 4 }, (_, i) => i + 1).map((y) => <option key={y} value={y}>Year {y}</option>)}
          </SelectField>
          <SelectField label="Batch" value={f.batch_id} onChange={set("batch_id")}
                       disabled={locked.has("batch_id")} error={errors.batch_id}>
            <option value="">Select…</option>
            {opts?.batches.map((b) => <option key={b.id} value={b.id}>{b.label}</option>)}
          </SelectField>
          <SelectField label="Section" value={f.section_id} onChange={set("section_id")}
                       disabled={locked.has("section_id")} error={errors.section_id}>
            <option value="">{locked.has("section_id") ? s.section ?? "—" : "Select…"}</option>
            {sections.map((x) => <option key={x.id} value={x.id}>Section {x.name}</option>)}
          </SelectField>
          <TextField label="Date of birth" type="date" value={f.dob} onChange={set("dob")} error={errors.dob} />
          <SelectField label="Gender" value={f.gender} onChange={set("gender")} error={errors.gender}>
            <option value="">Select…</option>
            {GENDERS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </SelectField>
          <TextField label="Guardian name" value={f.guardian_name} onChange={set("guardian_name")}
                     error={errors.guardian_name} />
          <TextField label="Guardian phone" type="tel" inputMode="tel" value={f.guardian_phone}
                     onChange={set("guardian_phone")} error={errors.guardian_phone} />
        </div>
        <TextField label="Guardian email" type="email" value={f.guardian_email}
                   onChange={set("guardian_email")} error={errors.guardian_email} />
        <TextArea label="Address" value={f.address} onChange={set("address")} error={errors.address} />
        <div>
          <Button type="submit" variant="primary" busy={busy}>Save changes</Button>
        </div>
      </form>
    </Card>
  );
}

const LOCKED_LABEL: Record<string, string> = {
  full_name: "Full name", roll_number: "Roll number", enrollment_no: "Enrollment no.",
  department_id: "Branch", batch_id: "Batch", year: "Year", section_id: "Section",
};

function EditRequestCard({ profile, opts, onSaved }: { profile: Profile; opts: Options | null; onSaved: () => void }) {
  const { toast } = useUi();
  const s = profile.student!;
  const pending = s.pending_edit_request;
  const [field, setField] = useState("roll_number");
  const [value, setValue] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const label = (k: string, v: unknown) => {
    if (k === "department_id") return opts?.departments.find((d) => d.id === Number(v))?.code ?? String(v);
    if (k === "batch_id") return opts?.batches.find((b) => b.id === Number(v))?.label ?? String(v);
    if (k === "section_id") return opts?.sections.find((x) => x.id === Number(v))?.label ?? String(v);
    return String(v);
  };

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!value.trim()) return setError("Enter the corrected value.");
    if (reason.trim().length < 5) return setError("Explain why (at least 5 characters).");
    setBusy(true);
    setError(null);
    const numeric = ["department_id", "batch_id", "year", "section_id"].includes(field);
    try {
      await api.post("/api/me/edit-requests", {
        changes: { [field]: numeric ? Number(value) : value.trim() },
        reason: reason.trim(),
      });
      toast("Edit request sent to your teacher.");
      setValue("");
      setReason("");
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send the request.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Request a correction" meta="locked details" />
      {pending ? (
        <div className="text-[14px]">
          <p className="m-0">
            Waiting for review:{" "}
            {Object.entries(pending.changes).map(([k, v]) => (
              <strong key={k}>{LOCKED_LABEL[k] ?? k} → {label(k, v)} </strong>
            ))}
          </p>
          <p className="mt-1 text-ash">“{pending.reason}”</p>
          <Button
            className="mt-2"
            onClick={async () => {
              try {
                await api.del(`/api/me/edit-requests/${pending.id}`);
                toast("Request withdrawn.");
                onSaved();
              } catch (e) {
                toast(e instanceof Error ? e.message : "Could not withdraw.", "bad");
              }
            }}
          >
            Withdraw request
          </Button>
        </div>
      ) : (
        <form onSubmit={submit} className="grid gap-3.5" noValidate>
          <FormError>{error}</FormError>
          <div className="grid gap-3.5 sm:grid-cols-2">
            <SelectField label="Field" value={field} onChange={(e) => { setField(e.target.value); setValue(""); }}>
              {Object.entries(LOCKED_LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
            </SelectField>
            {field === "department_id" ? (
              <SelectField label="Correct value" value={value} onChange={(e) => setValue(e.target.value)}>
                <option value="">Select…</option>
                {opts?.departments.map((d) => <option key={d.id} value={d.id}>{d.code}</option>)}
              </SelectField>
            ) : field === "batch_id" ? (
              <SelectField label="Correct value" value={value} onChange={(e) => setValue(e.target.value)}>
                <option value="">Select…</option>
                {opts?.batches.map((b) => <option key={b.id} value={b.id}>{b.label}</option>)}
              </SelectField>
            ) : field === "section_id" ? (
              <SelectField label="Correct value" value={value} onChange={(e) => setValue(e.target.value)}>
                <option value="">Select…</option>
                {opts?.sections.map((x) => <option key={x.id} value={x.id}>{x.label}</option>)}
              </SelectField>
            ) : (
              <TextField label="Correct value" value={value} inputMode={field === "year" ? "numeric" : undefined}
                         onChange={(e) => setValue(e.target.value)} />
            )}
          </div>
          <TextArea label="Why does it need changing?" value={reason} onChange={(e) => setReason(e.target.value)} />
          <div><Button type="submit" variant="primary" busy={busy}>Send request</Button></div>
        </form>
      )}
    </Card>
  );
}

function PhotoCard({ profile, onSaved }: { profile: Profile; onSaved: () => void }) {
  const { toast } = useUi();
  const [busy, setBusy] = useState(false);
  const url = profile.student?.photo_url;
  return (
    <Card>
      <CardHeader title="Profile photo" />
      <div className="flex items-center gap-4">
        <div className="grid h-[96px] w-[96px] shrink-0 place-items-center overflow-hidden rounded-[3px] border border-rule bg-paper">
          {url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={`/api/backend${url}`} alt="Your profile photo" className="h-full w-full object-cover" />
          ) : (
            <span className="label">None</span>
          )}
        </div>
        <label className="display inline-flex cursor-pointer rounded-[3px] border border-ink px-3.5 py-2 text-[12px] text-ink hover:bg-tint">
          {busy ? "Uploading…" : "Change photo"}
          <input
            type="file"
            accept="image/jpeg,image/png,image/webp"
            className="sr-only"
            disabled={busy}
            onChange={async (e) => {
              const file = e.target.files?.[0];
              if (!file) return;
              if (file.size > 3 * 1024 * 1024) return toast("The photo must be under 3 MB.", "bad");
              const fd = new FormData();
              fd.append("photo", file);
              setBusy(true);
              try {
                await api.upload("/api/me/photo", fd);
                toast("Photo updated.");
                onSaved();
              } catch (err) {
                toast(err instanceof Error ? err.message : "Upload failed.", "bad");
              } finally {
                setBusy(false);
              }
            }}
          />
        </label>
      </div>
    </Card>
  );
}

function PasswordCard() {
  const { toast } = useUi();
  const [cur, setCur] = useState("");
  const [pw, setPw] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const errs: Record<string, string> = {};
    if (!cur) errs.current_password = "Enter your current password.";
    if (pw.length < 8 || !/[A-Za-z]/.test(pw) || !/\d/.test(pw)) errs.new_password = "8+ characters with a letter and a number.";
    if (confirm !== pw) errs.confirm = "The passwords do not match.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    try {
      await api.post("/api/me/password", { current_password: cur, new_password: pw });
      toast("Password changed. Signing you in again…", "info");
      // Every token issued before the change is now refused, including this tab's.
      setTimeout(() => (window.location.href = "/login"), 1200);
    } catch (err) {
      const d = err instanceof ApiFailure ? err.detail : undefined;
      if (d && typeof d.field === "string") setErrors({ [d.field]: err instanceof Error ? err.message : "" });
      else toast(err instanceof Error ? err.message : "Could not change the password.", "bad");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader title="Change password" />
      <form onSubmit={submit} className="grid gap-3" noValidate>
        <TextField label="Current password" type="password" autoComplete="current-password" value={cur}
                   onChange={(e) => setCur(e.target.value)} error={errors.current_password} />
        <TextField label="New password" type="password" autoComplete="new-password" value={pw}
                   onChange={(e) => setPw(e.target.value)} error={errors.new_password} />
        <TextField label="Confirm new password" type="password" autoComplete="new-password" value={confirm}
                   onChange={(e) => setConfirm(e.target.value)} error={errors.confirm} />
        <div><Button type="submit" variant="primary" busy={busy}>Change password</Button></div>
      </form>
    </Card>
  );
}
