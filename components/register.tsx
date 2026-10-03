"use client";

/**
 * The marking register — the screen used every working day.
 *
 * Design decisions that matter more than the pixels:
 *
 *  - **One tap per student.** The row itself is the control; there is no "edit" mode.
 *  - **Mark all present, then flip the absentees.** In a normal class most people are there,
 *    so the default bulk action is the one that leaves the least work.
 *  - **Keyboard first.** j/k or arrows move, p/a/l/d/e mark and advance, Ctrl+S saves. A
 *    teacher with 60 students should never need the mouse.
 *  - **Nothing is lost if the network drops.** Every change is written to localStorage
 *    immediately; a failed save keeps the draft, shows it plainly, and retries. The draft is
 *    cleared only after the server confirms.
 *  - **Optimistic, but honest.** The UI updates instantly and says "unsaved" until the server
 *    agrees. It never shows "saved" on hope.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { Mark, Pill } from "@/components/ui";

type Row = {
  user_id: number;
  display_name: string;
  roll_number: string | null;
  status: string | null;
  source: string | null;
  overridden: boolean;
  needs_review: boolean;
};

type RosterPayload = {
  session: {
    id: number;
    room: string;
    is_locked: boolean;
    marked_at: string | null;
    subject_code: string | null;
    subject_name: string | null;
    section_label: string | null;
  };
  marked_count: number;
  roster: Row[];
};

const CYCLE = ["present", "absent", "late"] as const;
const KEYS: Record<string, string> = {
  p: "present",
  a: "absent",
  l: "late",
  d: "on_duty",
  e: "excused",
};

const draftKey = (sessionId: number) => `att_draft_${sessionId}`;

export function Register({ initial }: { initial: RosterPayload }) {
  const sessionId = initial.session.id;
  const [marks, setMarks] = useState<Record<number, string>>(() => {
    const base: Record<number, string> = {};
    for (const r of initial.roster) if (r.status) base[r.user_id] = r.status;
    return base;
  });
  const [saved, setSaved] = useState<Record<number, string>>(() => {
    const base: Record<number, string> = {};
    for (const r of initial.roster) if (r.status) base[r.user_id] = r.status;
    return base;
  });
  const [cursor, setCursor] = useState(0);
  const [state, setState] = useState<"idle" | "saving" | "error">("idle");
  const [message, setMessage] = useState<string | null>(null);
  const [restored, setRestored] = useState(false);
  const rowRefs = useRef<(HTMLTableRowElement | null)[]>([]);

  const rows = initial.roster;
  const locked = initial.session.is_locked;

  /* ---------------------------------------------------------- draft recovery */
  // Runs before anything can overwrite it: if the last session ended with an unsaved draft
  // (tab closed, laptop shut, network down), the teacher gets their work back.
  useEffect(() => {
    try {
      const raw = localStorage.getItem(draftKey(sessionId));
      if (!raw) return;
      const draft = JSON.parse(raw) as Record<number, string>;
      if (draft && Object.keys(draft).length) {
        setMarks((m) => ({ ...m, ...draft }));
        setRestored(true);
      }
    } catch {
      /* a corrupt draft must not break the screen */
    }
  }, [sessionId]);

  const dirty = useMemo(
    () => Object.entries(marks).filter(([id, s]) => saved[Number(id)] !== s),
    [marks, saved],
  );

  /* Persist every keystroke. Cheap, synchronous, and the whole point. */
  useEffect(() => {
    if (!dirty.length) {
      localStorage.removeItem(draftKey(sessionId));
      return;
    }
    try {
      localStorage.setItem(draftKey(sessionId), JSON.stringify(Object.fromEntries(dirty)));
    } catch {
      /* quota or private mode — the in-memory state still works */
    }
  }, [dirty, sessionId]);

  /* Warn before losing unsaved work. */
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (dirty.length) e.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty.length]);

  /* ------------------------------------------------------------------ actions */

  const setMark = useCallback(
    (userId: number, status: string) => {
      if (locked) return;
      setMarks((m) => ({ ...m, [userId]: status }));
    },
    [locked],
  );

  const cycle = useCallback(
    (userId: number) => {
      if (locked) return;
      setMarks((m) => {
        const now = m[userId];
        const i = CYCLE.indexOf(now as (typeof CYCLE)[number]);
        return { ...m, [userId]: CYCLE[(i + 1) % CYCLE.length] };
      });
    },
    [locked],
  );

  const markAllPresent = useCallback(() => {
    if (locked) return;
    setMarks(Object.fromEntries(rows.map((r) => [r.user_id, "present"])));
  }, [rows, locked]);

  const save = useCallback(async () => {
    if (locked || !rows.length) return;
    setState("saving");
    setMessage(null);
    // The FULL register is sent, not a delta: a dropped connection can then never leave half
    // the class marked and the other half silently absent.
    const payload = rows
      .filter((r) => marks[r.user_id])
      .map((r) => ({ user_id: r.user_id, status: marks[r.user_id] }));

    if (!payload.length) {
      setState("idle");
      setMessage("Nothing to save yet.");
      return;
    }

    try {
      const res = await fetch(`/api/backend/api/attendance/sessions/${sessionId}/records`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ marks: payload }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        const detail = body?.detail?.message ?? body?.detail ?? body?.error;
        setState("error");
        setMessage(
          typeof detail === "string" ? detail : `Save failed (${res.status}). Your marks are kept.`,
        );
        return;
      }
      const body = await res.json();
      // Only now is it safe to consider the work committed.
      setSaved({ ...marks });
      setRestored(false);
      localStorage.removeItem(draftKey(sessionId));
      setState("idle");
      setMessage(
        `Saved — ${body.created} new, ${body.updated} changed, ${body.unchanged} unchanged.`,
      );
    } catch {
      setState("error");
      setMessage("No connection. Your marks are saved on this device and will not be lost.");
    }
  }, [locked, marks, rows, sessionId]);

  /* ---------------------------------------------------------------- keyboard */

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA") return;

      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        void save();
        return;
      }
      if (locked) return;

      const key = e.key.toLowerCase();
      if (key === "j" || e.key === "ArrowDown") {
        e.preventDefault();
        setCursor((c) => Math.min(rows.length - 1, c + 1));
      } else if (key === "k" || e.key === "ArrowUp") {
        e.preventDefault();
        setCursor((c) => Math.max(0, c - 1));
      } else if (KEYS[key]) {
        e.preventDefault();
        const row = rows[cursor];
        if (row) {
          setMark(row.user_id, KEYS[key]);
          setCursor((c) => Math.min(rows.length - 1, c + 1)); // mark-and-advance
        }
      } else if (e.key === " ") {
        e.preventDefault();
        const row = rows[cursor];
        if (row) cycle(row.user_id);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [cursor, rows, save, setMark, cycle, locked]);

  useEffect(() => {
    rowRefs.current[cursor]?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  /* ------------------------------------------------------------------ render */

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const r of rows) {
      const s = marks[r.user_id];
      if (s) c[s] = (c[s] ?? 0) + 1;
    }
    return c;
  }, [marks, rows]);

  const unmarked = rows.length - Object.values(counts).reduce((a, b) => a + b, 0);

  return (
    <div>
      {restored ? (
        <div
          role="status"
          className="mb-3 rounded-r-[2px] border-l-4 px-3.5 py-2.5 text-[13.5px]"
          style={{
            borderLeftColor: "var(--amber)",
            background: "color-mix(in srgb, var(--amber) 10%, transparent)",
          }}
        >
          Unsaved marks from an earlier attempt were restored from this device.
        </div>
      ) : null}

      {locked ? (
        <div
          role="status"
          className="mb-3 rounded-r-[2px] border-l-4 px-3.5 py-2.5 text-[13.5px]"
          style={{
            borderLeftColor: "var(--oxide)",
            background: "color-mix(in srgb, var(--oxide) 11%, transparent)",
          }}
        >
          This register is locked. Changes now need a correction request, so the original marks
          stay in the audit log.
        </div>
      ) : null}

      {/* ------------------------------------------------------------ toolbar */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={markAllPresent}
          disabled={locked}
          className="display cursor-pointer rounded-[3px] border px-3.5 py-2 text-[12px] disabled:opacity-50"
          style={{ background: "var(--ink)", borderColor: "var(--ink)", color: "var(--card)" }}
        >
          Mark all present
        </button>
        <button
          type="button"
          onClick={() => void save()}
          disabled={locked || state === "saving" || !dirty.length}
          className="display cursor-pointer rounded-[3px] border border-ink px-3.5 py-2 text-[12px] text-ink hover:bg-tint disabled:opacity-50"
        >
          {state === "saving" ? "Saving..." : dirty.length ? `Save ${dirty.length} change(s)` : "Saved"}
        </button>

        <span className="ml-auto flex flex-wrap items-center gap-2 font-mono text-[12px] tnum text-ash">
          <span style={{ color: "var(--status-present)" }}>P {counts.present ?? 0}</span>
          <span style={{ color: "var(--status-absent)" }}>A {counts.absent ?? 0}</span>
          <span style={{ color: "var(--status-late)" }}>L {counts.late ?? 0}</span>
          {unmarked > 0 ? <Pill tone="warn">{unmarked} unmarked</Pill> : null}
          {dirty.length ? <Pill tone="warn">unsaved</Pill> : null}
        </span>
      </div>

      {message ? (
        <p
          role="status"
          className="mb-3 text-[13px]"
          style={{ color: state === "error" ? "var(--oxide)" : "var(--ash)" }}
        >
          {message}
        </p>
      ) : null}

      {/* ------------------------------------------------------------- roster */}
      <div className="overflow-x-auto">
        <table className="w-full border-collapse text-[14px]">
          <caption className="sr-only">
            Attendance register. Use j and k to move, p a l d e to mark, Ctrl+S to save.
          </caption>
          <thead>
            <tr>
              <th className="label border-b-2 border-ink px-2 pb-1.5 text-left">Roll</th>
              <th className="label border-b-2 border-ink px-2 pb-1.5 text-left">Name</th>
              <th className="label border-b-2 border-ink px-2 pb-1.5 text-left">Mark</th>
              <th className="label border-b-2 border-ink px-2 pb-1.5 text-right">Set</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => {
              const status = marks[r.user_id];
              const isDirty = saved[r.user_id] !== status;
              return (
                <tr
                  key={r.user_id}
                  ref={(el) => {
                    rowRefs.current[i] = el;
                  }}
                  onClick={() => {
                    setCursor(i);
                    cycle(r.user_id);
                  }}
                  aria-current={i === cursor ? "true" : undefined}
                  className="cursor-pointer"
                  style={{
                    background: i === cursor ? "var(--tint-hard)" : undefined,
                    boxShadow: isDirty ? "inset 3px 0 0 var(--amber)" : undefined,
                  }}
                >
                  <td className="h-[34px] border-b border-rule px-2 font-mono text-[13px] tnum">
                    {r.roll_number}
                  </td>
                  <td className="border-b border-rule px-2">
                    {r.display_name}
                    {r.overridden ? <span className="ml-2 text-[11px] text-ash">overridden</span> : null}
                  </td>
                  <td className="border-b border-rule px-2">
                    {status ? <Mark status={status} /> : <span className="text-ash">—</span>}
                  </td>
                  <td className="border-b border-rule px-2 text-right whitespace-nowrap">
                    {(["present", "absent", "late"] as const).map((s) => (
                      <button
                        key={s}
                        type="button"
                        aria-label={`Mark ${r.display_name} ${s}`}
                        aria-pressed={status === s}
                        disabled={locked}
                        onClick={(e) => {
                          e.stopPropagation();
                          setCursor(i);
                          setMark(r.user_id, s);
                        }}
                        className="display ml-1 cursor-pointer rounded-[3px] border px-2 py-1 text-[11px] disabled:opacity-40"
                        style={
                          status === s
                            ? {
                                background: `var(--status-${s})`,
                                borderColor: `var(--status-${s})`,
                                color: "var(--card)",
                              }
                            : { borderColor: "var(--rule)", color: "var(--ash)" }
                        }
                      >
                        {s[0].toUpperCase()}
                      </button>
                    ))}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <p className="mt-3 text-[12.5px] text-ash">
        <strong className="label">Keyboard</strong> j / k move · p a l d e mark and advance ·
        space cycles · Ctrl+S saves
      </p>
    </div>
  );
}
