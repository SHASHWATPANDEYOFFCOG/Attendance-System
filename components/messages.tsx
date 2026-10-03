"use client";

/** Inbox, one conversation, and the notice board — shared by both portals. */
import { useCallback, useEffect, useState } from "react";

import Link from "next/link";

import { api } from "@/lib/client";
import { Card, CardHeader, Pill } from "@/components/ui";
import { EmptyState, PageError, PageLoading } from "@/components/states";
import { AttachmentLink, Composer, Thread } from "@/components/thread";

export type Conv = {
  id: number; with: { id: number; name: string; roll_number: string | null };
  last_message: { body: string; at: string; mine: boolean } | null; unread: number;
};
type ConvDetail = Conv & {
  messages: { id: number; body: string; created_at: string; mine: boolean; sender: string | null; attachment: { url: string; name: string } | null }[];
};
export type Notice = {
  id: number; title: string; body: string; pinned: boolean; created_at: string; expires_at: string | null;
  author: string | null; attachment: { url: string; name: string } | null; read: boolean; mine: boolean;
  audience_type: string;
};

export function ConversationList({ base }: { base: string }) {
  const [rows, setRows] = useState<Conv[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setRows(await api.get<Conv[]>("/api/conversations"));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load messages.");
    }
  }, []);
  useEffect(() => {
    load();
    const t = setInterval(load, 20000);
    return () => clearInterval(t);
  }, [load]);

  if (error) return <PageError message={error} retry={load} />;
  if (!rows) return <PageLoading rows={3} />;
  if (!rows.length) return <EmptyState title="No messages yet">Messages appear here as soon as they are sent.</EmptyState>;
  return (
    <Card>
      <ul className="m-0 list-none p-0">
        {rows.map((c) => (
          <li key={c.id} className="border-b border-rule last:border-0">
            <Link href={`${base}/${c.id}`} className="flex items-start justify-between gap-3 py-2.5 text-ink no-underline hover:bg-tint">
              <div className="min-w-0">
                <div className={`text-[14.5px] ${c.unread ? "font-semibold" : ""}`}>
                  {c.with.name}{c.with.roll_number ? <span className="ml-1 font-mono text-[11.5px] text-ash">{c.with.roll_number}</span> : null}
                </div>
                {c.last_message ? (
                  <div className="truncate text-[13px] text-ash">{c.last_message.mine ? "You: " : ""}{c.last_message.body}</div>
                ) : null}
              </div>
              <div className="shrink-0 text-right">
                {c.last_message ? <div className="font-mono text-[11px] text-ash">{new Date(c.last_message.at).toLocaleDateString()}</div> : null}
                {c.unread ? <Pill tone="bad">{c.unread} new</Pill> : null}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export function ConversationView({ id, back }: { id: number; back: string }) {
  const [d, setD] = useState<ConvDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setD(await api.get<ConvDetail>(`/api/conversations/${id}`));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load the conversation.");
    }
  }, [id]);
  useEffect(() => {
    load();
    const t = setInterval(load, 15000);
    return () => clearInterval(t);
  }, [load]);

  if (error) return <PageError message={error} retry={load} />;
  if (!d) return <PageLoading rows={2} />;
  return (
    <Card>
      <CardHeader title={d.with.name} meta={<Link href={back} className="text-ink">All messages</Link>} />
      <Thread items={d.messages.map((m) => ({ id: m.id, body: m.body, created_at: m.created_at, mine: m.mine, author: m.sender, attachment: m.attachment }))} />
      <Composer endpoint={`/api/conversations/${id}/messages`} onSent={load} />
    </Card>
  );
}

export function NoticeBoard({ onRead, onDelete }: { onRead?: () => void; onDelete?: (n: Notice) => void }) {
  const [rows, setRows] = useState<Notice[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const load = useCallback(async () => {
    try {
      setRows(await api.get<Notice[]>("/api/announcements"));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load notices.");
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    // Opening the board marks what is on it as read.
    const unread = rows?.filter((n) => !n.read && !n.mine) ?? [];
    if (!unread.length) return;
    Promise.all(unread.map((n) => api.post(`/api/announcements/${n.id}/read`).catch(() => {}))).then(() => onRead?.());
  }, [rows, onRead]);

  if (error) return <PageError message={error} retry={load} />;
  if (!rows) return <PageLoading rows={2} />;
  if (!rows.length) return <EmptyState title="No notices" />;
  return (
    <div className="grid gap-3">
      {rows.map((n) => (
        <Card key={n.id}>
          <div className="flex flex-wrap items-start justify-between gap-2">
            <h2 className="m-0 text-[16px] font-semibold">{n.title}</h2>
            <div className="flex items-center gap-1">
              {n.pinned ? <Pill tone="warn">pinned</Pill> : null}
              {!n.read && !n.mine ? <Pill tone="bad">new</Pill> : null}
              {onDelete && n.mine ? (
                <button type="button" onClick={async () => { onDelete(n); }} className="cursor-pointer border-0 bg-transparent px-1 text-[12.5px] text-oxide underline">Remove</button>
              ) : null}
            </div>
          </div>
          <div className="font-mono text-[11.5px] text-ash">
            {n.author} · {new Date(n.created_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}
            {n.expires_at ? ` · until ${new Date(n.expires_at).toLocaleDateString()}` : ""}
          </div>
          <p className="mb-0 mt-2 whitespace-pre-wrap text-[14px]">{n.body}</p>
          <AttachmentLink a={n.attachment} />
        </Card>
      ))}
    </div>
  );
}
