"use client";

/**
 * Face enrollment. Consent first — an informed, active choice with a real alternative (the
 * classroom code / QR works without any face data). Then a guided capture of five poses in a
 * random order chosen by the server, which doubles as the liveness check.
 */
import { useCallback, useEffect, useState } from "react";

import Link from "next/link";
import { useRouter } from "next/navigation";

import { api } from "@/lib/client";
import { Page, PageHeader } from "@/components/shell";
import { Banner, Card, CardHeader, Pill } from "@/components/ui";
import { Button, Checkbox, TextArea } from "@/components/forms";
import { PageError, PageLoading } from "@/components/states";
import { GuidedCapture } from "@/components/camera";
import { useUi } from "@/components/toast";

type Status = {
  consent_given: boolean; consent_at: string | null; account_approved: boolean;
  enrollment: "none" | "pending" | "approved" | "rejected"; enrolled_at: string | null;
  rejection_note: string | null; can_enroll: boolean; antispoof_model: boolean;
  reenroll_request: { status: string; reason: string; remark: string | null } | null;
};
type Challenge = { id: number; steps: string[]; instructions: string[] };

export default function FacePage() {
  const router = useRouter();
  const { toast, confirm } = useUi();
  const [s, setS] = useState<Status | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [challenge, setChallenge] = useState<Challenge | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => {
    try {
      setS(await api.get<Status>("/api/me/face"));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load your face status.");
    }
  }, []);
  useEffect(() => {
    load();
  }, [load]);

  async function start() {
    setResult(null);
    try {
      setChallenge(await api.post<Challenge>("/api/me/face/challenge", { purpose: "enroll" }));
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not start.", "bad");
    }
  }

  async function submit(frames: Blob[]) {
    if (!challenge) return;
    setSubmitting(true);
    const fd = new FormData();
    fd.append("challenge_id", String(challenge.id));
    frames.forEach((f, i) => fd.append("images", f, `${i}.jpg`));
    try {
      const r = await api.upload<{ message: string }>("/api/me/face/enroll", fd);
      setResult({ ok: true, text: r.message });
    } catch (e) {
      setResult({ ok: false, text: e instanceof Error ? e.message : "Enrollment failed." });
    } finally {
      setSubmitting(false);
      setChallenge(null);
      load();
    }
  }

  async function withdraw() {
    const ok = await confirm({
      title: "Withdraw consent and delete your face data?",
      body: "Your face template and any review photos are deleted permanently. You can keep marking attendance with the classroom code, and enroll again later if you change your mind.",
      confirmLabel: "Withdraw and delete", danger: true,
    });
    if (!ok) return;
    try {
      await api.post("/api/me/face/consent", { consent: false });
      toast("Consent withdrawn. Your face data has been deleted.");
      load();
      router.refresh();
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not withdraw.", "bad");
    }
  }

  if (error) return <Page><PageHeader title="Face check" /><PageError message={error} retry={load} /></Page>;
  if (!s) return <Page><PageHeader title="Face check" /><PageLoading /></Page>;

  return (
    <Page>
      <PageHeader
        title="Face check"
        subtitle="Optional — lets you mark attendance with a selfie"
        actions={<Pill tone={s.enrollment === "approved" ? "ok" : s.enrollment === "pending" ? "warn" : s.enrollment === "rejected" ? "bad" : "neutral"}>
          {s.enrollment === "none" ? "not enrolled" : s.enrollment}
        </Pill>}
      />

      {!s.account_approved ? (
        <Banner>Your account must be approved by your teacher before you can enroll your face.</Banner>
      ) : null}
      {result ? <Banner bad={!result.ok}>{result.text}</Banner> : null}

      {!s.consent_given ? (
        <ConsentCard onDone={load} />
      ) : challenge ? (
        <Card>
          <CardHeader title="Take your photos" meta={`${challenge.steps.length} poses`} />
          <GuidedCapture steps={challenge.steps} instructions={challenge.instructions} onComplete={submit} busy={submitting} />
          <div className="mt-3 text-center">
            <Button variant="ghost" onClick={() => setChallenge(null)}>Cancel</Button>
          </div>
        </Card>
      ) : (
        <div className="grid gap-4">
          <Card>
            <CardHeader title="Your face enrollment" />
            {s.enrollment === "approved" ? (
              <p className="mt-0 text-[14px]">
                Enrolled{ s.enrolled_at ? ` on ${new Date(s.enrolled_at).toLocaleDateString()}` : ""}. You can use the face
                check on <Link href="/student/mark" className="text-ink underline">Mark attendance</Link>.
              </p>
            ) : s.enrollment === "pending" ? (
              <p className="mt-0 text-[14px]">Your photos are with your teacher for review. You will be notified when it is approved.</p>
            ) : s.enrollment === "rejected" ? (
              <Banner bad>Not approved{ s.rejection_note ? `: ${s.rejection_note}` : "." } You can enroll again.</Banner>
            ) : (
              <p className="mt-0 text-[14px]">You have not enrolled your face yet.</p>
            )}
            {s.can_enroll ? (
              <>
                <ul className="mb-3 mt-2 pl-5 text-[13.5px] text-ink/85">
                  <li>Find good, even light — face a window or a lamp, not a bright background.</li>
                  <li>Remove sunglasses and masks. Regular glasses are fine.</li>
                  <li>You will look straight, then turn and tilt your head slightly as asked (about 20 seconds).</li>
                </ul>
                <Button variant="primary" onClick={start}>{s.enrollment === "approved" ? "Re-enroll my face" : "Start face enrollment"}</Button>
              </>
            ) : null}
            {!s.antispoof_model ? (
              <p className="mb-0 mt-3 text-[12px] text-ash">
                Note: the head-movement check stops printed photos and photos on another phone. This server does
                not run an additional anti-spoofing model.
              </p>
            ) : null}
          </Card>
          {s.enrollment === "approved" ? <ReenrollCard status={s} onDone={load} /> : null}
          <Card>
            <CardHeader title="Your consent" meta={s.consent_at ? `given ${new Date(s.consent_at).toLocaleDateString()}` : undefined} />
            <p className="mt-0 text-[13.5px]">You can withdraw consent at any time. Your face data is then deleted permanently and you
              continue with the classroom code. <Link href="/privacy" className="text-ink underline">Privacy policy</Link></p>
            <Button variant="danger" onClick={withdraw}>Withdraw consent & delete face data</Button>
          </Card>
        </div>
      )}
    </Page>
  );
}

