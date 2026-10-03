"use client";

/**
 * Student self-registration.
 *
 * Four short steps on a phone (all visible as one long form is a wall on a 360 px screen).
 * Each step validates before moving on, with the same rules the server applies; the server's
 * answer is still the one that counts, and its errors are routed back to the right field and
 * step. Dropdowns are dependent: sections offered are only those of the chosen branch, year and
 * batch, all created by staff under Setup.
 */
import { useEffect, useMemo, useRef, useState } from "react";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { ApiFailure, publicApi } from "@/lib/client";
import { AuthCard, PublicShell } from "@/components/public-shell";
import { Button, FormError, SelectField, TextArea, TextField } from "@/components/forms";

type Options = {
  departments: { id: number; code: string; name: string; years: number }[];
  batches: { id: number; label: string }[];
  sections: { id: number; name: string; year: number; department_id: number; batch_id: number | null; label: string }[];
};

type Form = Record<
  | "full_name" | "email" | "mobile" | "password" | "confirm" | "department_id" | "year"
  | "batch_id" | "section_id" | "roll_number" | "enrollment_no" | "dob" | "gender"
  | "guardian_name" | "guardian_phone" | "guardian_email" | "address",
  string
>;

const EMPTY: Form = {
  full_name: "", email: "", mobile: "", password: "", confirm: "", department_id: "", year: "",
  batch_id: "", section_id: "", roll_number: "", enrollment_no: "", dob: "", gender: "",
  guardian_name: "", guardian_phone: "", guardian_email: "", address: "",
};

const STEPS = ["Account", "Class", "Personal", "Photo"] as const;
const STEP_OF: Record<string, number> = {
  full_name: 0, email: 0, mobile: 0, password: 0, confirm: 0,
  department_id: 1, year: 1, batch_id: 1, section_id: 1, roll_number: 1, enrollment_no: 1,
  dob: 2, gender: 2, guardian_name: 2, guardian_phone: 2, guardian_email: 2, address: 2,
  photo: 3,
};

const EMAIL_RE = /^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$/;
const PHONE_RE = /^\+?\d{10,15}$/;

function validate(step: number, f: Form, photo: File | null): Record<string, string> {
  const e: Record<string, string> = {};
  const phone = (v: string) => v.replace(/[\s\-()]/g, "");
  if (step === 0) {
    if (!f.full_name.trim()) e.full_name = "Enter your full name.";
    if (!EMAIL_RE.test(f.email.trim())) e.email = "Enter a valid email address.";
    if (!PHONE_RE.test(phone(f.mobile))) e.mobile = "Enter a 10–15 digit mobile number.";
    if (f.password.length < 8) e.password = "Use at least 8 characters.";
    else if (!/[A-Za-z]/.test(f.password) || !/\d/.test(f.password))
      e.password = "Use at least one letter and one number.";
    if (f.confirm !== f.password) e.confirm = "The passwords do not match.";
  }
  if (step === 1) {
    if (!f.department_id) e.department_id = "Choose your branch.";
    if (!f.year) e.year = "Choose your year.";
    if (!f.batch_id) e.batch_id = "Choose your batch.";
    if (!f.section_id) e.section_id = "Choose your section.";
    if (!/^[A-Za-z0-9][A-Za-z0-9/\-_.]{0,31}$/.test(f.roll_number.trim()))
      e.roll_number = "Use letters, digits and - / _ . only.";
    if (!f.enrollment_no.trim()) e.enrollment_no = "Enter your enrollment / registration number.";
  }
  if (step === 2) {
    if (!f.dob) e.dob = "Enter your date of birth.";
    if (!f.gender) e.gender = "Select an option.";
    if (!f.guardian_name.trim()) e.guardian_name = "Enter a parent or guardian's name.";
    if (!PHONE_RE.test(phone(f.guardian_phone))) e.guardian_phone = "Enter a 10–15 digit number.";
    else if (phone(f.guardian_phone) === phone(f.mobile))
      e.guardian_phone = "Give a guardian's number, not your own.";
    if (f.guardian_email && !EMAIL_RE.test(f.guardian_email.trim()))
      e.guardian_email = "Enter a valid email address or leave it blank.";
    if (f.address.trim().length < 5) e.address = "Enter your full address.";
  }
  if (step === 3) {
    if (!photo) e.photo = "Add a clear photo of your face.";
    else if (!["image/jpeg", "image/png", "image/webp"].includes(photo.type))
      e.photo = "Use a JPG, PNG or WEBP image.";
    else if (photo.size > 3 * 1024 * 1024) e.photo = "The photo must be under 3 MB.";
  }
  return e;
}

