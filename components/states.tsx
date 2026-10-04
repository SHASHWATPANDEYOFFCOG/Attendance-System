/** Loading, empty and error states shared by every page, so none of them is ever blank. */
import type { ReactNode } from "react";

export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      className={`animate-pulse rounded-[var(--radius)] ${className}`}
      style={{ background: "var(--tint-hard)" }}
      aria-hidden="true"
    />
  );
}

export function PageLoading({ rows = 4 }: { rows?: number }) {
  return (
    <div aria-busy="true" className="grid gap-3">
      <span className="sr-only">Loading…</span>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="rounded-[var(--radius)] border border-rule bg-card p-4 shadow-card">
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
      className="rounded-[var(--radius-sm)] border-l-4 px-3.5 py-3 text-[14px]"
      style={{
        borderLeftColor: "var(--oxide)",
        background: "color-mix(in srgb, var(--oxide) 11%, transparent)",
      }}
    >
      <strong className="label mb-0.5 block">Something went wrong</strong>
      {message}
      {retry ? (
        <div className="mt-2">
          <button
            type="button"
            onClick={retry}
            className="display cursor-pointer rounded-[var(--radius)] border border-ink bg-transparent px-3 py-1.5 text-[12px] text-ink"
          >
            Try again
          </button>
        </div>
      ) : null}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-[var(--radius)] border border-dashed border-rule px-4 py-8 text-center">
      <p className="display m-0 text-[14px] text-ash">{title}</p>
      {children ? <div className="mt-1.5 text-[13.5px] text-ash">{children}</div> : null}
    </div>
  );
}
