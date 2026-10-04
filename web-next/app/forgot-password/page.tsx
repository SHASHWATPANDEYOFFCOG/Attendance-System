"use client";

import { useState } from "react";

import Link from "next/link";

import { publicApi } from "@/lib/client";
import { AuthCard, PublicShell } from "@/components/public-shell";
import { Button, FormError, TextField } from "@/components/forms";
import { Banner } from "@/components/ui";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!/^[^@\s]+@[^@\s]+\.[a-z]{2,}$/i.test(email.trim())) return setError("Enter a valid email address.");
    setBusy(true);
    setError(null);
    try {
      const res = await publicApi.post<{ message: string }>("auth/forgot-password", { email: email.trim() });
      setSent(res.message);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send the reset link.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <PublicShell subtitle="Reset your password">
      <AuthCard title="Forgot your password?">
        {sent ? (
          <>
            <Banner>{sent} The link works once and expires in 30 minutes.</Banner>
            <Link href="/login" className="text-[13.5px] text-ink underline">Back to sign in</Link>
          </>
        ) : (
          <form onSubmit={submit} className="grid gap-3.5" noValidate>
            <p className="m-0 text-[14px] text-ink/85">
              Enter the email address on your account and we will send you a reset link.
            </p>
            <FormError>{error}</FormError>
            <TextField label="Email" type="email" autoComplete="email" inputMode="email" required
                       value={email} onChange={(e) => setEmail(e.target.value)} />
            <Button type="submit" variant="primary" busy={busy}>Send reset link</Button>
            <Link href="/login" className="text-[13.5px] text-ink underline-offset-2 hover:underline">
              Back to sign in
            </Link>
          </form>
        )}
      </AuthCard>
    </PublicShell>
  );
}
