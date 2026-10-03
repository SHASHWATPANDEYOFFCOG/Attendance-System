"use client";

/** CCTV review queue: near matches and late sightings for the teacher to accept or reject. */
import { Suspense, useCallback, useEffect, useState } from "react";

import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { api } from "@/lib/client";
import { Page, PageHeader } from "@/components/shell";
import { Card, Pill } from "@/components/ui";
import { Button } from "@/components/forms";
import { EmptyState, PageError, PageLoading } from "@/components/states";
import { useUi } from "@/components/toast";

type Item = {
  id: number; session_id: number; session_title: string | null; user_id: number; student: string | null;
  roll_number: string | null; photo_url: string | null; camera: string | null; score: number; frames: number;
  seen_at: string; reason: string | null; snapshot: string | null;
};

export default function ReviewPage() {
  return (
    <Suspense fallback={<Page><PageHeader title="Review queue" /><PageLoading /></Page>}>
      <Review />
    </Suspense>
  );
}

function Review() {
  const session = useSearchParams().get("session");
  const { toast } = useUi();
  const [rows, setRows] = useState<Item[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRows(await api.get<Item[]>(`/api/review-queue${session ? `?session_id=${session}` : ""}`));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load the review queue.");
    }
  }, [session]);
  useEffect(() => {
    load();
  }, [load]);

  async function decide(it: Item, accept: boolean) {
    try {
      const r = await api.post<{ marked: string | null }>(`/api/review-queue/${it.id}/${accept ? "accept" : "reject"}`, {});
      toast(accept ? `${it.student} marked ${r.marked}.` : "Rejected — not marked.");
      load();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Action failed.", "bad");
    }
  }

  return (
    <Page wide>
      <PageHeader title="Review queue" subtitle="Camera sightings that need your decision"
                  actions={session ? <Link href={`/staff/sessions/${session}`} className="display rounded-[3px] border border-ink px-3.5 py-2 text-[12px] text-ink no-underline">Back to session</Link> : null} />
      {error ? <PageError message={error} retry={load} /> : !rows ? <PageLoading /> : !rows.length ? (
        <EmptyState title="Nothing to review" />
      ) : (
        <div className="grid gap-3 md:grid-cols-2">
          {rows.map((it) => (
            <Card key={it.id}>
              <div className="flex gap-3">
                <figure className="m-0 text-center">
                  {it.snapshot ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img src={it.snapshot} alt="Camera face crop" className="h-[104px] w-[104px] rounded-[3px] border border-rule object-cover" />
                  ) : <div className="grid h-[104px] w-[104px] place-items-center rounded-[3px] border border-dashed border-rule text-[11px] text-ash">no crop</div>}
                  <figcaption className="label text-[10px]">camera</figcaption>
                </figure>
                {it.photo_url ? (
                  <figure className="m-0 text-center">
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={`/api/backend${it.photo_url}`} alt="Profile photo" className="h-[104px] w-[104px] rounded-[3px] border border-rule object-cover" />
                    <figcaption className="label text-[10px]">profile</figcaption>
                  </figure>
                ) : null}
                <div className="min-w-0">
                  <div className="font-semibold">{it.student} <span className="font-mono text-[12px] text-ash">{it.roll_number}</span></div>
                  <div className="text-[13px] text-ash">{it.session_title} · {it.camera}</div>
                  <div className="text-[13px] text-ash">{new Date(it.seen_at).toLocaleTimeString()} · {it.frames} frames</div>
                  <Pill tone="warn">{Math.round(it.score * 100)}% match</Pill>
                  {it.reason ? <div className="mt-1 text-[12.5px] text-ash">{it.reason}</div> : null}
                </div>
              </div>
              <div className="mt-3 flex gap-2">
                <Button variant="primary" onClick={() => decide(it, true)}>Yes, it is them — mark</Button>
                <Button onClick={() => decide(it, false)}>Not them</Button>
              </div>
            </Card>
          ))}
        </div>
      )}
    </Page>
  );
}
