/**
 * Base components. Deliberately small and unstyled-by-prop: the tokens in globals.css do the
 * work, so a component cannot drift off-palette by accepting a colour.
 */
import type { ReactNode } from "react";

import { clsx } from "clsx";

/* ------------------------------------------------------------------- card */

export function Card({
  children,
  className,
  ruled = false,
  interactive = false,
  featured = false,
}: {
  children: ReactNode;
  className?: string;
  ruled?: boolean;
  /** Lifts and lights its border on hover (use for cards that are links or open something). */
  interactive?: boolean;
  /** Gradient hairline border for the one card that matters most on a screen. */
  featured?: boolean;
}) {
  return (
    <section
      className={clsx(
        "rounded-[var(--radius-lg)] p-4 shadow-card md:p-5",
        featured ? "ring-gradient" : "glass border border-rule",
        interactive && "surface-interactive",
        ruled && "ruled",
        className,
      )}
    >
      {children}
    </section>
  );
}

export function CardHeader({ title, meta }: { title: string; meta?: ReactNode }) {
  return (
    <header className="mb-3.5 flex flex-wrap items-center justify-between gap-3">
      <h2 className="display m-0 text-[15.5px] text-ink">{title}</h2>
      {meta ? <span className="font-mono text-xs text-ash tnum">{meta}</span> : null}
    </header>
  );
}

/* ------------------------------------------------------------------- stat */

export function StatTile({
  label,
  value,
  tone = "ink",
  sub,
}: {
  label: string;
  value: ReactNode;
  tone?: "ink" | "oxide" | "amber" | "verdant";
  sub?: string;
}) {
  const toneColor = {
    ink: "var(--accent)",
    oxide: "var(--oxide)",
    amber: "var(--amber)",
    verdant: "var(--verdant)",
  }[tone];

  return (
    <Card interactive className="relative overflow-hidden">
      {/* A soft colour wash in the tile's tone, top-right: hierarchy by colour, not by size alone. */}
      <span aria-hidden className="pointer-events-none absolute -right-8 -top-10 h-28 w-28 rounded-full opacity-25 blur-2xl"
            style={{ background: toneColor }} />
      <span className="label relative block">{label}</span>
      <div className="relative mt-1 font-mono text-[30px] font-semibold leading-tight tracking-[-0.02em] tnum"
           style={{ color: tone === "ink" ? "var(--ink)" : toneColor }}>
        {value}
      </div>
      {sub ? <div className="relative mt-0.5 text-[12.5px] text-ash">{sub}</div> : null}
    </Card>
  );
}

/* ------------------------------------------------------- register marks */

const MARK_LETTER: Record<string, string> = {
  present: "P",
  late: "L",
  absent: "A",
  partial: "~",
  left_early: "<",
  on_duty: "D",
  excused: "E",
  on_leave: "O",
  needs_review: "?",
};

const MARK_COLOR: Record<string, string> = {
  present: "var(--status-present)",
  late: "var(--status-late)",
  absent: "var(--status-absent)",
  partial: "var(--status-late)",
  left_early: "var(--status-late)",
  on_duty: "var(--status-present)",
  excused: "var(--status-excused)",
  on_leave: "var(--status-leave)",
  needs_review: "var(--status-absent)",
};

/**
 * The register mark. Status is carried by the LETTER first and colour second, so it survives
 * colour-blindness, greyscale printing and forced-colors mode.
 */
export function Mark({ status }: { status: string }) {
  const letter = MARK_LETTER[status] ?? "?";
  return (
    <span
      title={status.replace(/_/g, " ")}
      aria-label={status.replace(/_/g, " ")}
      className="inline-flex h-6 w-6 items-center justify-center rounded-[var(--radius-sm)] border-[1.5px] font-mono text-[13px] font-semibold"
      style={{ color: MARK_COLOR[status] ?? "var(--ash)", borderColor: "currentColor" }}
    >
      {letter}
    </span>
  );
}

export function Pill({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "ok" | "warn" | "bad";
}) {
  const color = {
    neutral: "var(--ash)",
    ok: "var(--status-present)",
    warn: "var(--status-late)",
    bad: "var(--status-absent)",
  }[tone];

  return (
    <span
      className="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-[3px] text-[11.5px] font-semibold"
      style={{ color, background: `color-mix(in srgb, ${color} 14%, transparent)`, border: `1px solid color-mix(in srgb, ${color} 30%, transparent)` }}
    >
      <span aria-hidden className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
      {children}
    </span>
  );
}

/* ---------------------------------------------------------------- banner */

export function Banner({ children, bad = false }: { children: ReactNode; bad?: boolean }) {
  return (
    <div
      className="mb-3 rounded-[var(--radius)] border px-4 py-3 text-[13.5px]"
      style={{
        borderColor: bad ? "color-mix(in srgb, var(--oxide) 35%, transparent)" : "color-mix(in srgb, var(--accent) 28%, transparent)",
        background: bad
          ? "color-mix(in srgb, var(--oxide) 10%, var(--card))"
          : "color-mix(in srgb, var(--accent) 7%, var(--card))",
        boxShadow: `inset 3px 0 0 ${bad ? "var(--oxide)" : "var(--accent)"}`,
      }}
    >
      {children}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="py-6 text-center text-[13.5px] text-ash">{children}</div>;
}
