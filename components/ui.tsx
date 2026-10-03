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
}: {
  children: ReactNode;
  className?: string;
  ruled?: boolean;
}) {
  return (
    <section
      className={clsx(
        "bg-card border border-rule rounded-[3px] shadow-card p-4 md:p-[18px]",
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
    <header className="flex flex-wrap items-baseline justify-between gap-3 mb-3">
      <h2 className="display text-[15px] text-ash m-0">{title}</h2>
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
  const toneClass = {
    ink: "text-ink",
    oxide: "text-oxide",
    amber: "text-amber",
    verdant: "text-verdant",
  }[tone];

  return (
    <Card className="transition-shadow hover:shadow-lift">
      <span className="label block">{label}</span>
      <div className={clsx("font-mono text-[30px] font-semibold leading-tight tnum", toneClass)}>
        {value}
      </div>
      {sub ? <div className="text-ash text-[12.5px] mt-0.5">{sub}</div> : null}
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
      className="inline-flex h-6 w-6 items-center justify-center rounded-[2px] border-[1.5px] font-mono text-[13px] font-semibold"
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
  const toneStyle = {
    neutral: { color: "var(--ash)", borderColor: "var(--rule)" },
    ok: { color: "var(--status-present)", borderColor: "var(--status-present)" },
    warn: { color: "var(--status-late)", borderColor: "var(--status-late)" },
    bad: { color: "var(--status-absent)", borderColor: "var(--status-absent)" },
  }[tone];

  return (
    <span
      className="display inline-block rounded-full border px-2 py-[2px] text-[10.5px] tracking-[0.1em] whitespace-nowrap"
      style={toneStyle}
    >
      {children}
    </span>
  );
}

/* ---------------------------------------------------------------- banner */

export function Banner({ children, bad = false }: { children: ReactNode; bad?: boolean }) {
  return (
    <div
      className="mb-3 rounded-r-[2px] border-l-4 px-3.5 py-2.5 text-[13.5px]"
      style={{
        borderLeftColor: bad ? "var(--oxide)" : "var(--amber)",
        background: bad
          ? "color-mix(in srgb, var(--oxide) 11%, transparent)"
          : "color-mix(in srgb, var(--amber) 10%, transparent)",
      }}
    >
      {children}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="py-6 text-center text-[13.5px] text-ash">{children}</div>;
}
