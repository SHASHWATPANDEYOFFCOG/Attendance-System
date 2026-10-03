/**
 * The register for one period.
 *
 * Opening a session is a POST (it creates the session and syncs the roster), so it happens
 * here on the server with the httpOnly token attached. It is idempotent, so a refresh or a
 * second tab reopens the same register rather than creating a duplicate.
 *
 * Next 16: route `params` is a Promise.
 */
import Link from "next/link";

import { apiSend } from "@/lib/api";
import { Card } from "@/components/ui";
import { Register } from "@/components/register";

export const dynamic = "force-dynamic";

export default async function MarkSession({
  params,
  searchParams,
}: {
  params: Promise<{ slotId: string }>;
  searchParams: Promise<{ date?: string }>;
}) {
  const { slotId } = await params;
  const { date } = await searchParams;

  let payload: Awaited<ReturnType<typeof apiSend>> | null = null;
  let error: string | null = null;
  try {
    payload = await apiSend("/api/attendance/sessions", "POST", {
      slot_id: Number(slotId),
      date: date ?? null,
    });
  } catch (e) {
    error = e instanceof Error ? e.message : "Could not open this period.";
  }

  const data = payload as {
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
    roster: {
      user_id: number;
      display_name: string;
      roll_number: string | null;
      status: string | null;
      source: string | null;
      overridden: boolean;
      needs_review: boolean;
    }[];
  } | null;

  return (
    <main className="relative z-[1] mx-auto max-w-[900px] px-4 pb-16 pt-6 md:px-5">
      <header className="mb-5 flex flex-wrap items-end justify-between gap-4 border-b-2 border-ink pb-3">
        <div>
          <h1 className="display m-0 text-[26px]">
            {data?.session.subject_code ?? "Register"}
          </h1>
          <p className="mt-0.5 font-mono text-xs text-ash">
            {data
              ? `${data.session.subject_name ?? ""} · section ${data.session.section_label ?? "—"} · ${data.session.room} · ${data.roster.length} students`
              : ""}
          </p>
        </div>
        <Link
          href="/mark"
          className="display rounded-[3px] border border-ink px-3.5 py-2 text-[12px] text-ink hover:bg-tint"
        >
          All periods
        </Link>
      </header>

      <Card>
        {error ? (
          <div
            role="alert"
            className="rounded-r-[2px] border-l-4 px-3.5 py-2.5 text-[13.5px]"
            style={{
              borderLeftColor: "var(--oxide)",
              background: "color-mix(in srgb, var(--oxide) 11%, transparent)",
            }}
          >
            <strong className="label mb-0.5 block">Cannot open this period</strong>
            {error}
          </div>
        ) : data ? (
          <Register initial={data} />
        ) : null}
      </Card>
    </main>
  );
}
