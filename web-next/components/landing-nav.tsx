"use client";

/** Landing top bar: transparent over the hero, blurred glass with a hairline once you scroll. */
import { useEffect, useState } from "react";

import Link from "next/link";

import { Logo } from "@/components/app-frame";
import { ThemeToggle } from "@/components/controls";

const LINKS = [["#how", "How it works"], ["#features", "Features"], ["#performance", "Performance"], ["/guide", "Guide"]] as const;

export function LandingNav() {
  const [scrolled, setScrolled] = useState(false);
  useEffect(() => {
    const on = () => setScrolled(window.scrollY > 12);
    on();
    window.addEventListener("scroll", on, { passive: true });
    return () => window.removeEventListener("scroll", on);
  }, []);
  return (
    <header className={`sticky top-0 z-40 transition-[background-color,border-color,backdrop-filter] duration-300 ${scrolled ? "glass border-b border-rule" : "border-b border-transparent"}`}>
      <div className="mx-auto flex max-w-[1240px] items-center justify-between gap-3 px-4 py-3 md:px-8">
        <Link href="/" className="no-underline" aria-label="Attendance Register home"><Logo /></Link>
        <nav aria-label="Sections" className="hidden items-center gap-1 md:flex">
          {LINKS.map(([href, label]) => (
            <a key={href} href={href} className="rounded-[var(--radius)] px-3 py-2 text-[14px] text-ash no-underline transition-colors hover:bg-tint hover:text-ink">{label}</a>
          ))}
        </nav>
        <div className="flex items-center gap-2">
          <ThemeToggle />
          <Link href="/login" className="btn display hidden h-[38px] items-center rounded-[var(--radius)] border border-rule px-3.5 text-[13.5px] text-ink no-underline hover:bg-tint sm:inline-flex">Sign in</Link>
          <Link href="/signup" className="btn btn-primary display inline-flex h-[38px] items-center rounded-[var(--radius)] px-3.5 text-[13.5px] text-white no-underline"
                style={{ backgroundImage: "var(--grad-primary)" }}>Register</Link>
        </div>
      </div>
    </header>
  );
}
