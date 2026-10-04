/** User guide for administrators, authorities, tablets, teachers and students. Public, so it
 *  helps before the first sign-in; it never shows the access codes themselves. */
import Link from "next/link";

import { PublicShell } from "@/components/public-shell";

export const metadata = { title: "User guide" };
export const dynamic = "force-dynamic";

const API_BASE = process.env.ATTENDANCE_API_BASE ?? "http://127.0.0.1:8079";
const DEFAULT_POLICY = { present_window_min: 10, late_window_min: 20, min_attendance_pct: 75 };

/** The college's own windows and minimum, so the guide never contradicts the settings. */
async function policy() {
  try {
    const r = await fetch(`${API_BASE}/api/public/academic-options`, { cache: "no-store" });
    if (!r.ok) throw new Error();
    const body = (await r.json()) as { policy?: Partial<typeof DEFAULT_POLICY> };
    return { ...DEFAULT_POLICY, ...body.policy };
  } catch {
    return DEFAULT_POLICY;
  }
}

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <li className="flex gap-3">
      <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full font-mono text-[13px] font-semibold"
            style={{ background: "var(--grad-primary)", color: "var(--on-accent)" }}>{n}</span>
      <div className="min-w-0">
        <strong className="text-[15px]">{title}</strong>
        <div className="text-[14px] text-ink/85">{children}</div>
      </div>
    </li>
  );
}

