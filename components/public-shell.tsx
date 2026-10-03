/** Frame for the signed-out pages: sign in, sign up, verification, password reset. */
import type { ReactNode } from "react";

import Link from "next/link";

export function PublicShell({
  children,
  width = 420,
  subtitle = "Smart attendance",
}: {
  children: ReactNode;
  width?: number;
  subtitle?: string;
}) {
  return (
    <main className="relative z-[1] grid min-h-screen place-items-center px-4 py-10">
      <div className="w-full" style={{ maxWidth: width }}>
        <header className="mb-6 text-center">
          <Link href="/login" className="no-underline">
            <h1
              className="display m-0 text-[28px]"
              style={{
                background: "linear-gradient(100deg, var(--ink) 30%, var(--oxide))",
                WebkitBackgroundClip: "text",
                backgroundClip: "text",
                color: "transparent",
              }}
            >
              Attendance Register
            </h1>
          </Link>
          <div
            className="mx-auto mt-2.5 h-[2px]"
            style={{ background: "linear-gradient(90deg, var(--ink), var(--oxide) 55%, transparent)" }}
          />
          <p className="mt-2 font-mono text-xs text-ash">{subtitle}</p>
        </header>
        {children}
        <p className="mt-6 text-center text-[12.5px] text-ash">
          <Link href="/privacy" className="text-ash underline-offset-2 hover:underline">
            Privacy policy
          </Link>
          {" · "}
          <Link href="/guide" className="text-ash underline-offset-2 hover:underline">
            Help
          </Link>
        </p>
      </div>
    </main>
  );
}

export function AuthCard({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className="rounded-[3px] border border-rule bg-card p-5 shadow-lift sm:p-6">
      {title ? <h2 className="display m-0 mb-4 text-[17px]">{title}</h2> : null}
      {children}
    </section>
  );
}
