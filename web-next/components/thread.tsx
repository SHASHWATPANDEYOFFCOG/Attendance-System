"use client";

/** A message thread with a composer — shared by direct messages and issue comments. */
import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/client";
import { Button } from "@/components/forms";

export type ThreadItem = {
  id: number;
  body: string;
  created_at: string;
  mine: boolean;
  author: string | null;
  staff?: boolean;
  attachment: { url: string; name: string } | null;
};

export function AttachmentLink({ a }: { a: { url: string; name: string } | null }) {
  if (!a) return null;
  return (
    <a href={`/api/backend${a.url}`} target="_blank" rel="noopener" className="mt-1 inline-flex items-center gap-1 text-[12.5px] text-ink underline">
      <svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
        <path d="m21.4 11.1-9.2 9.2a6 6 0 0 1-8.5-8.5l9.2-9.2a4 4 0 0 1 5.7 5.7l-9.2 9.2a2 2 0 0 1-2.8-2.8l8.5-8.5" />
      </svg>
      {a.name}
    </a>
  );
}

export function Thread({ items }: { items: ThreadItem[] }) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => end.current?.scrollIntoView({ block: "end" }), [items.length]);
  if (!items.length) return <p className="m-0 py-4 text-center text-[13.5px] text-ash">No messages yet.</p>;
  return (
    <ol className="m-0 grid list-none gap-2.5 p-0" aria-label="Conversation">
      {items.map((m) => (
        <li key={m.id} className={`flex ${m.mine ? "justify-end" : "justify-start"}`}>
          <div
            className="max-w-[85%] rounded-[var(--radius)] border px-3 py-2"
            style={m.mine
              ? { background: "color-mix(in srgb, var(--ink) 8%, var(--card))", borderColor: "var(--rule)" }
              : { background: "var(--card)", borderColor: "var(--rule)" }}
          >
            <div className="mb-0.5 flex items-baseline gap-2 text-[11.5px] text-ash">
              <span className="font-semibold text-ink">{m.mine ? "You" : m.author}</span>
              {m.staff ? <span className="label text-[10px]">staff</span> : null}
              <span className="font-mono">{new Date(m.created_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}</span>
            </div>
            <p className="m-0 whitespace-pre-wrap break-words text-[14px]">{m.body}</p>
            <AttachmentLink a={m.attachment} />
          </div>
        </li>
      ))}
      <div ref={end} />
    </ol>
  );
}

export function Composer({
  endpoint,
  onSent,
  disabled,
  placeholder = "Write a reply…",
}: {
  endpoint: string;
  onSent: () => void;
  disabled?: string | null;
  placeholder?: string;
}) {
  const [body, setBody] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (disabled) return <p className="m-0 mt-3 text-[13.5px] text-ash">{disabled}</p>;

  async function send(e: React.FormEvent) {
    e.preventDefault();
    if (!body.trim()) return setError("Write something first.");
    if (file && file.size > 5 * 1024 * 1024) return setError("Attachments must be under 5 MB.");
    setBusy(true);
    setError(null);
    const fd = new FormData();
    fd.append("body", body.trim());
    if (file) fd.append("attachment", file);
    try {
      await api.upload(endpoint, fd);
      setBody("");
      setFile(null);
      onSent();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={send} className="mt-3 grid gap-2 border-t border-rule pt-3" noValidate>
      <label htmlFor="composer" className="sr-only">Message</label>
      <textarea
        id="composer"
        value={body}
        onChange={(e) => setBody(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) send(e as unknown as React.FormEvent);
        }}
        placeholder={placeholder}
        className="min-h-[80px] w-full rounded-[var(--radius)] border border-rule bg-card px-3 py-2 text-[14px] text-ink transition-[border-color,box-shadow] duration-200 hover:border-[color-mix(in_srgb,var(--accent)_40%,var(--rule))] focus:border-accent focus:shadow-[0_0_0_4px_color-mix(in_srgb,var(--accent)_18%,transparent)]"
      />
      {error ? <p role="alert" className="m-0 text-[12.5px] text-oxide">{error}</p> : null}
      <div className="flex flex-wrap items-center justify-between gap-2">
        <label className="cursor-pointer text-[12.5px] text-ink underline">
          {file ? `Attached: ${file.name}` : "Attach PDF / JPG / PNG"}
          <input type="file" accept="application/pdf,image/jpeg,image/png" className="sr-only" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <Button type="submit" variant="primary" busy={busy}>Send</Button>
      </div>
    </form>
  );
}
