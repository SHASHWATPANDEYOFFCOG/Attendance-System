/** Frame for the signed-out pages: sign in, sign up, verification, password reset, guides. */
import type { ReactNode } from "react";

import Link from "next/link";

import { Logo } from "@/components/app-frame";
import { ThemeToggle } from "@/components/controls";

/** Brand block shared by every public page: logo, gradient wordmark, page subtitle. */
export function BrandHeader({ subtitle, heading = true }: { subtitle: string; heading?: boolean }) {
  const Tag = heading ? "h1" : "p";
  return (
    <header className="mb-7 flex flex-col items-center text-center">
      <Link href="/" className="no-underline" aria-label="Attendance Register home"><Logo compact /></Link>
      <Tag className="headline mb-0 mt-4 text-[30px] sm:text-[34px]"><span className="text-gradient">Attendance Register</span></Tag>
      <p className="m-0 mt-2 text-[14px] text-ash">{subtitle}</p>
    </header>
  );
}

/** Top-corner controls for public pages: back to the landing page, theme. */
export function PublicTopBar() {
  return (
    <div className="absolute inset-x-0 top-0 z-10 flex items-center justify-between px-4 py-3 md:px-6">
      <Link href="/" className="rounded-[var(--radius)] px-2.5 py-1.5 text-[13.5px] text-ash no-underline hover:bg-tint hover:text-ink">← Home</Link>
      <ThemeToggle />
    </div>
  );
}

export function PublicShell({
  children,
  width = 440,
  subtitle = "Smart attendance",
  brandHeading = true,
}: {
  children: ReactNode;
  width?: number;
  subtitle?: string;
  /** False on pages that have their own <h1> (guide, privacy): one main heading per page. */
  brandHeading?: boolean;
}) {
  return (
    <main className="relative z-[1] grid min-h-screen place-items-center px-4 pb-10 pt-16">
      <PublicTopBar />
      <div className="animate-page-in w-full" style={{ maxWidth: width }}>
        <BrandHeader subtitle={subtitle} heading={brandHeading} />
        {children}
        <p className="mt-6 text-center text-[12.5px] text-ash">
          <Link href="/privacy" className="text-ash underline-offset-2 hover:underline">
            Privacy policy
          </Link>
          {" · "}
          <Link href="/guide" className="text-ash underline-offset-2 hover:underline">
            Help
          </Link>
        </p>
      </div>
    </main>
  );
}

export function AuthCard({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className="glass rounded-[var(--radius-xl)] border border-rule p-6 shadow-lift sm:p-7">
      {title ? <h2 className="display m-0 mb-4 text-[20px]">{title}</h2> : null}
      {children}
    </section>
  );
}
