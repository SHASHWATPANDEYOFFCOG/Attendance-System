import Link from "next/link";
import { redirect } from "next/navigation";

import {
  ArrowRight, BarChart3, BellRing, Boxes, Camera, Fingerprint, LockKeyhole, QrCode, ShieldCheck,
  Smartphone, Tablet, Users,
} from "lucide-react";

import { getMe } from "@/lib/api";
import { homeFor } from "@/lib/session";
import { LandingNav } from "@/components/landing-nav";
import { PipelineVisual } from "@/components/pipeline-visual";
import { Reveal } from "@/components/reveal";

export const metadata = { title: { absolute: "Attendance Register — attendance that takes itself" } };

/**
 * Signed in: straight to your own portal. Signed out: what this is, in one screen, and the two
 * doors (students / authorities). Every claim here describes what the system actually does;
 * the timings are the ones measured on this project's own CPU benchmark (see the README).
 */
export default async function Home() {
  const me = await getMe();
  if (me) redirect(homeFor(me.role));

  return (
    <div className="relative z-[1]">
      <LandingNav />

      {/* ------------------------------------------------------------------ hero */}
      <section className="mx-auto max-w-[1240px] px-4 pb-10 pt-12 md:px-8 md:pt-20">
        <div className="animate-page-in max-w-[900px]">
          <p className="label m-0 inline-flex items-center gap-2 rounded-full border border-rule px-3 py-1.5 text-[11px]">
            <span className="h-1.5 w-1.5 rounded-full" style={{ background: "var(--verdant)" }} aria-hidden />
            Face recognition attendance for colleges
          </p>
          <h1 className="headline mb-0 mt-5 text-[46px] sm:text-[64px] lg:text-[88px]">
            Attendance that <span className="text-gradient">takes itself.</span>
          </h1>
          <p className="mt-5 max-w-[640px] text-[17px] leading-relaxed text-ash md:text-[19px]">
            Classroom cameras, a teacher&apos;s tablet or a student&apos;s phone — the register fills in during the lecture.
            Masks and glasses don&apos;t stop it, and anything uncertain goes to a teacher, never a guess.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link href="/login" className="btn btn-primary display group inline-flex h-12 items-center gap-2 rounded-[var(--radius)] px-6 text-[15px] text-white no-underline"
                  style={{ backgroundImage: "var(--grad-primary)" }}>
              Student sign in <ArrowRight size={17} className="btn-arrow" aria-hidden />
            </Link>
            <Link href="/authority/login" className="btn display glass inline-flex h-12 items-center gap-2 rounded-[var(--radius)] border border-rule px-6 text-[15px] text-ink no-underline hover:bg-tint">
              Teacher & admin sign in
            </Link>
          </div>
          <p className="mt-4 text-[13.5px] text-ash">
            New here? <Link href="/signup" className="font-semibold text-ink underline-offset-4 hover:underline">Register as a student</Link>
            {" · "}<Link href="/authority/register" className="font-semibold text-ink underline-offset-4 hover:underline">Register as staff</Link>
          </p>
        </div>

        <div className="mt-10 rounded-[var(--radius-xl)] border border-rule p-2 shadow-lift md:mt-14">
          <div className="glass overflow-hidden rounded-[calc(var(--radius-xl)-6px)] border border-rule">
            <div className="flex items-center gap-2 border-b border-rule px-4 py-2.5">
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: "var(--magenta)" }} aria-hidden />
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: "var(--amber)" }} aria-hidden />
              <span className="h-2.5 w-2.5 rounded-full" style={{ background: "var(--verdant)" }} aria-hidden />
              <span className="ml-2 font-mono text-[12px] text-ash">recognition pipeline · hover a stage</span>
            </div>
            <PipelineVisual />
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------------ how */}
      <section id="how" className="mx-auto max-w-[1240px] scroll-mt-20 px-4 py-16 md:px-8 md:py-24">
        <Reveal>
          <p className="label m-0">How it works</p>
          <h2 className="headline mb-0 mt-3 max-w-[760px] text-[34px] md:text-[52px]">Three ways in. One register.</h2>
        </Reveal>
        <div className="mt-10 grid gap-4 md:grid-cols-3">
          {[
            { icon: Camera, grad: "var(--grad-primary)", title: "Classroom camera", text: "During a lecture the room's camera looks only for that class's students. A match must hold over several frames before it counts; near-misses go to a teacher for review." },
            { icon: Tablet, grad: "var(--grad-cool)", title: "Teacher's tablet", text: "Photograph the class from the front. Recognised students are ticked for you; check the list, confirm, done. Photos are never saved." },
            { icon: Smartphone, grad: "var(--grad-warm)", title: "Student's phone", text: "A live selfie with a head-turn liveness check, or the rotating classroom QR — both inside the campus geofence, both inside the lecture's time window." },
          ].map(({ icon: Icon, grad, title, text }, i) => (
            <Reveal key={title} delay={i * 90}>
              <article className="glass surface-interactive h-full rounded-[var(--radius-lg)] border border-rule p-6">
                <span className="grid h-11 w-11 place-items-center rounded-[var(--radius)] text-white" style={{ backgroundImage: grad }}>
                  <Icon size={21} strokeWidth={1.9} aria-hidden />
                </span>
                <h3 className="display mb-2 mt-5 text-[20px]">{title}</h3>
                <p className="m-0 text-[15px] leading-relaxed text-ash">{text}</p>
              </article>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ------------------------------------------------------------------ bento */}
      <section id="features" className="mx-auto max-w-[1240px] scroll-mt-20 px-4 pb-16 md:px-8 md:pb-24">
        <Reveal>
          <p className="label m-0">Built for a real college</p>
          <h2 className="headline mb-0 mt-3 text-[34px] md:text-[52px]">Everything around the register.</h2>
        </Reveal>
        <div className="mt-10 grid auto-rows-[minmax(190px,auto)] gap-4 md:grid-cols-6">
          <Reveal className="md:col-span-4 md:row-span-2">
            <article className="ring-gradient relative h-full overflow-hidden rounded-[var(--radius-xl)] p-7 shadow-lift">
              <span aria-hidden className="absolute -right-24 -top-24 h-72 w-72 rounded-full opacity-30 blur-3xl" style={{ backgroundImage: "var(--grad-aurora)" }} />
              <ShieldCheck size={26} strokeWidth={1.8} className="relative" style={{ color: "var(--electric)" }} aria-hidden />
              <h3 className="headline relative mb-3 mt-5 text-[28px] md:text-[38px]">Private by design.</h3>
              <ul className="relative m-0 grid list-none gap-2.5 p-0 text-[15.5px] text-ash sm:grid-cols-2">
                {["Video is analysed in memory and never recorded", "Faces are stored as encrypted numbers, not photos",
                  "Explicit consent; withdrawing it deletes the face data", "Unknown faces are ignored and never kept",
                  "A non-face option (QR code) always exists", "Every sensitive action is in an audit log"].map((t) => (
                  <li key={t} className="flex gap-2.5"><span aria-hidden className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: "var(--cyan)" }} />{t}</li>
                ))}
              </ul>
            </article>
          </Reveal>
          {[
            { icon: Users, title: "Approvals", text: "Registrations by status, academic year, branch and section — approve or revoke in bulk." },
            { icon: BarChart3, title: "Reports", text: "Daily, monthly, subject-wise and defaulter lists, as CSV, Excel or PDF." },
          ].map(({ icon: Icon, title, text }, i) => (
            <Reveal key={title} delay={i * 80} className="md:col-span-2">
              <BentoCard icon={<Icon size={20} strokeWidth={1.8} aria-hidden />} title={title} text={text} />
            </Reveal>
          ))}
          {[
            { icon: Boxes, title: "Workspaces", text: "Cameras and tablets grouped by building; each authority sees only theirs." },
            { icon: QrCode, title: "Rotating QR", text: "A code on the projector that changes every 30 seconds." },
            { icon: BellRing, title: "Live updates", text: "Marks, leave and messages arrive instantly, plus email." },
          ].map(({ icon: Icon, title, text }, i) => (
            <Reveal key={title} delay={i * 80} className="md:col-span-2">
              <BentoCard icon={<Icon size={20} strokeWidth={1.8} aria-hidden />} title={title} text={text} />
            </Reveal>
          ))}
        </div>
      </section>

      {/* ------------------------------------------------------------- performance */}
      <section id="performance" className="mx-auto max-w-[1240px] scroll-mt-20 px-4 pb-16 md:px-8 md:pb-24">
        <div className="grid gap-8 md:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] md:items-center">
          <Reveal>
            <p className="label m-0">Measured, not promised</p>
            <h2 className="headline mb-0 mt-3 text-[34px] md:text-[48px]">Fast enough on an ordinary CPU.</h2>
            <p className="mt-4 text-[16px] leading-relaxed text-ash">
              Per-stage cost of the recognition pipeline, medians over 15 runs on one desktop CPU with no GPU. Searching
              the whole college&apos;s faces takes under a millisecond; finding the faces in the frame is the expensive part.
            </p>
            <p className="m-0 font-mono text-[12.5px] text-ash">8.4 frames per second with one face in view, at the shipped settings.</p>
          </Reveal>
          <Reveal delay={100}>
            <LatencyChart />
          </Reveal>
        </div>
      </section>

      {/* ------------------------------------------------------------------ CTA */}
      <section className="mx-auto max-w-[1240px] px-4 pb-20 md:px-8">
        <Reveal>
          <div className="relative overflow-hidden rounded-[var(--radius-xl)] p-8 text-white md:p-14" style={{ backgroundImage: "var(--grad-aurora)" }}>
            <span aria-hidden className="absolute inset-0 opacity-30" style={{ backgroundImage: "radial-gradient(circle at 80% 20%, #fff 0, transparent 40%)" }} />
            <div className="relative grid gap-6 md:grid-cols-[1fr_auto] md:items-center">
              <div>
                <h2 className="headline m-0 text-[32px] md:text-[46px]">Ready for today&apos;s lecture?</h2>
                <p className="mb-0 mt-3 max-w-[560px] text-[16px] text-white/85">Sign in, or register in two minutes. Your teacher approves you, then you&apos;re in.</p>
              </div>
              <div className="flex flex-wrap gap-3">
                <Link href="/login" className="btn display inline-flex h-12 items-center gap-2 rounded-[var(--radius)] bg-white px-6 text-[15px] text-[#0D1330] no-underline">
                  <Fingerprint size={17} aria-hidden /> Student sign in
                </Link>
                <Link href="/authority/login" className="btn display inline-flex h-12 items-center rounded-[var(--radius)] border border-white/40 px-6 text-[15px] text-white no-underline hover:bg-white/10">
                  Staff sign in
                </Link>
              </div>
            </div>
          </div>
        </Reveal>
      </section>

      <footer className="border-t border-rule">
        <div className="mx-auto flex max-w-[1240px] flex-wrap items-center justify-between gap-3 px-4 py-6 text-[13px] text-ash md:px-8">
          <span className="inline-flex items-center gap-2"><LockKeyhole size={14} aria-hidden /> Your data stays with your college.</span>
          <nav aria-label="Footer" className="flex gap-4">
            <Link href="/privacy" className="text-ash no-underline hover:text-ink">Privacy</Link>
            <Link href="/guide" className="text-ash no-underline hover:text-ink">User guide</Link>
            <Link href="/authority/register" className="text-ash no-underline hover:text-ink">Staff registration</Link>
          </nav>
        </div>
      </footer>
    </div>
  );
}

