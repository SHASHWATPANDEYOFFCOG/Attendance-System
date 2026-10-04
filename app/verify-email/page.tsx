"use client";

import { Suspense, useEffect, useState } from "react";

import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { publicApi } from "@/lib/client";
import { AuthCard, PublicShell } from "@/components/public-shell";
import { Button, FormError, TextField } from "@/components/forms";
import { Banner } from "@/components/ui";

export default function VerifyEmailPage() {
  return (
    <PublicShell subtitle="Verify your email">
      <Suspense fallback={<AuthCard title="Verify your email">Loading…</AuthCard>}>
        <VerifyForm />
      </Suspense>
    </PublicShell>
  );
}

function VerifyForm() {
  const params = useSearchParams();
  const [email, setEmail] = useState(params.get("email") ?? "");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const [signInAt, setSignInAt] = useState("/login");
  const [busy, setBusy] = useState(false);
  const [cooldown, setCooldown] = useState(0);

  useEffect(() => {
    if (cooldown <= 0) return;
    const t = setTimeout(() => setCooldown((c) => c - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  async function verify(e: React.FormEvent) {
    e.preventDefault();
    if (!/^\d{6}$/.test(code.trim())) return setError("Enter the 6-digit code from the email.");
    setBusy(true);
    setError(null);
    try {
      const res = await publicApi.post<{ message: string; portal?: string }>("auth/verify-email", {
        email: email.trim(),
        code: code.trim(),
      });
      setNotice(res.message);
      if (res.portal === "authority") setSignInAt("/authority/login");
      setDone(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Verification failed.");
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    setError(null);
    try {
      const res = await publicApi.post<{ message: string }>("auth/resend-otp", { email: email.trim() });
      setNotice(res.message);
      setCooldown(60);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send a new code.");
    }
  }

  if (done) {
    return (
      <AuthCard title="Email verified">
        <Banner>{notice}</Banner>
        <Link
          href={signInAt}
          className="display mt-2 inline-flex rounded-[3px] border px-4 py-2.5 text-[12px] no-underline"
          style={{ background: "var(--ink)", borderColor: "var(--ink)", color: "var(--card)" }}
        >
          Sign in
        </Link>
      </AuthCard>
    );
  }

  return (
    <AuthCard title="Verify your email">
      <p className="mt-0 text-[14px] text-ink/85">
        We sent a 6-digit code to <strong>{email || "your email"}</strong>. It expires in 10
        minutes. Check your spam folder if it has not arrived.
      </p>
      {notice ? <Banner>{notice}</Banner> : null}
      <FormError>{error}</FormError>
      <form onSubmit={verify} className="grid gap-3.5" noValidate>
        {!params.get("email") ? (
          <TextField label="Email" type="email" required value={email}
                     onChange={(e) => setEmail(e.target.value)} />
        ) : null}
        <TextField
          label="Verification code"
          inputMode="numeric"
          autoComplete="one-time-code"
          pattern="\d{6}"
          maxLength={6}
          required
          value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
          className="font-mono text-[20px] tracking-[0.4em]"
        />
        <Button type="submit" variant="primary" busy={busy}>Verify</Button>
      </form>
      <div className="mt-4 flex items-center justify-between text-[13.5px]">
        <button
          type="button"
          onClick={resend}
          disabled={cooldown > 0 || !email}
          className="cursor-pointer border-0 bg-transparent p-0 text-ink underline-offset-2 hover:underline disabled:cursor-not-allowed disabled:text-ash"
        >
          {cooldown > 0 ? `Resend code in ${cooldown}s` : "Resend code"}
        </button>
        <Link href="/login" className="text-ink underline-offset-2 hover:underline">Back to sign in</Link>
      </div>
    </AuthCard>
  );
}
