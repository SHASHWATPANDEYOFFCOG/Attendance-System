"use client";

/** One issue with its thread. Used by both portals; the server decides what each may change. */
import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/client";
import { Page, PageHeader } from "@/components/shell";
import { Card, CardHeader, Pill } from "@/components/ui";
import { Button, SelectField } from "@/components/forms";
import { PageError, PageLoading } from "@/components/states";
import { AttachmentLink, Composer, Thread } from "@/components/thread";
import { useUi } from "@/components/toast";

type Detail = {
  id: number; category_label: string; title: string; description: string; status: string;
  created_at: string; attachment: { url: string; name: string } | null;
  student: { id: number; name: string; roll_number: string | null; section: string | null };
  assigned_to: { id: number; name: string } | null;
  comments: { id: number; body: string; created_at: string; author: { id: number; name: string; staff: boolean } | null; attachment: { url: string; name: string } | null }[];
};

const tone = (s: string) => (s === "resolved" ? "ok" : s === "closed" ? "neutral" : s === "in_progress" ? "warn" : "bad");

export function IssueDetail({ id, staff, meId }: { id: number; staff: boolean; meId: number }) {
  const { toast } = useUi();
  const [d, setD] = useState<Detail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [colleagues, setColleagues] = useState<{ id: number; full_name: string }[]>([]);

  const load = useCallback(async () => {
    try {
      setD(await api.get<Detail>(`/api/issues/${id}`));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load this issue.");
    }
  }, [id]);
  useEffect(() => {
    load();
    if (staff) api.get<{ id: number; full_name: string }[]>("/api/admin/users").then(setColleagues).catch(() => {});
  }, [load, staff]);

  async function setStatus(status: string) {
    try {
      setD(await api.post<Detail>(`/api/issues/${id}/status`, { status }));
      toast(`Marked ${status.replace("_", " ")}.`);
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not change the status.", "bad");
    }
  }

  async function assign(value: string) {
    try {
      setD(await api.post<Detail>(`/api/issues/${id}/assign`, { assigned_to_id: value ? Number(value) : null }));
      toast(value ? "Assigned." : "Unassigned.");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not assign.", "bad");
    }
  }

  if (error) return <Page><PageHeader title="Issue" /><PageError message={error} retry={load} /></Page>;
  if (!d) return <Page><PageHeader title="Issue" /><PageLoading /></Page>;

  const staffActions: [string, string][] = [["in_progress", "Mark in progress"], ["resolved", "Mark resolved"], ["closed", "Close"], ["open", "Reopen"]];
  const studentActions: [string, string][] = d.status === "resolved" ? [["closed", "Close — my issue is solved"], ["open", "Reopen — not solved"]]
    : d.status === "closed" ? [["open", "Reopen"]] : [];

  return (
    <Page>
      <PageHeader
        title={d.title}
        subtitle={`${d.category_label} · ${staff ? `${d.student.name} (${d.student.roll_number ?? ""}) · ${d.student.section ?? ""} · ` : ""}raised ${new Date(d.created_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}`}
        actions={<Pill tone={tone(d.status)}>{d.status.replace("_", " ")}</Pill>}
      />
      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_280px]">
        <Card>
          <p className="mt-0 whitespace-pre-wrap text-[14.5px]">{d.description}</p>
          <AttachmentLink a={d.attachment} />
          <div className="mt-4 border-t border-rule pt-3">
            <Thread items={d.comments.map((c) => ({
              id: c.id, body: c.body, created_at: c.created_at, mine: c.author?.id === meId,
              author: c.author?.name ?? null, staff: c.author?.staff, attachment: c.attachment,
            }))} />
          </div>
          <Composer endpoint={`/api/issues/${id}/comments`} onSent={load}
                    disabled={d.status === "closed" && !staff ? "This issue is closed. Reopen it to reply." : null} />
        </Card>
        <div className="grid content-start gap-4">
          <Card>
            <CardHeader title="Status" />
            <div className="grid gap-2">
              {(staff ? staffActions.filter(([s]) => s !== d.status) : studentActions).map(([s, label]) => (
                <Button key={s} onClick={() => setStatus(s)}>{label}</Button>
              ))}
              {!staff && !studentActions.length ? <p className="m-0 text-[13px] text-ash">Your teacher will update the status as they work on it.</p> : null}
            </div>
          </Card>
          {staff ? (
            <Card>
              <CardHeader title="Assigned to" />
              <SelectField label="Staff member" value={String(d.assigned_to?.id ?? "")} onChange={(e) => assign(e.target.value)}>
                <option value="">Unassigned</option>
                {colleagues.map((c) => <option key={c.id} value={c.id}>{c.full_name}</option>)}
              </SelectField>
            </Card>
          ) : d.assigned_to ? (
            <Card><CardHeader title="Handled by" /><p className="m-0">{d.assigned_to.name}</p></Card>
          ) : null}
        </div>
      </div>
    </Page>
  );
}
