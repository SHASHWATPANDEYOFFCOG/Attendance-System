"use client";

/**
 * Form controls in the register's visual language. Every field takes an `error` and renders
 * it inline, wired to the input with aria-describedby / aria-invalid, so a screen reader hears
 * the problem on focus — not only a sighted user who spots red text.
 */
import { forwardRef, useId } from "react";
import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";

import { clsx } from "clsx";

export const inputClass =
  "w-full rounded-[3px] border bg-card px-3 py-2.5 text-[14px] text-ink placeholder:text-ash/70 disabled:opacity-60";

function fieldBorder(error?: string | null) {
  return error ? "border-oxide" : "border-rule focus:border-ink";
}

type FieldShell = { label: string; error?: string | null; hint?: ReactNode; required?: boolean };

function Shell({
  id,
  label,
  error,
  hint,
  required,
  children,
}: FieldShell & { id: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <label htmlFor={id} className="label mb-1 block">
        {label}
        {required ? <span aria-hidden="true" className="text-oxide"> *</span> : null}
      </label>
      {children}
      {error ? (
        <p id={`${id}-error`} role="alert" className="mt-1 text-[12.5px] text-oxide">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="mt-1 text-[12.5px] text-ash">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

export const TextField = forwardRef<
  HTMLInputElement,
  InputHTMLAttributes<HTMLInputElement> & FieldShell
>(function TextField({ label, error, hint, required, className, id, ...rest }, ref) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <Shell id={fid} label={label} error={error} hint={hint} required={required}>
      <input
        ref={ref}
        id={fid}
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${fid}-error` : hint ? `${fid}-hint` : undefined}
        className={clsx(inputClass, fieldBorder(error), className)}
        {...rest}
      />
    </Shell>
  );
});

export function SelectField({
  label,
  error,
  hint,
  required,
  className,
  id,
  children,
  ...rest
}: SelectHTMLAttributes<HTMLSelectElement> & FieldShell & { children: ReactNode }) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <Shell id={fid} label={label} error={error} hint={hint} required={required}>
      <select
        id={fid}
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${fid}-error` : hint ? `${fid}-hint` : undefined}
        className={clsx(inputClass, fieldBorder(error), className)}
        {...rest}
      >
        {children}
      </select>
    </Shell>
  );
}

export function TextArea({
  label,
  error,
  hint,
  required,
  className,
  id,
  ...rest
}: TextareaHTMLAttributes<HTMLTextAreaElement> & FieldShell) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <Shell id={fid} label={label} error={error} hint={hint} required={required}>
      <textarea
        id={fid}
        required={required}
        aria-invalid={error ? true : undefined}
        aria-describedby={error ? `${fid}-error` : hint ? `${fid}-hint` : undefined}
        className={clsx(inputClass, fieldBorder(error), "min-h-[96px]", className)}
        {...rest}
      />
    </Shell>
  );
}

export function Checkbox({
  label,
  className,
  ...rest
}: InputHTMLAttributes<HTMLInputElement> & { label: ReactNode }) {
  return (
    <label className={clsx("flex cursor-pointer items-start gap-2.5 text-[14px]", className)}>
      <input type="checkbox" className="mt-[3px] h-4 w-4 shrink-0 accent-[var(--ink)]" {...rest} />
      <span>{label}</span>
    </label>
  );
}

type Variant = "primary" | "secondary" | "danger" | "ghost";

export function Button({
  variant = "secondary",
  busy = false,
  className,
  children,
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; busy?: boolean }) {
  const style =
    variant === "primary"
      ? { background: "var(--ink)", borderColor: "var(--ink)", color: "var(--card)" }
      : variant === "danger"
        ? { background: "var(--oxide)", borderColor: "var(--oxide)", color: "var(--card)" }
        : variant === "ghost"
          ? { background: "transparent", borderColor: "transparent", color: "var(--ink)" }
          : { background: "transparent", borderColor: "var(--ink)", color: "var(--ink)" };
  return (
    <button
      type="button"
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      className={clsx(
        "display inline-flex cursor-pointer items-center justify-center gap-1.5 rounded-[3px] border px-3.5 py-2 text-[12px] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50",
        variant === "ghost" && "hover:bg-tint",
        className,
      )}
      style={style}
      {...rest}
    >
      {busy ? <Spinner /> : null}
      {children}
    </button>
  );
}

export function Spinner({ size = 12 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      className="animate-spin"
      aria-hidden="true"
      fill="none"
      stroke="currentColor"
      strokeWidth="3"
    >
      <circle cx="12" cy="12" r="9" strokeOpacity="0.25" />
      <path d="M21 12a9 9 0 0 0-9-9" strokeLinecap="round" />
    </svg>
  );
}

/** Form-level error banner (e.g. a 409 that is not tied to one field). */
export function FormError({ children }: { children?: ReactNode }) {
  if (!children) return null;
  return (
    <div
      role="alert"
      className="mb-3 rounded-r-[2px] border-l-4 px-3 py-2 text-[13.5px]"
      style={{
        borderLeftColor: "var(--oxide)",
        background: "color-mix(in srgb, var(--oxide) 11%, transparent)",
      }}
    >
      {children}
    </div>
  );
}

/** Map an ApiFailure onto {field: message} for inline display. */
export function fieldErrorsFrom(err: unknown): { field?: string; message: string } {
  if (err && typeof err === "object" && "detail" in err) {
    const d = (err as { detail?: { field?: string; message?: string } }).detail;
    if (d?.field) return { field: d.field, message: d.message ?? String(err) };
  }
  return { message: err instanceof Error ? err.message : String(err) };
}
