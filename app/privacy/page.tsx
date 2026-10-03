/**
 * Privacy policy — plain language, written for students. Mirrors what the code actually does;
 * if behaviour changes, this page must change with it.
 */
import Link from "next/link";

import { PublicShell } from "@/components/public-shell";

export const metadata = { title: "Privacy policy" };
export const dynamic = "force-dynamic";

const API_BASE = process.env.ATTENDANCE_API_BASE ?? "http://127.0.0.1:8079";

const DEFAULTS = { org_name: "the college", retention: { review_days: 7, thumbnail_days: 30 } };

async function facts() {
  try {
    const r = await fetch(`${API_BASE}/api/public/academic-options`, { cache: "no-store" });
    if (!r.ok) throw new Error();
    const body = (await r.json()) as { org_name?: string; retention?: Partial<typeof DEFAULTS.retention> };
    return {
      org_name: body.org_name || DEFAULTS.org_name,
      retention: { ...DEFAULTS.retention, ...body.retention },
    };
  } catch {
    return DEFAULTS;
  }
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-5">
      <h2 className="display m-0 mb-1.5 text-[16px]">{title}</h2>
      <div className="grid gap-2 text-[14.5px] leading-relaxed">{children}</div>
    </section>
  );
}

export default async function PrivacyPage() {
  const f = await facts();
  return (
    <PublicShell width={760} subtitle="Privacy policy">
      <article className="rounded-[3px] border border-rule bg-card p-5 shadow-lift sm:p-7">
        <h1 className="display m-0 mb-1 text-[22px]">How {f.org_name} handles your data</h1>
        <p className="mt-0 font-mono text-[12px] text-ash">Attendance portal · applies to students, staff and guardians</p>

        <Section title="Who is responsible">
          <p className="m-0">{f.org_name} is the data fiduciary for this attendance system under India&apos;s Digital Personal Data
            Protection Act, 2023 (DPDP Act). Questions, corrections and requests go to the college office or your class
            teacher; you can also raise an issue in the portal.</p>
        </Section>

        <Section title="What we collect, and why">
          <ul className="m-0 pl-5">
            <li><strong>Account and academic details</strong> — name, email, mobile, roll and enrollment number, branch, batch,
              section, date of birth, gender, address, guardian contact, profile photo. Used to identify you, place you in your
              class and contact you or your guardian about attendance.</li>
            <li><strong>Attendance records</strong> — for each lecture, your status, how it was marked (camera, selfie, QR,
              teacher) and when. Used to compute attendance percentages and reports. They are academic records.</li>
            <li><strong>Location (only when you mark attendance from your phone)</strong> — one reading, checked against the
              campus area. Only the distance and the result are kept, not a location history.</li>
            <li><strong>Leave, issues and messages</strong> you send, with any files you attach.</li>
            <li><strong>Face data — only if you consent</strong> (see below).</li>
          </ul>
        </Section>

        <Section title="Face data (biometric) — only with your consent">
          <ul className="m-0 pl-5">
            <li>Face enrollment is <strong>optional</strong>. Without it you mark attendance with the classroom code / QR, or
              your teacher marks you. Nothing else changes.</li>
            <li>When you enroll, the server turns five photos into a numeric <strong>face template</strong>, stored
              <strong> encrypted</strong>. The photos themselves are kept encrypted only until your teacher reviews them, then
              deleted.</li>
            <li>The template is used <strong>only for attendance</strong>: to check a selfie is you, and for classroom cameras
              to recognise you during <strong>your own lectures</strong>. It is never used for anything else, never sold and
              never shared outside the college.</li>
            <li>Classroom cameras analyse video in memory; <strong>no video is recorded</strong>. Faces of people who are not
              students of the lecture are ignored and not stored. A near-certain match may be saved as an encrypted face crop
              for your teacher to confirm; it is deleted when they decide, or after {f.retention.review_days} days at most.</li>
            <li>You can <strong>withdraw consent any time</strong> from the Face check page. Your template and any crops are
              deleted immediately and permanently.</li>
            <li>Face data is also deleted when you leave the college or your account is removed.</li>
          </ul>
        </Section>

        <Section title="Who can see what">
          <ul className="m-0 pl-5">
            <li>You see only your own data.</li>
            <li>Teachers see students of the classes they teach; a head of department sees their branch; administrators
              manage the whole system. Every access rule is enforced by the server.</li>
            <li>Sensitive actions — attendance changes, approvals, role changes, deletions, settings changes — are written to
              an audit log with who did it and when.</li>
          </ul>
        </Section>

        <Section title="How it is protected">
          <ul className="m-0 pl-5">
            <li>Passwords are stored as one-way hashes (argon2), never in readable form.</li>
            <li>Face templates, review crops and camera passwords are encrypted at rest.</li>
            <li>Uploaded files are stored outside the public website and served only to people allowed to see them.</li>
            <li>Sessions use secure, http-only cookies; sign-in is rate-limited and accounts lock after repeated failures.</li>
          </ul>
        </Section>

        <Section title="How long we keep it">
          <ul className="m-0 pl-5">
            <li>Attendance records: kept as academic records as required by the college, including after you graduate.</li>
            <li>Face template: until consent is withdrawn, or you leave / are removed.</li>
            <li>Camera review crops: at most {f.retention.review_days} days. Other recognition crops: at most{" "}
              {f.retention.thumbnail_days} days.</li>
            <li>Account details, notifications, messages, leave and issue records: kept with your account. When your
              account is removed it is closed and your face data erased; ask the college office if you need other personal
              data erased.</li>
          </ul>
        </Section>

        <Section title="Your rights">
          <p className="m-0">Under the DPDP Act you can ask to access your data, correct it (from your profile, or by an edit
            request for locked details), have it erased where the law allows, withdraw consent for face data at any time, and
            raise a grievance with the college. Attendance records required for academic purposes may be kept after a request
            to erase other data.</p>
        </Section>

        <p className="mb-0 mt-6 text-[13px] text-ash">
          <Link href="/guide" className="text-ink underline">How to use the portal</Link> ·{" "}
          <Link href="/login" className="text-ink underline">Sign in</Link>
        </p>
      </article>
    </PublicShell>
  );
}
