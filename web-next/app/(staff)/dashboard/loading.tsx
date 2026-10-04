/** Skeletons, not a spinner: the layout is known ahead of the data, so hold its shape and
 *  avoid the layout shift a spinner-then-content swap causes. */
import { Skeleton as Block } from "@/components/states";

export default function Loading() {
  return (
    <main className="relative z-[1] mx-auto max-w-[1280px] px-4 pb-16 pt-6 md:px-8" aria-busy="true">
      <div className="mb-5 border-b border-[color-mix(in_srgb,var(--ink)_20%,transparent)] pb-3">
        <Block className="h-7 w-64" />
        <Block className="mt-2 h-3 w-80" />
      </div>

      <div className="mb-4 grid grid-cols-2 gap-4 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <div key={i} className="glass border-rule rounded-[var(--radius-lg)] border p-4 shadow-card">
            <Block className="h-3 w-24" />
            <Block className="mt-3 h-8 w-20" />
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]">
        <div className="grid gap-4">
          <div className="glass border-rule rounded-[var(--radius-lg)] border p-4 shadow-card">
            <Block className="h-3 w-32" />
            <Block className="mt-3 h-[240px] w-full" />
          </div>
          <div className="glass border-rule rounded-[var(--radius-lg)] border p-4 shadow-card">
            <Block className="h-3 w-40" />
            <Block className="mt-3 h-16 w-full" />
          </div>
        </div>
        <div className="grid gap-4">
          <div className="glass border-rule rounded-[var(--radius-lg)] border p-4 shadow-card">
            <Block className="h-3 w-20" />
            <Block className="mt-3 h-40 w-full" />
          </div>
          <div className="glass border-rule rounded-[var(--radius-lg)] border p-4 shadow-card">
            <Block className="h-3 w-24" />
            <Block className="mt-3 h-48 w-full" />
          </div>
        </div>
      </div>
      <span className="sr-only">Loading dashboard…</span>
    </main>
  );
}
