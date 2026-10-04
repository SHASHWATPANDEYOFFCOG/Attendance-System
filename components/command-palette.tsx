"use client";

/**
 * Command palette (Ctrl/⌘ + K, or the search button in the top bar).
 *
 * Fuzzy search over every page this user can open (the same list as their sidebar, so it never
 * offers a page they may not see) plus a few actions. Arrow keys move, Enter opens, Escape
 * closes; recent picks are remembered in this browser. Focus is trapped in the dialog and
 * returned to where it was on close.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { useRouter } from "next/navigation";

import { ArrowRight, Clock, LogOut, Search, SunMedium } from "lucide-react";

import { NavIcon } from "@/components/nav-icons";
import type { NavGroup } from "@/components/shell-nav";

type Entry = { id: string; label: string; group: string; href?: string; action?: () => void | Promise<void>; icon?: React.ReactNode };

const RECENT_KEY = "att_cmd_recent";

/** Subsequence match with a score that favours word starts and adjacency; returns matched indices. */
function fuzzy(text: string, query: string): { score: number; hits: number[] } | null {
  if (!query) return { score: 0, hits: [] };
  const t = text.toLowerCase();
  const q = query.toLowerCase().replace(/\s+/g, "");
  const hits: number[] = [];
  let score = 0;
  let last = -2;
  let from = 0;
  for (const ch of q) {
    const i = t.indexOf(ch, from);
    if (i === -1) return null;
    hits.push(i);
    score += i === last + 1 ? 5 : 1;
    if (i === 0 || /[\s/·-]/.test(t[i - 1])) score += 4;
    last = i;
    from = i + 1;
  }
  return { score: score - t.length * 0.02, hits };
}

function Highlighted({ text, hits }: { text: string; hits: number[] }) {
  if (!hits.length) return <>{text}</>;
  const set = new Set(hits);
  return (
    <>
      {[...text].map((ch, i) => (set.has(i) ? <mark key={i} className="bg-transparent font-semibold" style={{ color: "var(--accent)" }}>{ch}</mark> : <span key={i}>{ch}</span>))}
    </>
  );
}

function readRecent(): string[] {
  try {
    return JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]");
  } catch {
    return [];
  }
}