function ConsentCard({ onDone }: { onDone: () => void }) {
  const { toast } = useUi();
  const [agree, setAgree] = useState(false);
  const [busy, setBusy] = useState(false);
  return (
    <Card>
      <CardHeader title="Before you start: your consent" />
      <div className="grid gap-2.5 text-[14px]">
        <p className="m-0"><strong>What is collected.</strong> Five photos of your face, taken now. From them the server computes a
          numeric face template. The photos are kept, encrypted, only until your teacher checks them, then deleted. The template is
          stored encrypted.</p>
        <p className="m-0"><strong>Why.</strong> Only to mark your attendance — when you take a selfie in class, or when a classroom
          camera recognises you during your own lecture. It is never used for anything else, never sold or shared.</p>
        <p className="m-0"><strong>How long.</strong> Until you leave the college, are removed, or withdraw consent — then it is deleted.
          Attendance records themselves are kept as academic records.</p>
        <p className="m-0"><strong>You can say no.</strong> Without face data you mark attendance with the classroom code / QR, or your
          teacher marks you. Nothing else changes.</p>
        <p className="m-0 text-ash">Under India&apos;s Digital Personal Data Protection Act, 2023 you may withdraw consent at any time.
          See the <Link href="/privacy" className="text-ink underline">privacy policy</Link>.</p>
        <Checkbox label="I understand and I agree that my face data is used for attendance as described." checked={agree} onChange={(e) => setAgree(e.target.checked)} />
        <div className="flex flex-wrap gap-2">
          <Button variant="primary" disabled={!agree} busy={busy} onClick={async () => {
            setBusy(true);
            try {
              await api.post("/api/me/face/consent", { consent: true });
              toast("Consent recorded.");
              onDone();
            } catch (e) {
              toast(e instanceof Error ? e.message : "Could not save consent.", "bad");
            } finally {
              setBusy(false);
            }
          }}>I agree — continue</Button>
          <Link href="/student/mark" className="display self-center px-2 text-[13px] text-ink">No thanks, I will use the classroom code</Link>
        </div>
      </div>
    </Card>
  );
}

function ReenrollCard({ status, onDone }: { status: Status; onDone: () => void }) {
  const { toast } = useUi();
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const req = status.reenroll_request;
  const open = req && (req.status === "pending" || req.status === "approved");
  return (
    <Card>
      <CardHeader title="Look different now?" meta="re-enrollment" />
      {open ? (
        <p className="m-0 text-[14px]">Your request is <strong>{req!.status}</strong>
          {req!.status === "approved" ? " — use Re-enroll above." : ". Your teacher will review it."}</p>
      ) : (
        <>
          {req?.status === "rejected" ? <Banner bad>Your last request was not approved{req.remark ? `: ${req.remark}` : "."}</Banner> : null}
          <p className="mt-0 text-[13.5px]">New glasses, a beard, a big change? Ask your teacher to let you re-enroll.</p>
          <TextArea label="What changed?" value={reason} onChange={(e) => setReason(e.target.value)} />
          <Button className="mt-2" busy={busy} onClick={async () => {
            if (reason.trim().length < 5) return toast("Say briefly what changed.", "bad");
            setBusy(true);
            try {
              await api.post("/api/me/face/reenroll-request", { reason: reason.trim() });
              toast("Request sent to your teacher.");
              setReason("");
              onDone();
            } catch (e) {
              toast(e instanceof Error ? e.message : "Could not send.", "bad");
            } finally {
              setBusy(false);
            }
          }}>Request re-enrollment</Button>
        </>
      )}
    </Card>
  );
}
