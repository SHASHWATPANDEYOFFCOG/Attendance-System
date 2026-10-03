"use client";

/**
 * Landing page for the classroom QR. The phone's camera app opens
 * /student/scan?s=<session>&c=<code>; this page (already signed in) takes one location fix and
 * submits. The QR alone proves nothing — the server still checks the code is current, the
 * student is in this class, the time window, and the geofence.
 */
import { Suspense, useEffect, useRef, useState } from "react";

import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { api, ApiFailure } from "@/lib/client";
import { Page, PageHeader } from "@/components/shell";
import { Banner, Card } from "@/components/ui";
import { Button } from "@/components/forms";
import { Spinner } from "@/components/forms";
import { getLocation, LocationHelp, type GeoFailure } from "@/components/geo-help";

export default function ScanPage() {
  return (
    <Suspense fallback={<Page><PageHeader title="Classroom QR" /></Page>}>
      <Scan />
    </Suspense>
  );
}

function Scan() {
  const sp = useSearchParams();
  const sessionId = Number(sp.get("s"));
  const code = sp.get("c") ?? "";
  const [state, setState] = useState<"locating" | "sending" | "done" | "error" | "geo">("locating");
  const [message, setMessage] = useState("");
  const [geoFail, setGeoFail] = useState<GeoFailure | null>(null);
  const started = useRef(false);

  async function run() {
    setState("locating");
    setGeoFail(null);
    let fix;
    try {
      fix = await getLocation();
    } catch (reason) {
      setGeoFail(reason as GeoFailure);
      setState("geo");
      return;
    }
    setState("sending");
    try {
      const r = await api.post<{ message: string }>("/api/attendance/qr", { session_id: sessionId, code, ...fix });
      setMessage(r.message);
      setState("done");
    } catch (err) {
      setMessage(err instanceof ApiFailure ? err.message : "Could not mark attendance.");
      setState("error");
    }
  }

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    if (!sessionId || !/^\d{6}$/.test(code)) {
      setMessage("This QR link is incomplete. Scan the code on the screen again.");
      setState("error");
      return;
    }
    run();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <Page>
      <PageHeader title="Classroom QR" subtitle={sessionId ? `lecture #${sessionId}` : ""} />
      <Card>
        {state === "locating" || state === "sending" ? (
          <p className="m-0 flex items-center gap-2 text-[15px]" role="status">
            <Spinner size={16} /> {state === "locating" ? "Checking your location…" : "Marking your attendance…"}
          </p>
        ) : state === "done" ? (
          <Banner><strong className="label mb-0.5 block">Done</strong>{message}</Banner>
        ) : state === "geo" && geoFail ? (
          <>
            <Banner bad><LocationHelp reason={geoFail} /></Banner>
            <Button variant="primary" onClick={run}>Try again</Button>
          </>
        ) : (
          <>
            <Banner bad><strong className="label mb-0.5 block">Not marked</strong>{message}</Banner>
            <p className="text-[13.5px] text-ash">The code changes every 30 seconds — scan the screen again for a fresh one.</p>
          </>
        )}
        <div className="mt-3 flex gap-3 text-[13.5px]">
          <Link href="/student/mark" className="text-ink underline">Mark attendance</Link>
          <Link href="/student" className="text-ink underline">Dashboard</Link>
        </div>
      </Card>
    </Page>
  );
}