export function CommandPalette({ groups, logoutTo }: { groups: NavGroup[]; logoutTo: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const [recent, setRecent] = useState<string[]>([]);
  const inputRef = useRef<HTMLInputElement>(null);
  const returnFocus = useRef<HTMLElement | null>(null);

  const entries = useMemo<Entry[]>(() => {
    const pages: Entry[] = groups.flatMap((g) => g.items.map((i) => ({
      id: i.href, label: i.label, group: g.title ?? "Go to", href: i.href, icon: <NavIcon href={i.href} size={16} />,
    })));
    const actions: Entry[] = [
      {
        id: "action:theme", label: "Switch light / dark theme", group: "Actions",
        icon: <SunMedium size={16} strokeWidth={1.8} aria-hidden />,
        action: () => {
          const root = document.documentElement;
          const dark = root.getAttribute("data-theme") === "dark" ||
            (!root.hasAttribute("data-theme") && window.matchMedia("(prefers-color-scheme: dark)").matches);
          const next = dark ? "light" : "dark";
          root.setAttribute("data-theme", next);
          try { localStorage.setItem("att_theme", next); } catch { /* private mode */ }
        },
      },
      {
        id: "action:logout", label: "Sign out", group: "Actions", icon: <LogOut size={16} strokeWidth={1.8} aria-hidden />,
        action: async () => {
          await fetch("/api/auth/logout", { method: "POST" });
          window.location.href = logoutTo;
        },
      },
    ];
    return [...pages, ...actions];
  }, [groups, logoutTo]);

  const results = useMemo(() => {
    if (!query.trim()) {
      const byId = new Map(entries.map((e) => [e.id, e]));
      const rec = recent.map((id) => byId.get(id)).filter(Boolean).map((e) => ({ entry: { ...e!, group: "Recent" }, hits: [] as number[] }));
      const rest = entries.filter((e) => !recent.includes(e.id)).map((entry) => ({ entry, hits: [] as number[] }));
      return [...rec, ...rest];
    }
    return entries
      .map((entry) => ({ entry, m: fuzzy(entry.label, query) ?? fuzzy(`${entry.group} ${entry.label}`, query) }))
      .filter((r) => r.m)
      .sort((a, b) => b.m!.score - a.m!.score)
      .map((r) => ({ entry: r.entry, hits: fuzzy(r.entry.label, query)?.hits ?? [] }));
  }, [entries, query, recent]);

  const show = useCallback(() => {
    returnFocus.current = document.activeElement as HTMLElement | null;
    setRecent(readRecent());
    setQuery("");
    setCursor(0);
    setOpen(true);
  }, []);
  const hide = useCallback(() => {
    setOpen(false);
    returnFocus.current?.focus?.();
  }, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (open) hide();
        else show();
      }
    };
    const onOpen = () => show();
    window.addEventListener("keydown", onKey);
    window.addEventListener("open-command-palette", onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("open-command-palette", onOpen);
    };
  }, [open, show, hide]);

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 0);
  }, [open]);

  async function run(e: Entry) {
    const next = [e.id, ...readRecent().filter((x) => x !== e.id)].slice(0, 5);
    try { localStorage.setItem(RECENT_KEY, JSON.stringify(next)); } catch { /* private mode */ }
    setOpen(false);
    if (e.href) router.push(e.href);
    else await e.action?.();
  }

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") { e.preventDefault(); hide(); }
    else if (e.key === "ArrowDown") { e.preventDefault(); setCursor((c) => Math.min(c + 1, results.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setCursor((c) => Math.max(c - 1, 0)); }
    else if (e.key === "Enter" && results[cursor]) { e.preventDefault(); run(results[cursor].entry); }
    else if (e.key === "Tab") e.preventDefault();            // keep focus in the dialog
  }

  useEffect(() => {
    document.getElementById(`cmd-${cursor}`)?.scrollIntoView({ block: "nearest" });
  }, [cursor]);

  if (!open || typeof document === "undefined") return null;
  let lastGroup = "";
  return createPortal(
    <div className="fixed inset-0 z-[70] flex items-start justify-center px-3 pt-[12vh]" role="dialog" aria-modal="true" aria-label="Command palette">
      <button type="button" aria-label="Close" className="absolute inset-0 cursor-default border-0 bg-black/45 backdrop-blur-[3px]" onClick={hide} />
      <div className="glass animate-pop-in relative w-full max-w-[600px] overflow-hidden rounded-[var(--radius-xl)] border border-rule shadow-lift" onKeyDown={onKeyDown}>
        <div className="flex items-center gap-2.5 border-b border-rule px-4">
          <Search size={18} strokeWidth={1.8} className="text-ash" aria-hidden />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => { setQuery(e.target.value); setCursor(0); }}
            placeholder="Search pages and actions…"
            aria-label="Search pages and actions"
            role="combobox"
            aria-expanded="true"
            aria-controls="cmd-list"
            aria-activedescendant={results[cursor] ? `cmd-${cursor}` : undefined}
            className="h-14 min-w-0 flex-1 border-0 bg-transparent text-[16px] text-ink outline-none placeholder:text-muted focus-visible:outline-none"
          />
          <kbd className="rounded-md border border-rule px-1.5 py-0.5 font-mono text-[11px] text-ash">Esc</kbd>
        </div>
        <ul id="cmd-list" role="listbox" className="m-0 max-h-[52vh] list-none overflow-y-auto p-2">
          {results.length ? results.map(({ entry, hits }, i) => {
            const header = entry.group !== lastGroup ? entry.group : null;
            lastGroup = entry.group;
            return (
              <li key={`${entry.group}-${entry.id}`} role="presentation">
                {header ? (
                  <div className="label flex items-center gap-1.5 px-3 pb-1 pt-2.5 text-[10.5px] text-muted">
                    {header === "Recent" ? <Clock size={12} aria-hidden /> : null}{header}
                  </div>
                ) : null}
                <div
                  id={`cmd-${i}`}
                  role="option"
                  aria-selected={i === cursor}
                  onMouseEnter={() => setCursor(i)}
                  onClick={() => run(entry)}
                  className="flex cursor-pointer items-center gap-3 rounded-[var(--radius)] px-3 py-2.5 text-[14.5px]"
                  style={i === cursor ? { background: "color-mix(in srgb, var(--accent) 14%, transparent)" } : undefined}
                >
                  <span className={i === cursor ? "text-accent" : "text-ash"}>{entry.icon}</span>
                  <span className="min-w-0 flex-1 truncate"><Highlighted text={entry.label} hits={hits} /></span>
                  {i === cursor ? <ArrowRight size={15} className="text-accent" aria-hidden /> : null}
                </div>
              </li>
            );
          }) : (
            <li className="px-3 py-8 text-center text-[14px] text-ash">Nothing matches “{query}”.</li>
          )}
        </ul>
        <div className="flex items-center justify-between border-t border-rule px-4 py-2 text-[11.5px] text-ash">
          <span><kbd className="font-mono">↑↓</kbd> move · <kbd className="font-mono">Enter</kbd> open</span>
          <span><kbd className="font-mono">Ctrl/⌘ K</kbd> toggle</span>
        </div>
      </div>
    </div>,
    document.body,
  );
}

/** The top-bar search button; also shows the shortcut. */
export function CommandButton() {
  return (
    <button
      type="button"
      onClick={() => window.dispatchEvent(new Event("open-command-palette"))}
      className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-[var(--radius)] border border-rule bg-transparent px-2.5 text-[13px] text-ash transition-colors hover:border-[color-mix(in_srgb,var(--accent)_45%,var(--rule))] hover:text-ink sm:min-w-[220px]"
      aria-label="Search (Ctrl+K)"
    >
      <Search size={16} strokeWidth={1.8} aria-hidden />
      <span className="hidden flex-1 text-left sm:inline">Search…</span>
      <kbd className="hidden rounded-md border border-rule px-1.5 font-mono text-[11px] sm:inline">Ctrl K</kbd>
    </button>
  );
}
