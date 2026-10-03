"use client";

import { Suspense, useState } from "react";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

/**
 * `useSearchParams` opts the subtree out of prerendering, so it must sit inside a Suspense
 * boundary or the whole /login route fails to build. Only the form needs the ?next= param;
 * the page shell around it stays static.
 */
export default function LoginPage() {
  return (
    <Suspense fallback={<LoginShell />}>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        if (body.code === "email_unverified") {
          router.push(`/verify-email?email=${encodeURIComponent(body.email ?? username)}`);
          return;
        }
        setError(body.error ?? "Sign in failed");
        return;
      }
      const { home } = (await res.json().catch(() => ({}))) as { home?: string };
      // Only follow ?next= to a path on this site — never an absolute URL (open redirect).
      const next = params.get("next");
      const safeNext = next && next.startsWith("/") && !next.startsWith("//") ? next : null;
      router.push(safeNext || home || "/");
      router.refresh();
    } catch {
      setError("Could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <LoginShell>
      <form
          onSubmit={submit}
          className="bg-card border border-rule rounded-[3px] p-6 shadow-lift"
        >
          {error ? (
            <div
              role="alert"
              className="mb-3 rounded-r-[2px] border-l-4 px-3 py-2 text-[13.5px]"
              style={{
                borderLeftColor: "var(--oxide)",
                background: "color-mix(in srgb, var(--oxide) 11%, transparent)",
              }}
            >
              {error}
            </div>
          ) : null}

          <div className="mb-3.5">
            <label className="label block" htmlFor="username">
              Username, email or roll number
            </label>
            <input
              id="username"
              name="username"
              autoComplete="username"
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              className="w-full rounded-[3px] border border-rule bg-card px-3 py-2.5 text-[14px] text-ink"
            />
          </div>

          <div className="mb-4">
            <label className="label block" htmlFor="password">
              Password
            </label>
            <input
              id="password"
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-[3px] border border-rule bg-card px-3 py-2.5 text-[14px] text-ink"
            />
          </div>

          <button
            type="submit"
            disabled={busy}
            className="display w-full cursor-pointer rounded-[3px] border px-4 py-2.5 text-[12px] disabled:opacity-50"
            style={{ background: "var(--ink)", borderColor: "var(--ink)", color: "var(--card)" }}
          >
            {busy ? "Signing in..." : "Sign in"}
          </button>
          <div className="mt-4 flex flex-wrap justify-between gap-2 text-[13.5px]">
            <Link href="/forgot-password" className="text-ink underline-offset-2 hover:underline">
              Forgot password?
            </Link>
            <Link href="/signup" className="text-ink underline-offset-2 hover:underline">
              New student? Register
            </Link>
          </div>
      </form>
    </LoginShell>
  );
}

/** The static page shell. Also the Suspense fallback, so the layout never jumps. */
function LoginShell({ children }: { children?: React.ReactNode }) {
  return (
    <main className="relative z-[1] grid min-h-screen place-items-center px-4">
      <div className="w-full max-w-[420px]">
        <header className="mb-6 text-center">
          <h1
            className="display m-0 text-[30px]"
            style={{
              background: "linear-gradient(100deg, var(--ink) 30%, var(--oxide))",
              WebkitBackgroundClip: "text",
              backgroundClip: "text",
              color: "transparent",
            }}
          >
            Attendance Register
          </h1>
          <div
            className="mx-auto mt-2.5 h-[2px]"
            style={{
              background: "linear-gradient(90deg, var(--ink), var(--oxide) 55%, transparent)",
            }}
          />
          <p className="mt-2 font-mono text-xs text-ash">Occlusion-robust face recognition</p>
        </header>
        {children}
      </div>
    </main>
  );
}

