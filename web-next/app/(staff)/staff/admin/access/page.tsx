"use client";

/**
 * Administrator access: an authority who has been given the administrator code becomes an
 * administrator. The code is checked on the server (never shipped to the browser), guesses are
 * rate-limited, and existing administrators are told whenever someone uses it.
 */
import { useState } from "react";

import { useRouter } from "next/navigation";

import { api, ApiFailure } from "@/lib/client";
import { useMe } from "@/lib/use-me";
import { Page, PageHeader } from "@/components/shell";
import { Banner, Card, CardHeader } from "@/components/ui";
import { Button, TextField } from "@/components/forms";
import { useUi } from "@/components/toast";

export default function AdministratorAccessPage() {
  const router = useRouter();
  const { toast } = useUi();
  const { me, isAdministrator } = useMe();
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function unlock(e: React.FormEvent) {
    e.preventDefault();
    if (!code.trim()) return setError("Enter the administrator code.");
    setBusy(true);
    setError(null);
    try {
      const r = await api.post<{ message: string }>("/api/access/administrator", { code: code.trim() });
      toast(r.message);
      router.push("/dashboard");
      router.refresh();
    } catch (err) {
      const detail = err instanceof ApiFailure ? err.detail : undefined;
      setError(typeof detail?.message === "string" ? detail.message : err instanceof Error ? err.message : "Could not verify the code.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Page>
      <PageHeader title="Administrator access" subtitle="Unlock full control of the system with the administrator code" />
      {isAdministrator ? (
        <Banner>You are already an administrator. You can change the access codes under Settings → Access codes.</Banner>
      ) : (
        <Card>
          <CardHeader title="Enter the administrator code" meta={me ? `signed in as ${me.display_name}` : undefined} />
          <p className="mt-0 text-[14px] text-ash">
            Administrators manage cameras, workspaces, authorities, the academic structure, settings and access codes.
            Your college gives the administrator code only to the people who run the system. Using it makes your own
            account an administrator; the other administrators are notified.
          </p>
          <form onSubmit={unlock} noValidate className="grid max-w-[420px] gap-3">
            <TextField label="Administrator code" type="password" autoComplete="off" value={code}
                       onChange={(e) => { setCode(e.target.value); setError(null); }} error={error} />
            <div><Button type="submit" variant="primary" busy={busy}>Become administrator</Button></div>
          </form>
        </Card>
      )}
    </Page>
  );
}
