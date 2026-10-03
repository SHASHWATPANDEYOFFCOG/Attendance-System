"use client";

/**
 * Toasts and confirmation dialogs.
 *
 * Toasts live in an aria-live region, so a screen reader announces "Leave approved" without the
 * user hunting for it. Destructive actions go through `confirm()`, a real modal dialog with focus
 * moved into it and Escape to cancel — never `window.confirm`, which mobile Safari can suppress.
 */
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

type Tone = "ok" | "bad" | "info";
type Toast = { id: number; tone: Tone; text: string };
type ConfirmOpts = {
  title: string;
  body?: ReactNode;
  confirmLabel?: string;
  danger?: boolean;
  /** Ask for a reason; the promise resolves with it (or null on cancel). */
  reason?: { label: string; minLength?: number; placeholder?: string };
};
type Pending = ConfirmOpts & { resolve: (v: string | boolean | null) => void };

type Ctx = {
  toast: (text: string, tone?: Tone) => void;
  confirm: (opts: ConfirmOpts) => Promise<boolean>;
  askReason: (opts: ConfirmOpts & { reason: NonNullable<ConfirmOpts["reason"]> }) => Promise<string | null>;
};

const UiContext = createContext<Ctx | null>(null);

export function useUi(): Ctx {
  const ctx = useContext(UiContext);
  if (!ctx) throw new Error("useUi must be used inside <UiProvider>");
  return ctx;
}

export function UiProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [pending, setPending] = useState<Pending | null>(null);
  const seq = useRef(0);

  const toast = useCallback((text: string, tone: Tone = "ok") => {
    const id = ++seq.current;
    setToasts((t) => [...t.slice(-3), { id, tone, text }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === "bad" ? 7000 : 4000);
  }, []);

  const confirm = useCallback(
    (opts: ConfirmOpts) =>
      new Promise<boolean>((resolve) =>
        setPending({ ...opts, reason: undefined, resolve: (v) => resolve(Boolean(v)) }),
      ),
    [],
  );
  const askReason = useCallback(
    (opts: ConfirmOpts & { reason: NonNullable<ConfirmOpts["reason"]> }) =>
      new Promise<string | null>((resolve) =>
        setPending({ ...opts, resolve: (v) => resolve(typeof v === "string" ? v : null) }),
      ),
    [],
  );

  return (
    <UiContext.Provider value={{ toast, confirm, askReason }}>
      {children}
      <div
        aria-live="polite"
        aria-atomic="false"
        className="pointer-events-none fixed inset-x-0 bottom-3 z-[70] flex flex-col items-center gap-2 px-3 sm:bottom-5 sm:right-5 sm:left-auto sm:items-end"
      >
        {toasts.map((t) => (
          <div
            key={t.id}
            role={t.tone === "bad" ? "alert" : "status"}
            className="animate-row-in pointer-events-auto w-full max-w-[380px] rounded-[3px] border-l-4 bg-card px-3.5 py-2.5 text-[13.5px] shadow-lift"
            style={{
              borderLeftColor:
                t.tone === "bad" ? "var(--oxide)" : t.tone === "info" ? "var(--ink)" : "var(--verdant)",
            }}
          >
            {t.text}
          </div>
        ))}
      </div>
      {pending ? <ConfirmDialog pending={pending} close={() => setPending(null)} /> : null}
    </UiContext.Provider>
  );
}

function ConfirmDialog({ pending, close }: { pending: Pending; close: () => void }) {
  const [reason, setReason] = useState("");
  const panel = useRef<HTMLDivElement>(null);
  const min = pending.reason?.minLength ?? 3;
  const tooShort = pending.reason ? reason.trim().length < min : false;

  const finish = useCallback(
    (ok: boolean) => {
      pending.resolve(ok ? (pending.reason ? reason.trim() : true) : pending.reason ? null : false);
      close();
    },
    [pending, reason, close],
  );

  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    panel.current?.querySelector<HTMLElement>("textarea, button")?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") finish(false);
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      prev?.focus();
    };
  }, [finish]);

  return (
    <div className="fixed inset-0 z-[80] grid place-items-center bg-black/45 px-4" role="presentation">
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        className="w-full max-w-[440px] rounded-[3px] border border-rule bg-card p-5 shadow-lift"
      >
        <h2 id="confirm-title" className="display m-0 mb-2 text-[17px]">
          {pending.title}
        </h2>
        {pending.body ? <div className="mb-3 text-[14px] text-ink/85">{pending.body}</div> : null}
        {pending.reason ? (
          <div className="mb-3">
            <label htmlFor="confirm-reason" className="label mb-1 block">
              {pending.reason.label}
            </label>
            <textarea
              id="confirm-reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={pending.reason.placeholder}
              className="min-h-[84px] w-full rounded-[3px] border border-rule bg-card px-3 py-2 text-[14px] text-ink"
            />
            {tooShort && reason ? (
              <p className="mt-1 text-[12.5px] text-oxide">Write at least {min} characters.</p>
            ) : null}
          </div>
        ) : null}
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={() => finish(false)}
            className="display cursor-pointer rounded-[3px] border border-ink bg-transparent px-3.5 py-2 text-[12px] text-ink"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={tooShort}
            onClick={() => finish(true)}
            className="display cursor-pointer rounded-[3px] border px-3.5 py-2 text-[12px] disabled:opacity-50"
            style={{
              background: pending.danger ? "var(--oxide)" : "var(--ink)",
              borderColor: pending.danger ? "var(--oxide)" : "var(--ink)",
              color: "var(--card)",
            }}
          >
            {pending.confirmLabel ?? "Confirm"}
          </button>
        </div>
      </div>
    </div>
  );
}
