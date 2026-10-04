"use client";

/**
 * Staff registration. After the emailed code, the account either works at once (as a Teacher)
 * or waits for an administrator — the "Staff registrations need approval" setting decides, and
 * the page says which up front. HOD rights are never self-granted.
 */
import { useEffect, useState } from "react";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { ApiFailure, publicApi } from "@/lib/client";
import { AuthCard, PublicShell } from "@/components/public-shell";
import { Button, FormError, SelectField, TextField } from "@/components/forms";
import { Banner } from "@/components/ui";

type Options = {
  departments: { id: number; code: string; name: string }[];
  policy?: { staff_registration_approval?: boolean; email_verification_required?: boolean };
};

type Form = {
  full_name: string; email: string; mobile: string; employee_id: string; designation: string;
  department_id: string; requested_role: string; password: string; confirm: string; access_code: string;
};

const EMPTY: Form = {
  full_name: "", email: "", mobile: "", employee_id: "", designation: "", department_id: "",
  requested_role: "faculty", password: "", confirm: "", access_code: "",
};

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const PHONE_RE = /^\+?\d{10,15}$/;

function validate(f: Form): Record<string, string> {
  const e: Record<string, string> = {};
  if (!f.access_code.trim()) e.access_code = "Enter the authority access code your administrator gave you.";
  if (!f.full_name.trim()) e.full_name = "Enter your full name.";
  if (!EMAIL_RE.test(f.email.trim())) e.email = "Enter a valid email address.";
  if (!PHONE_RE.test(f.mobile.replace(/[\s\-()]/g, ""))) e.mobile = "Enter a 10–15 digit mobile number.";
  if (!f.employee_id.trim()) e.employee_id = "Enter your employee / staff ID.";
  if (!f.department_id) e.department_id = "Choose your branch.";
  if (f.password.length < 8) e.password = "Use at least 8 characters.";
  else if (!/[A-Za-z]/.test(f.password) || !/\d/.test(f.password)) e.password = "Use at least one letter and one number.";
  if (f.confirm !== f.password) e.confirm = "The passwords do not match.";
  return e;
}

export default function AuthorityRegisterPage() {
  const router = useRouter();
  const [opts, setOpts] = useState<Options | null>(null);
  const [optsError, setOptsError] = useState<string | null>(null);
  const [form, setForm] = useState<Form>(EMPTY);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    publicApi.get<Options>("public/academic-options")
      .then(setOpts)
      .catch((e) => setOptsError(e instanceof Error ? e.message : "Could not load branches."));
  }, []);

  const set = (k: keyof Form) => (e: { target: { value: string } }) => {
    const v = e.target.value;
    setForm((f) => ({ ...f, [k]: v }));
    if (errors[k]) setErrors(({ [k]: _drop, ...rest }) => rest);
  };

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const found = validate(form);
    setErrors(found);
    if (Object.keys(found).length) return;
    setBusy(true);
    setFormError(null);
    try {
      const res = await publicApi.post<{ otp_sent?: boolean; account?: string }>("auth/staff-signup", {
        full_name: form.full_name.trim(), email: form.email.trim(), mobile: form.mobile.trim(),
        employee_id: form.employee_id.trim(), designation: form.designation.trim() || null,
        department_id: Number(form.department_id), requested_role: form.requested_role,
        password: form.password, access_code: form.access_code.trim(),
      });
      router.push(res?.otp_sent
        ? `/verify-email?email=${encodeURIComponent(form.email.trim().toLowerCase())}`
        : `/authority/login?registered=${res?.account === "pending" ? "staff-pending" : "staff"}`);
    } catch (err) {
      const detail = err instanceof ApiFailure ? err.detail : undefined;
      const field = typeof detail?.field === "string" ? detail.field : undefined;
      const message = err instanceof Error ? err.message : "Registration failed.";
      if (field && field in EMPTY) setErrors({ [field]: message });
      else setFormError(message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <PublicShell width={560} subtitle="Authority portal · staff registration">
      <AuthCard title="Register as staff">
        <Banner>
          {[
            opts?.policy?.email_verification_required ? "We email you a code to confirm your address." : null,
            opts?.policy?.staff_registration_approval
              ? "Your account works once an administrator approves it (an HOD can approve teachers of their own branch)."
              : "Your account is ready as soon as you register. HOD rights are given by the administrator.",
          ].filter(Boolean).join(" ")}
        </Banner>
        {optsError ? <FormError>{optsError}</FormError> : null}
        {opts && opts.departments.length === 0 ? (
          <FormError>No branches have been set up yet. Ask the administrator to create your account.</FormError>
        ) : null}
        <form onSubmit={submit} noValidate className="mt-4 grid gap-3.5">
          <TextField label="Authority access code" type="password" autoComplete="off" required value={form.access_code}
                     onChange={set("access_code")} error={errors.access_code}
                     hint="Only staff with this code can register. Ask your administrator for it." />
          <TextField label="Full name" required autoComplete="name" value={form.full_name}
                     onChange={set("full_name")} error={errors.full_name} />
          <div className="grid gap-3.5 sm:grid-cols-2">
            <TextField label="Email" type="email" inputMode="email" required autoComplete="email"
                       value={form.email} onChange={set("email")} error={errors.email}
                       hint="Use your college email if you have one." />
            <TextField label="Mobile number" type="tel" inputMode="tel" required autoComplete="tel"
                       value={form.mobile} onChange={set("mobile")} error={errors.mobile} />
          </div>
          <div className="grid gap-3.5 sm:grid-cols-2">
            <TextField label="Employee / staff ID" required value={form.employee_id}
                       onChange={set("employee_id")} error={errors.employee_id} />
            <TextField label="Designation (optional)" placeholder="e.g. Assistant Professor"
                       value={form.designation} onChange={set("designation")} error={errors.designation} />
          </div>
          <div className="grid gap-3.5 sm:grid-cols-2">
            <SelectField label="Branch" required value={form.department_id} onChange={set("department_id")}
                         error={errors.department_id}>
              <option value="">Select…</option>
              {opts?.departments.map((d) => (
                <option key={d.id} value={d.id}>{d.code} — {d.name}</option>
              ))}
            </SelectField>
            <SelectField label="I am a" required value={form.requested_role} onChange={set("requested_role")}
                         error={errors.requested_role}
                         hint={form.requested_role === "admin" ? "HOD rights are granted by the administrator; until then you have teacher access." : undefined}>
              <option value="faculty">Teacher</option>
              <option value="admin">Head of department (HOD)</option>
            </SelectField>
          </div>
          <div className="grid gap-3.5 sm:grid-cols-2">
            <TextField label="Password" type="password" required autoComplete="new-password"
                       value={form.password} onChange={set("password")} error={errors.password}
                       hint="8+ characters, a letter and a number." />
            <TextField label="Confirm password" type="password" required autoComplete="new-password"
                       value={form.confirm} onChange={set("confirm")} error={errors.confirm} />
          </div>
          {formError ? <FormError>{formError}</FormError> : null}
          <div className="mt-1 flex flex-wrap items-center justify-between gap-3">
            <Link href="/authority/login" className="text-[13.5px] text-ink underline-offset-2 hover:underline">
              Already have an account? Sign in
            </Link>
            <Button type="submit" variant="primary" busy={busy}>{busy ? "Registering…" : "Register"}</Button>
          </div>
        </form>
      </AuthCard>
    </PublicShell>
  );
}
