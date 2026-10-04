"use client";

import { Suspense } from "react";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { Page, PageHeader } from "@/components/shell";
import { ConversationList, NoticeBoard } from "@/components/messages";
import { PageLoading } from "@/components/states";

export default function StudentMessagesPage() {
  return (
    <Suspense fallback={<Page><PageHeader title="Messages" /><PageLoading /></Page>}>
      <Inner />
    </Suspense>
  );
}

function Inner() {
  const router = useRouter();
  const tab = useSearchParams().get("tab") === "notices" ? "notices" : "inbox";
  return (
    <Page>
      <PageHeader title="Messages" subtitle="From your teachers, and the notice board" />
      <nav aria-label="Messages" className="mb-4 flex gap-1">
        {([["inbox", "Inbox"], ["notices", "Notice board"]] as const).map(([k, l]) => (
          <Link key={k} href={`/student/messages${k === "notices" ? "?tab=notices" : ""}`} aria-current={tab === k ? "page" : undefined}
                className="display rounded-[var(--radius)] border px-3 py-1.5 text-[12.5px] no-underline"
                style={tab === k ? { background: "var(--grad-primary)", borderColor: "transparent", color: "var(--on-accent)" } : { borderColor: "var(--rule)", color: "var(--ink)" }}>
            {l}
          </Link>
        ))}
      </nav>
      {tab === "notices" ? <NoticeBoard onRead={() => router.refresh()} /> : <ConversationList base="/student/messages" />}
    </Page>
  );
}
