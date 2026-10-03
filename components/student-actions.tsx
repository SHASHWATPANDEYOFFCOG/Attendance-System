"use client";

/** Approve / reject / remove buttons on a student's page. Each asks first; reject and remove
 *  require a reason, which the server records in the audit log. */
import { useRouter } from "next/navigation";

import { api } from "@/lib/client";
import { Button } from "@/components/forms";
import { useUi } from "@/components/toast";

export function StudentActions({
  studentId,
  name,
  status,
  emailVerified,
  canRemove,
}: {
  studentId: number;
  name: string;
  status: string;
  emailVerified: boolean;
  canRemove: boolean;
}) {
  const router = useRouter();
  const { toast, confirm, askReason } = useUi();

  async function approve() {
    if (!(await confirm({ title: `Approve ${name}?`, body: "They will get full access, including marking attendance.", confirmLabel: "Approve" }))) return;
    try {
      await api.post(`/api/students/${studentId}/approve`);
      toast(`${name} approved.`);
      router.refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not approve.", "bad");
    }
  }

  async function reject() {
    const reason = await askReason({
      title: `Reject ${name}?`,
      body: "The student sees this reason and can correct their details and resubmit.",
      confirmLabel: "Reject",
      danger: true,
      reason: { label: "Reason", placeholder: "e.g. Roll number does not match college records", minLength: 3 },
    });
    if (!reason) return;
    try {
      await api.post(`/api/students/${studentId}/reject`, { reason });
      toast(`${name} rejected.`);
      router.refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not reject.", "bad");
    }
  }

  async function remove() {
    const reason = await askReason({
      title: `Remove ${name}?`,
      body: "Closes the account and permanently deletes their face data. Their attendance history is kept as an academic record.",
      confirmLabel: "Remove student",
      danger: true,
      reason: { label: "Reason", placeholder: "e.g. Graduated / transferred / withdrew", minLength: 3 },
    });
    if (!reason) return;
    try {
      await api.del(`/api/students/${studentId}?reason=${encodeURIComponent(reason)}`);
      toast(`${name} removed.`);
      router.push("/staff/students");
      router.refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not remove.", "bad");
    }
  }

  return (
    <div className="flex flex-wrap gap-2">
      <Button onClick={() => router.push(`/staff/messages?student=${studentId}`)}>Message</Button>
      {status !== "approved" ? (
        <Button variant="primary" onClick={approve} disabled={!emailVerified} title={emailVerified ? undefined : "Waiting for the student to verify their email"}>
          Approve
        </Button>
      ) : null}
      {status !== "rejected" ? <Button onClick={reject}>{status === "approved" ? "Revoke approval" : "Reject"}</Button> : null}
      {canRemove ? <Button variant="danger" onClick={remove}>Remove</Button> : null}
    </div>
  );
}
