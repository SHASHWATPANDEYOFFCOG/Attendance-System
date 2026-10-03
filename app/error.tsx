"use client";

/** Last-resort error page: something threw while rendering. Offers a retry, never a stack trace. */
import { useEffect } from "react";

import Link from "next/link";

export default function ErrorPage({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    console.error(error);
  }, [error]);
  return (
    <main className="relative z-[1] grid min-h-[70vh] place-items-center px-4">
      <div className="max-w-[460px] text-center">
        <h1 className="display m-0 text-[24px]">Something went wrong</h1>
        <p className="text-[14.5px] text-ash">
          This page could not be shown. Your data is safe — try again, and if it keeps happening tell the college office
          {error.digest ? <> (reference <span className="font-mono">{error.digest}</span>)</> : null}.
        </p>
        <div className="mt-3 flex justify-center gap-2">
          <button type="button" onClick={reset} className="display cursor-pointer rounded-[3px] border px-4 py-2 text-[12px]"
                  style={{ background: "var(--ink)", borderColor: "var(--ink)", color: "var(--card)" }}>Try again</button>
          <Link href="/" className="display rounded-[3px] border border-ink px-4 py-2 text-[12px] text-ink no-underline">Home</Link>
        </div>
      </div>
    </main>
  );
}