export default function SignupPage() {
  const router = useRouter();
  const [opts, setOpts] = useState<Options | null>(null);
  const [optsError, setOptsError] = useState<string | null>(null);
  const [form, setForm] = useState<Form>(EMPTY);
  const [photo, setPhoto] = useState<File | null>(null);
  const [preview, setPreview] = useState<string | null>(null);
  const [step, setStep] = useState(0);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    publicApi
      .get<Options>("public/academic-options")
      .then(setOpts)
      .catch((e) => setOptsError(e instanceof Error ? e.message : "Could not load classes."));
  }, []);

  useEffect(() => {
    if (!photo) return setPreview(null);
    const url = URL.createObjectURL(photo);
    setPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [photo]);

  useEffect(() => headingRef.current?.focus(), [step]);

  const dept = opts?.departments.find((d) => String(d.id) === form.department_id);
  const sections = useMemo(
    () =>
      (opts?.sections ?? []).filter(
        (s) =>
          String(s.department_id) === form.department_id &&
          String(s.year) === form.year &&
          (s.batch_id === null || String(s.batch_id) === form.batch_id),
      ),
    [opts, form.department_id, form.year, form.batch_id],
  );

  const set = (k: keyof Form) => (e: { target: { value: string } }) => {
    const v = e.target.value;
    setForm((f) => {
      const next = { ...f, [k]: v };
      // Changing the branch, year or batch invalidates the chosen section.
      if (k === "department_id" || k === "year" || k === "batch_id") next.section_id = "";
      if (k === "department_id") next.year = "";
      return next;
    });
    if (errors[k]) setErrors(({ [k]: _drop, ...rest }) => rest);
  };

  function next() {
    const e = validate(step, form, photo);
    setErrors(e);
    if (Object.keys(e).length === 0) setStep((s) => s + 1);
  }

  async function submit(ev: React.FormEvent) {
    ev.preventDefault();
    if (step < STEPS.length - 1) return next();
    const all = [0, 1, 2, 3].reduce((acc, s) => ({ ...acc, ...validate(s, form, photo) }), {});
    if (Object.keys(all).length) {
      setErrors(all);
      setStep(Math.min(...Object.keys(all).map((k) => STEP_OF[k] ?? 0)));
      return;
    }
    setBusy(true);
    setFormError(null);
    const fd = new FormData();
    for (const [k, v] of Object.entries(form)) if (k !== "confirm" && v !== "") fd.append(k, v.trim());
    fd.append("photo", photo as File);
    try {
      await publicApi.upload("auth/signup", fd);
      router.push(`/verify-email?email=${encodeURIComponent(form.email.trim().toLowerCase())}`);
    } catch (e) {
      const detail = e instanceof ApiFailure ? e.detail : undefined;
      const field = typeof detail?.field === "string" ? detail.field : undefined;
      const message = e instanceof Error ? e.message : "Sign-up failed.";
      if (field && field in STEP_OF) {
        setErrors({ [field]: message });
        setStep(STEP_OF[field]);
      } else {
        setFormError(message);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <PublicShell width={560} subtitle="Student registration">
      <AuthCard>
        <ol className="m-0 mb-5 grid list-none grid-cols-4 gap-1.5 p-0" aria-label="Progress">
          {STEPS.map((s, i) => (
            <li key={s} aria-current={i === step ? "step" : undefined}>
              <div
                className="h-1 rounded-full"
                style={{ background: i <= step ? "var(--ink)" : "var(--rule)" }}
              />
              <span className={`label mt-1 block text-[10.5px] ${i === step ? "text-ink" : ""}`}>
                {i + 1}. {s}
              </span>
            </li>
          ))}
        </ol>

        <h2 ref={headingRef} tabIndex={-1} className="display m-0 mb-4 text-[17px]">
          {["Create your account", "Your class", "About you", "Profile photo"][step]}
        </h2>

        {optsError ? <FormError>{optsError}</FormError> : null}
        <FormError>{formError}</FormError>

        <form onSubmit={submit} noValidate className="grid gap-3.5">
          {step === 0 ? (
            <>
              <TextField label="Full name" autoComplete="name" required value={form.full_name}
                         onChange={set("full_name")} error={errors.full_name} />
              <TextField label="Email" type="email" autoComplete="email" inputMode="email" required
                         value={form.email} onChange={set("email")} error={errors.email}
                         hint="We send a 6-digit code here to verify it." />
              <TextField label="Mobile number" type="tel" autoComplete="tel" inputMode="tel" required
                         value={form.mobile} onChange={set("mobile")} error={errors.mobile} />
              <div className="grid gap-3.5 sm:grid-cols-2">
                <TextField label="Password" type="password" autoComplete="new-password" required
                           value={form.password} onChange={set("password")} error={errors.password}
                           hint="8+ characters, a letter and a number." />
                <TextField label="Confirm password" type="password" autoComplete="new-password"
                           required value={form.confirm} onChange={set("confirm")}
                           error={errors.confirm} />
              </div>
            </>
          ) : null}

          {step === 1 ? (
            <>
              {opts && opts.departments.length === 0 ? (
                <FormError>
                  Registration is not open yet: no branches have been set up. Ask your college
                  office.
                </FormError>
              ) : null}
              <div className="grid gap-3.5 sm:grid-cols-2">
                <SelectField label="Branch" required value={form.department_id}
                             onChange={set("department_id")} error={errors.department_id}>
                  <option value="">Select…</option>
                  {opts?.departments.map((d) => (
                    <option key={d.id} value={d.id}>{d.code} — {d.name}</option>
                  ))}
                </SelectField>
                <SelectField label="Year" required value={form.year} onChange={set("year")}
                             error={errors.year} disabled={!dept}>
                  <option value="">Select…</option>
                  {Array.from({ length: dept?.years ?? 4 }, (_, i) => i + 1).map((y) => (
                    <option key={y} value={y}>Year {y}</option>
                  ))}
                </SelectField>
                <SelectField label="Batch" required value={form.batch_id} onChange={set("batch_id")}
                             error={errors.batch_id}>
                  <option value="">Select…</option>
                  {opts?.batches.map((b) => (
                    <option key={b.id} value={b.id}>{b.label}</option>
                  ))}
                </SelectField>
                <SelectField label="Section" required value={form.section_id}
                             onChange={set("section_id")} error={errors.section_id}
                             disabled={!form.department_id || !form.year || !form.batch_id}
                             hint={form.department_id && form.year && form.batch_id && sections.length === 0
                               ? "No sections exist for this combination yet." : undefined}>
                  <option value="">Select…</option>
                  {sections.map((s) => (
                    <option key={s.id} value={s.id}>Section {s.name}</option>
                  ))}
                </SelectField>
              </div>
              <div className="grid gap-3.5 sm:grid-cols-2">
                <TextField label="Roll number" required autoCapitalize="characters"
                           value={form.roll_number} onChange={set("roll_number")}
                           error={errors.roll_number} />
                <TextField label="Enrollment / registration no." required value={form.enrollment_no}
                           onChange={set("enrollment_no")} error={errors.enrollment_no} />
              </div>
            </>
          ) : null}

          {step === 2 ? (
            <>
              <div className="grid gap-3.5 sm:grid-cols-2">
                <TextField label="Date of birth" type="date" required value={form.dob}
                           onChange={set("dob")} error={errors.dob}
                           max={new Date().toISOString().slice(0, 10)} />
                <SelectField label="Gender" required value={form.gender} onChange={set("gender")}
                             error={errors.gender}>
                  <option value="">Select…</option>
                  <option value="female">Female</option>
                  <option value="male">Male</option>
                  <option value="non_binary">Non-binary</option>
                  <option value="other">Other</option>
                  <option value="prefer_not_to_say">Prefer not to say</option>
                </SelectField>
              </div>
              <div className="grid gap-3.5 sm:grid-cols-2">
                <TextField label="Parent / guardian name" required value={form.guardian_name}
                           onChange={set("guardian_name")} error={errors.guardian_name} />
                <TextField label="Guardian phone" type="tel" inputMode="tel" required
                           value={form.guardian_phone} onChange={set("guardian_phone")}
                           error={errors.guardian_phone} />
              </div>
              <TextField label="Guardian email (optional)" type="email" inputMode="email"
                         value={form.guardian_email} onChange={set("guardian_email")}
                         error={errors.guardian_email}
                         hint="If given, your guardian can receive attendance summaries." />
              <TextArea label="Address" required autoComplete="street-address" value={form.address}
                        onChange={set("address")} error={errors.address} />
            </>
          ) : null}

          {step === 3 ? (
            <div className="grid gap-3">
              <p className="m-0 text-[14px] text-ink/85">
                A clear, recent photo of your face for your profile. This is <strong>not</strong>{" "}
                used for face recognition — that is a separate, optional step after approval,
                which asks for your consent first.
              </p>
              <div className="flex flex-wrap items-center gap-4">
                <div
                  className="grid h-[112px] w-[112px] shrink-0 place-items-center overflow-hidden rounded-[3px] border border-rule bg-paper"
                  aria-hidden={!preview}
                >
                  {preview ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={preview} alt="Selected profile photo" className="h-full w-full object-cover" />
                  ) : (
                    <span className="label">No photo</span>
                  )}
                </div>
                <div className="min-w-0">
                  <label className="display inline-flex cursor-pointer rounded-[3px] border border-ink px-3.5 py-2 text-[12px] text-ink hover:bg-tint">
                    {photo ? "Change photo" : "Choose photo"}
                    <input
                      type="file"
                      accept="image/jpeg,image/png,image/webp"
                      className="sr-only"
                      onChange={(e) => {
                        setPhoto(e.target.files?.[0] ?? null);
                        setErrors(({ photo: _p, ...rest }) => rest);
                      }}
                    />
                  </label>
                  <p className="mt-1.5 text-[12.5px] text-ash">JPG, PNG or WEBP, up to 3 MB.</p>
                  {errors.photo ? (
                    <p role="alert" className="mt-1 text-[12.5px] text-oxide">{errors.photo}</p>
                  ) : null}
                </div>
              </div>
              <p className="m-0 text-[12.5px] text-ash">
                By registering you agree to the{" "}
                <Link href="/privacy" className="text-ink underline" target="_blank">privacy policy</Link>.
              </p>
            </div>
          ) : null}

          <div className="mt-1 flex items-center justify-between gap-2">
            {step > 0 ? (
              <Button onClick={() => setStep((s) => s - 1)}>Back</Button>
            ) : (
              <Link href="/login" className="text-[13.5px] text-ink underline-offset-2 hover:underline">
                Already registered? Sign in
              </Link>
            )}
            <Button type="submit" variant="primary" busy={busy}>
              {step < STEPS.length - 1 ? "Continue" : busy ? "Registering…" : "Register"}
            </Button>
          </div>
        </form>
      </AuthCard>
    </PublicShell>
  );
}
