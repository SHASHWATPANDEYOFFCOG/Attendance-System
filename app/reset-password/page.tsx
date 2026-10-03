"use client";

import { Suspense, useState } from "react";

import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { publicApi } from "@/lib/client";
import { AuthCard, PublicShell } from "@/components/public-shell";
import { Button, FormError, TextField } from "@/components/forms";
import { Banner } from "@/components/ui";

export default function ResetPasswordPage() {
  return (
    <PublicShell subtitle="Choose a new password">
      <Suspense fallback={<AuthCard title="Set a new password">Loading…</AuthCard>}>
        <ResetForm />
      </Suspense>
    </PublicShell>
  );
}

function ResetForm() {
  const token = useSearchParams().get("token") ?? "";
  const [pw, setPw] = useState("");
  const [confirm, setConfirm] = useState("");
  const [errors, setErrors] = useState<{ pw?: string; confirm?: string }>({});
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const errs: typeof errors = {};
    if (pw.length < 8) errs.pw = "Use at least 8 characters.";
    else if (!/[A-Za-z]/.test(pw) || !/\d/.test(pw)) errs.pw = "Use at least one letter and one number.";
    if (confirm !== pw) errs.confirm = "The passwords do not match.";
    setErrors(errs);
    if (Object.keys(errs).length) return;
    setBusy(true);
    setError(null);
    try {
      await publicApi.post("auth/reset-password", { token, password: pw });
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reset the password.");
    } finally {
      setBusy(false);
    }
  }

  if (!token) {
    return (
      <AuthCard title="Link incomplete">
        <p className="mt-0 text-[14px]">This reset link is missing its token. Open the link from the email again, or request a new one.</p>
        <Link href="/forgot-password" className="text-[13.5px] text-ink underline">Request a new link</Link>
      </AuthCard>
    );
  }
  if (done) {
    return (
      <AuthCard title="Password updated">
        <Banner>Your password has been changed and other devices have been signed out.</Banner>
        <Link
          href="/login"
          className="display inline-flex rounded-[3px] border px-4 py-2.5 text-[12px] no-underline"
          style={{ background: "var(--ink)", borderColor: "var(--ink)", color: "var(--card)" }}
        >
          Sign in
        </Link>
      </AuthCard>
    );
  }
  return (
    <AuthCard title="Set a new password">
      <FormError>
        {error ? (
          <>
            {error}{" "}
            <Link href="/forgot-password" className="text-ink underline">Request a new link</Link>
          </>
        ) : null}
      </FormError>
      <form onSubmit={submit} className="grid gap-3.5" noValidate>
        <TextField label="New password" type="password" autoComplete="new-password" required
                   value={pw} onChange={(e) => setPw(e.target.value)} error={errors.pw}
                   hint="8+ characters, a letter and a number." />
        <TextField label="Confirm new password" type="password" autoComplete="new-password" required
                   value={confirm} onChange={(e) => setConfirm(e.target.value)} error={errors.confirm} />
        <Button type="submit" variant="primary" busy={busy}>Update password</Button>
      </form>
    </AuthCard>
  );
}
