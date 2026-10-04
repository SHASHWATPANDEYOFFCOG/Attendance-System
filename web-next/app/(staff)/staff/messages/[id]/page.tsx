"use client";

import { use } from "react";

import { Page, PageHeader } from "@/components/shell";
import { ConversationView } from "@/components/messages";

export default function StaffConversationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return (
    <Page>
      <PageHeader title="Conversation" />
      <ConversationView id={Number(id)} back="/staff/messages" />
    </Page>
  );
}
