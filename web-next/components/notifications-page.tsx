"use client";

import { useCallback, useEffect, useState } from "react";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { api } from "@/lib/client";
import { Page, PageHeader } from "@/components/shell";
import { Card } from "@/components/ui";
import { Button, Checkbox } from "@/components/forms";
import { EmptyState, PageError, PageLoading } from "@/components/states";

type Note = { id: number; type: string; title: string; body: string | null; link: string | null; created_at: string; read: boolean };

export function NotificationsScreen() {
  const router = useRouter();
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [page, setPage] = useState(1);
  const [data, setData] = useState<{ rows: Note[]; meta: { pages: number; total: number } } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(await api.get(`/api/notifications?page=${page}&page_size=30${unreadOnly ? "&unread_only=true" : ""}`));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load notifications.");
    }
  }, [page, unreadOnly]);
  useEffect(() => {
    load();
  }, [load]);

  return (
    <Page>
      <PageHeader
        title="Notifications"
        subtitle={data ? `${data.meta.total} total` : ""}
        actions={<Button onClick={async () => { await api.post("/api/notifications/read", {}); load(); router.refresh(); }}>Mark all read</Button>}
      />
      <Card className="mb-3">
        <Checkbox label="Show unread only" checked={unreadOnly} onChange={(e) => { setUnreadOnly(e.target.checked); setPage(1); }} />
      </Card>
      {error ? <PageError message={error} retry={load} /> : !data ? <PageLoading /> : !data.rows.length ? (
        <EmptyState title={unreadOnly ? "No unread notifications" : "No notifications yet"} />
      ) : (
        <Card>
          <ul className="m-0 list-none p-0">
            {data.rows.map((n) => (
              <li key={n.id} className="flex items-start gap-3 border-b border-rule py-2.5 last:border-0">
                <span className="mt-1.5 h-2 w-2 shrink-0 rounded-full" style={{ background: n.read ? "var(--rule)" : "var(--oxide)" }} aria-label={n.read ? "read" : "unread"} />
                <div className="min-w-0 flex-1">
                  <div className={`text-[14px] ${n.read ? "" : "font-semibold"}`}>
                    {n.link ? <Link href={n.link} className="text-ink" onClick={() => api.post("/api/notifications/read", { ids: [n.id] }).catch(() => {})}>{n.title}</Link> : n.title}
                  </div>
                  {n.body ? <p className="m-0 text-[13px] text-ash">{n.body}</p> : null}
                  <span className="font-mono text-[11px] text-ash">{new Date(n.created_at).toLocaleString()}</span>
                </div>
              </li>
            ))}
          </ul>
          {data.meta.pages > 1 ? (
            <nav className="mt-3 flex items-center justify-between" aria-label="Pages">
              <Button disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Newer</Button>
              <span className="font-mono text-[12px] text-ash">page {page} of {data.meta.pages}</span>
              <Button disabled={page >= data.meta.pages} onClick={() => setPage((p) => p + 1)}>Older</Button>
            </nav>
          ) : null}
        </Card>
      )}
    </Page>
  );
}
