"use client";

/**
 * The bell in the top bar. Opens a personal server-sent-event stream, so a leave approval or a
 * teacher's message appears within a second, as a toast and as a badge. The stream is a
 * convenience: the list is always re-fetched from the server when opened, so a dropped
 * connection can delay a notification but never lose one.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { api } from "@/lib/client";
import { useUi } from "@/components/toast";

type Note = { id: number; type: string; title: string; body: string | null; link: string | null; created_at: string; read: boolean };

export function NotificationBell({ initial, allHref }: { initial: number; allHref: string }) {
  const router = useRouter();
  const { toast } = useUi();
  const [count, setCount] = useState(initial);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<Note[] | null>(null);
  const box = useRef<HTMLDivElement>(null);

  const loadList = useCallback(async () => {
    try {
      const r = await api.get<{ rows: Note[] }>("/api/notifications?page_size=8");
      setItems(r.rows);
    } catch {
      setItems([]);
    }
  }, []);

  useEffect(() => setCount(initial), [initial]);

  useEffect(() => {
    let es: EventSource | null = null;
    let retry: ReturnType<typeof setTimeout> | null = null;
    let delay = 3000;
    const connect = () => {
      es = new EventSource("/api/backend/api/notifications/stream");
      es.addEventListener("hello", () => (delay = 3000));
      es.addEventListener("notification", (ev) => {
        try {
          const d = JSON.parse((ev as MessageEvent).data);
          setCount((c) => c + 1);
          toast(d.title ?? "New notification", "info");
          // Refresh server-rendered badges (approvals, leaves, messages) in the nav.
          router.refresh();
        } catch {
          /* ignore malformed */
        }
      });
      es.onerror = () => {
        es?.close();
        retry = setTimeout(connect, delay);
        delay = Math.min(delay * 2, 60000);
      };
    };
    connect();
    return () => {
      es?.close();
      if (retry) clearTimeout(retry);
    };
  }, [toast, router]);

  useEffect(() => {
    if (!open) return;
    loadList();
    const onDoc = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, loadList]);

  async function markAll() {
    try {
      await api.post("/api/notifications/read", {});
      setCount(0);
      setItems((xs) => xs?.map((x) => ({ ...x, read: true })) ?? null);
      router.refresh();
    } catch {
      toast("Could not mark notifications as read.", "bad");
    }
  }

  async function openOne(n: Note) {
    setOpen(false);
    if (!n.read) {
      api.post("/api/notifications/read", { ids: [n.id] }).catch(() => {});
      setCount((c) => Math.max(0, c - 1));
    }
    if (n.link) router.push(n.link);
  }

  return (
    <div ref={box} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-label={count ? `Notifications, ${count} unread` : "Notifications"}
        aria-expanded={open}
        aria-haspopup="true"
        className="relative inline-flex h-[34px] w-[34px] cursor-pointer items-center justify-center rounded-[3px] border border-rule bg-transparent text-ash hover:border-ash hover:text-ink"
      >
        <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9" />
          <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
        </svg>
        {count > 0 ? (
          <span
            className="absolute -right-1.5 -top-1.5 min-w-[18px] rounded-full px-1 font-mono text-[10.5px] font-semibold leading-[18px]"
            style={{ background: "var(--oxide)", color: "var(--card)" }}
            aria-hidden="true"
          >
            {count > 99 ? "99+" : count}
          </span>
        ) : null}
      </button>
      {open ? (
        <div
          role="dialog"
          aria-label="Notifications"
          className="absolute right-0 top-[40px] z-50 w-[min(360px,calc(100vw-24px))] rounded-[3px] border border-rule bg-card shadow-lift"
        >
          <div className="flex items-center justify-between border-b border-rule px-3 py-2">
            <span className="display text-[13px]">Notifications</span>
            {count > 0 ? (
              <button type="button" onClick={markAll} className="cursor-pointer border-0 bg-transparent text-[12.5px] text-ink underline">
                Mark all read
              </button>
            ) : null}
          </div>
          <ul className="m-0 max-h-[60vh] list-none overflow-y-auto p-0">
            {items === null ? (
              <li className="px-3 py-4 text-[13px] text-ash">Loading…</li>
            ) : items.length === 0 ? (
              <li className="px-3 py-4 text-[13px] text-ash">You are all caught up.</li>
            ) : (
              items.map((n) => (
                <li key={n.id}>
                  <button
                    type="button"
                    onClick={() => openOne(n)}
                    className="block w-full cursor-pointer border-0 border-b border-rule bg-transparent px-3 py-2.5 text-left hover:bg-tint"
                  >
                    <span className="flex items-start gap-2">
                      <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full" style={{ background: n.read ? "transparent" : "var(--oxide)" }} aria-hidden />
                      <span className="min-w-0">
                        <span className={`block text-[13.5px] text-ink ${n.read ? "" : "font-semibold"}`}>{n.title}</span>
                        {n.body ? <span className="line-clamp-2 block text-[12.5px] text-ash">{n.body}</span> : null}
                        <span className="block font-mono text-[10.5px] text-ash">{new Date(n.created_at).toLocaleString()}</span>
                      </span>
                    </span>
                  </button>
                </li>
              ))
            )}
          </ul>
          <Link href={allHref} onClick={() => setOpen(false)} className="block px-3 py-2 text-center text-[12.5px] text-ink">
            See all notifications
          </Link>
        </div>
      ) : null}
    </div>
  );
}
