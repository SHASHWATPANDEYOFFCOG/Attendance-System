"use client";

import { Suspense, useState } from "react";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

/**
 * The sign-in form behind both doors: /login for students (and guardians), /authority/login
 * for teachers, HODs and admins. The route handler refuses an account at the wrong door
 * before any cookie is set, and says which door to use.
 *
 * `useSearchParams` opts the subtree out of prerendering, so it must sit inside a Suspense
 * boundary or the route fails to build. Only the form needs the ?next= param; the page shell
 * around it stays static.
 */
export type Portal = "student" | "authority";

const COPY: Record<Portal, { subtitle: string; heading: string; user: string }> = {
  student: { subtitle: "Student portal", heading: "Student sign in", user: "Email or roll number" },
  authority: { subtitle: "Authority portal · teachers, HODs, administrators", heading: "Authority sign in",
               user: "Username or email" },
};

export function SignIn({ portal }: { portal: Portal }) {
  return (
    <Suspense fallback={<LoginShell portal={portal} />}>
      <LoginForm portal={portal} />
    </Suspense>
  );
}

function LoginForm({ portal }: { portal: Portal }) {
  const router = useRouter();
  const params = useSearchParams();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<{ text: string; switchTo?: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password, portal }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        if (body.code === "email_unverified") {
          router.push(`/verify-email?email=${encodeURIComponent(body.email ?? username)}`);
          return;
        }
        setError({ text: body.error ?? "Sign in failed", switchTo: body.code === "wrong_portal" ? body.login : undefined });
        return;
      }
      const { home } = (await res.json().catch(() => ({}))) as { home?: string };
      // Only follow ?next= to a path on this site — never an absolute URL (open redirect).
      const next = params.get("next");
      const safeNext = next && next.startsWith("/") && !next.startsWith("//") ? next : null;
      router.push(safeNext || home || "/");
      router.refresh();
    } catch {
      setError({ text: "Could not reach the server." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <LoginShell portal={portal}>
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
              {error.text}
              {error.switchTo ? (
                <>
                  {" "}
                  <Link href={error.switchTo} className="font-semibold text-ink underline">
                    Go to the {error.switchTo.startsWith("/authority") ? "authority" : "student"} sign in
                  </Link>
                </>
              ) : null}
            </div>
          ) : null}

          <h2 className="display m-0 mb-4 text-[17px]">{COPY[portal].heading}</h2>
          <div className="mb-3.5">
            <label className="label block" htmlFor="username">
              {COPY[portal].user}
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
            {portal === "student" ? (
              <Link href="/signup" className="text-ink underline-offset-2 hover:underline">
                New student? Register
              </Link>
            ) : (
              <Link href="/authority/register" className="text-ink underline-offset-2 hover:underline">
                New staff member? Register
              </Link>
            )}
          </div>
          <p className="mb-0 mt-4 border-t border-rule pt-3 text-center text-[13.5px] text-ash">
            {portal === "student" ? (
              <>Teacher, HOD or admin? <Link href="/authority/login" className="font-semibold text-ink underline-offset-2 hover:underline">Authority sign in</Link></>
            ) : (
              <>Student? <Link href="/login" className="font-semibold text-ink underline-offset-2 hover:underline">Student sign in</Link></>
            )}
          </p>
      </form>
    </LoginShell>
  );
}

/** The static page shell. Also the Suspense fallback, so the layout never jumps. */
function LoginShell({ portal, children }: { portal: Portal; children?: React.ReactNode }) {
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
          <p className="mt-2 font-mono text-xs text-ash">{COPY[portal].subtitle}</p>
        </header>
        {children}
      </div>
    </main>
  );
}

