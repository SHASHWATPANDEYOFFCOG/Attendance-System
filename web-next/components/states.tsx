/** Loading, empty and error states shared by every page, so none of them is ever blank. */
import type { ReactNode } from "react";

import { AlertTriangle, Inbox, RotateCw } from "lucide-react";

/** A shimmering placeholder block (globals.css .skeleton-shimmer; still under reduced motion). */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton-shimmer rounded-[var(--radius)] ${className}`} aria-hidden="true" />;
}

export function PageLoading({ rows = 4 }: { rows?: number }) {
  return (
    <div aria-busy="true" className="grid gap-3">
      <span className="sr-only">Loading…</span>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="glass rounded-[var(--radius-lg)] border border-rule p-4 shadow-card"
             style={{ opacity: 1 - i * 0.12 }}>
          <Skeleton className="h-3 w-32" />
          <Skeleton className="mt-3 h-6 w-full" />
        </div>
      ))}
    </div>
  );
}

export function PageError({ message, retry }: { message: string; retry?: () => void }) {
  return (
    <div
      role="alert"
      className="animate-pop-in flex gap-3 rounded-[var(--radius-lg)] border px-4 py-3.5 text-[14px]"
      style={{
        borderColor: "color-mix(in srgb, var(--oxide) 35%, transparent)",
        background: "color-mix(in srgb, var(--oxide) 9%, transparent)",
      }}
    >
      <AlertTriangle size={18} className="mt-0.5 shrink-0" style={{ color: "var(--oxide)" }} aria-hidden="true" />
      <div className="min-w-0">
        <strong className="mb-0.5 block text-[14px] font-semibold text-ink">Something went wrong</strong>
        <span className="text-ash">{message}</span>
        {retry ? (
          <div className="mt-2.5">
            <button
              type="button"
              onClick={retry}
              className="btn inline-flex cursor-pointer items-center gap-1.5 rounded-[var(--radius)] border border-rule bg-card px-3 py-1.5 text-[13px] font-medium text-ink hover:bg-tint"
            >
              <RotateCw size={14} aria-hidden="true" /> Try again
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center rounded-[var(--radius-lg)] border border-dashed border-rule px-4 py-9 text-center">
      <span className="mb-3 grid h-11 w-11 place-items-center rounded-2xl"
            style={{ background: "color-mix(in srgb, var(--accent) 12%, transparent)", color: "var(--accent)" }}>
        <Inbox size={20} aria-hidden="true" />
      </span>
      <p className="m-0 text-[14.5px] font-semibold text-ink">{title}</p>
      {children ? <div className="mt-1.5 max-w-[46ch] text-[13.5px] text-ash">{children}</div> : null}
    </div>
  );
}