function BentoCard({ icon, title, text }: { icon: React.ReactNode; title: string; text: string }) {
  return (
    <article className="glass surface-interactive group h-full rounded-[var(--radius-xl)] border border-rule p-6">
      <span className="grid h-10 w-10 place-items-center rounded-[var(--radius)] transition-transform duration-200 group-hover:-rotate-6 group-hover:scale-110"
            style={{ background: "color-mix(in srgb, var(--accent) 14%, transparent)", color: "var(--accent)" }}>{icon}</span>
      <h3 className="display mb-1.5 mt-4 text-[18px]">{title}</h3>
      <p className="m-0 text-[14.5px] leading-relaxed text-ash">{text}</p>
    </article>
  );
}

/** Real numbers from tools/bench_cpu.py (README "Measured per-stage cost"). Bars on a log scale
 *  so 0.3 ms and 160 ms are both visible; the value is printed, not left to the eye. */
const STAGES_MS: [string, number, string][] = [
  ["Find faces (SCRFD, 640×640)", 160, "var(--grad-warm)"],
  ["Face embedding (ArcFace)", 66, "var(--grad-primary)"],
  ["Search 5,000 faces (FAISS)", 1.0, "var(--grad-cool)"],
  ["Search 1,200 faces (FAISS)", 0.3, "var(--grad-cool)"],
];

function LatencyChart() {
  const max = Math.log10(160 * 10);
  return (
    <figure className="glass m-0 rounded-[var(--radius-xl)] border border-rule p-6">
      <figcaption className="mb-4 flex items-baseline justify-between gap-3">
        <span className="display text-[16px]">Milliseconds per stage</span>
        <span className="font-mono text-[11.5px] text-ash">log scale · lower is faster</span>
      </figcaption>
      <ul className="m-0 grid list-none gap-4 p-0">
        {STAGES_MS.map(([label, ms, grad]) => (
          <li key={label}>
            <div className="mb-1.5 flex items-baseline justify-between gap-3 text-[14px]">
              <span>{label}</span>
              <span className="font-mono font-semibold tnum">{ms} ms</span>
            </div>
            <div className="h-2.5 overflow-hidden rounded-full" style={{ background: "var(--tint-hard)" }}>
              <div className="h-full rounded-full" style={{ width: `${Math.max(4, (Math.log10(ms * 10) / max) * 100)}%`, backgroundImage: grad }} />
            </div>
          </li>
        ))}
      </ul>
    </figure>
  );
}