export default async function GuidePage() {
  const p = await policy();
  return (
    <PublicShell brandHeading={false} width={820} subtitle="User guide">
      <div className="grid gap-4">
        <h1 className="display m-0 text-center text-[22px]">User guide</h1>
        <nav aria-label="Guide sections" className="flex flex-wrap justify-center gap-1.5 text-[13px]">
          {[["#administrator", "Administrator"], ["#authority", "Authority"], ["#tablet", "Tablet"], ["#teachers", "Taking attendance"], ["#students", "Students"]].map(([href, label]) => (
            <a key={href} href={href} className="display rounded-[var(--radius)] border border-rule px-3 py-1.5 text-[12.5px] text-ink no-underline hover:bg-tint">{label}</a>
          ))}
        </nav>

        <section className="rounded-[var(--radius)] border border-rule bg-card p-5 shadow-lift sm:p-6" aria-labelledby="administrator">
          <h2 id="administrator" className="display m-0 mb-1 text-[20px]">Administrator guide</h2>
          <p className="mb-3 mt-0 text-[13.5px] text-ash">Administrators control the whole system. You need an authority account and the administrator code.</p>
          <ol className="m-0 grid list-none gap-3.5 p-0">
            <Step n={1} title="Sign in and become administrator">
              Register at <Link href="/authority/register" className="underline">Authority register</Link> (with the authority code) or use the
              account you were given, sign in at <Link href="/authority/login" className="underline">Authority sign in</Link>, then open{" "}
              <em>Administration → Administrator access</em> and enter the administrator code.
            </Step>
            <Step n={2} title="Change the access codes">
              <em>Settings → Access codes</em>: set your own administrator code and authority code. The old code stops working at once. Codes
              are stored only as one-way hashes, so keep the new ones somewhere safe.
            </Step>
            <Step n={3} title="Build the academic structure">
              <em>Academic setup</em>: add academic years (mark the current one), branches, batches, class groups (sections, each with its year
              and academic year), subjects, rooms, the term and the timetable. Anything can be deactivated instead of deleted: it disappears
              from registration but its history stays.
            </Step>
            <Step n={4} title="Create workspaces">
              <em>Workspaces</em>: a workspace groups cameras and tablets, e.g. &quot;CSE Block&quot;. Add the authorities who may use it.
            </Step>
            <Step n={5} title="Add cameras">
              <em>CCTV cameras → Add camera</em>: name, type, the stream address (without login), the login in its own fields, the room it
              watches and its workspace. Press <em>Test connection</em> to see a frame. Only the workspace&apos;s authorities can use it.
            </Step>
            <Step n={6} title="Manage authorities">
              <em>Staff &amp; roles</em>: add teachers and HODs, change roles, disable or re-enable accounts. HOD rights are only ever given
              here, by an administrator.
            </Step>
            <Step n={7} title="Monitor">
              The dashboard shows cameras online/offline, authorities, tablets, workspaces and students by approval status.{" "}
              <em>Audit log</em> records every sensitive action: who, when, what changed.
            </Step>
          </ol>
        </section>

        <section className="rounded-[var(--radius)] border border-rule bg-card p-5 shadow-lift sm:p-6" aria-labelledby="authority">
          <h2 id="authority" className="display m-0 mb-1 text-[20px]">Authority guide (teachers and HODs)</h2>
          <ol className="m-0 grid list-none gap-3.5 p-0">
            <Step n={1} title="Get an account">
              Register at <Link href="/authority/register" className="underline">Authority register</Link> with the authority code from your
              administrator, then sign in at <Link href="/authority/login" className="underline">Authority sign in</Link>.
            </Step>
            <Step n={2} title="Your workspace">
              An administrator adds you to a workspace. <em>Workspaces</em> shows yours, with its cameras; you see nothing of other workspaces.
            </Step>
            <Step n={3} title="Register your tablet">
              <em>Tablets → Register a tablet</em>: give it a name, choose the workspace and the cameras it may use. You get a one-time pairing
              code, valid for 15 minutes. Pair the tablet with it (see the tablet guide below).
            </Step>
            <Step n={4} title="Approve students">
              <em>Approvals → Students</em>: filter by academic year, branch, batch, year and section; switch between Pending, Approved, Rejected
              and Revoked. Approve, reject (with a reason), revoke or restore, one at a time or by ticking several. Every decision is logged.
            </Step>
            <Step n={5} title="Look after your tablets">
              Disable a tablet you are not using, issue a new pairing code to replace a device, or revoke a lost tablet: it stops working on
              its next request.
            </Step>
          </ol>
        </section>

        <section className="rounded-[var(--radius)] border border-rule bg-card p-5 shadow-lift sm:p-6" aria-labelledby="tablet">
          <h2 id="tablet" className="display m-0 mb-1 text-[20px]">Tablet guide</h2>
          <ol className="m-0 grid list-none gap-3.5 p-0">
            <Step n={1} title="Open the website on the tablet">Use its browser (Chrome or Safari). Add it to the home screen for an app-like icon.</Step>
            <Step n={2} title="Sign in">At <Link href="/authority/login" className="underline">Authority sign in</Link>, with your own authority account.</Step>
            <Step n={3} title="Pair the device">
              Open <em>Tablets</em>. Under <em>This device</em>, enter the 8-character pairing code shown when the tablet was registered. The
              tablet now shows as active, with its workspace and cameras.
            </Step>
            <Step n={4} title="Take attendance">
              Open a live lecture (<em>Live sessions → Take attendance</em>). <em>Tablet photo</em> photographs the class;{" "}
              <em>Classroom camera</em> connects one of the tablet&apos;s cameras. The tablet can only use the cameras assigned to it.
            </Step>
          </ol>
        </section>

        <section className="rounded-[var(--radius)] border border-rule bg-card p-5 shadow-lift sm:p-6" aria-labelledby="students">
          <h2 id="students" className="display m-0 mb-3 text-[20px]">Student guide</h2>
          <ol className="m-0 grid list-none gap-3.5 p-0">
            <Step n={1} title="Register">
              Open <Link href="/signup" className="underline">Register</Link>, fill in your details exactly as in college
              records, choose your branch, year, batch and section, and add a profile photo, then sign in.
            </Step>
            <Step n={2} title="Wait for approval">
              Your class teacher checks and approves your account. You can sign in meanwhile, but cannot mark attendance until
              approved. If rejected, the reason is shown — fix your details in <em>My profile</em> and resubmit.
            </Step>
            <Step n={3} title="(Optional) Enroll your face">
              In <em>Face check</em>, read and accept the consent, then follow the on-screen prompts: look straight, then turn
              and tilt your head slightly as asked. Good light, no mask or sunglasses. Your teacher approves it.
            </Step>
            <Step n={4} title="Mark attendance in class">
              When a lecture is live, <em>Mark attendance</em> appears on your dashboard. Use <strong>Face check</strong> (a short
              selfie with head turns) or <strong>Classroom code</strong> (scan the QR on the screen or type its 6 digits). Your
              location is checked once. Within {p.present_window_min} minutes of the start you are Present, until{" "}
              {p.late_window_min} minutes Late, after that the window closes. Classroom cameras may also mark you automatically.
            </Step>
            <Step n={5} title="Leave, issues and messages">
              Apply for leave (with a certificate if you have one) under <em>Leave</em> — approved leave becomes “On leave” and
              does not count against you. Raise attendance corrections or other problems under <em>Issues</em>. Messages and
              notices from teachers appear under <em>Messages</em>, and the bell shows new notifications instantly.
            </Step>
            <Step n={6} title={`Keep above ${p.min_attendance_pct}%`}>
              Your dashboard shows your percentage per subject, a calendar, and — if you are below the minimum — exactly how many
              classes in a row you need. Download your history as a PDF from <em>History</em>.
            </Step>
          </ol>
          <div className="mt-4 rounded-[var(--radius)] bg-tint p-3 text-[13.5px]">
            <strong>Camera or location blocked?</strong> On Android Chrome: tap the lock icon by the address → Permissions → allow
            Camera and Location. On iPhone Safari: tap <strong>aA</strong> → Website Settings → allow Camera and Location, and check
            Settings → Privacy &amp; Security → Location Services is on.
          </div>
        </section>

        <section className="rounded-[var(--radius)] border border-rule bg-card p-5 shadow-lift sm:p-6" aria-labelledby="teachers">
          <h2 id="teachers" className="display m-0 mb-3 text-[20px]">Taking attendance (teachers)</h2>
          <ol className="m-0 grid list-none gap-3.5 p-0">
            <Step n={1} title="Your classes">
              Sign in at <Link href="/authority/login" className="underline">Authority sign in</Link>; you land on the
              authority dashboard. The admin or HOD assigns you subjects and classes and builds the timetable (Setup). You see only students of
              your classes — everywhere: directory, reports, leave, issues.
            </Step>
            <Step n={2} title="Approvals">
              <em>Approvals</em> lists new registrations (check details against college records), profile corrections and face
              enrollments (compare the photos with the profile photo). A rejection always needs a reason.
            </Step>
            <Step n={3} title="Running a lecture">
              Lectures start by themselves at the timetabled time (or press <em>Start session</em> in <em>Live sessions</em>).
              Open <em>Show QR full-screen</em> on the classroom projector. The live view fills in as students mark; tap P / L / A
              / O / E to mark anyone by hand. Changing a mark that is already recorded asks for a reason — it goes to the audit
              log and to the student. At the end time everyone unmarked becomes Absent (or On leave if covered by approved leave).
            </Step>
            <Step n={4} title="Tablet photo and cameras">
              In a live lecture, <strong>Tablet photo</strong> lets you photograph the class with a tablet or phone: recognised
              students are ticked for you, you check the list and confirm. Photos are not saved. <strong>Classroom camera</strong>
              connects any registered CCTV camera to the lecture, with a preview of what it sees; it then marks students it is
              confident about by itself. Near matches wait in <em>Camera review</em>. If a camera goes offline you are notified.
            </Step>
            <Step n={5} title="Leave, issues, messages, notices">
              Approve leave (approved leave also corrects absences already recorded), answer issues, message one student, a class
              or everyone in your classes, and post notices with optional email.
            </Step>
            <Step n={6} title="Reports">
              <em>Reports</em> gives daily, monthly, subject-wise, student-wise and defaulter reports for any date range, each
              downloadable as CSV, Excel or PDF.
            </Step>
          </ol>
        </section>
        <p className="m-0 text-center text-[13px] text-ash">
          <Link href="/privacy" className="text-ink underline">Privacy policy</Link> · <Link href="/login" className="text-ink underline">Student sign in</Link> · <Link href="/authority/login" className="text-ink underline">Authority sign in</Link>
        </p>
      </div>
    </PublicShell>
  );
}
