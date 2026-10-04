"use client";

import { useEffect, useState } from "react";

import { useRouter } from "next/navigation";

import { LogOut, Moon, SunMedium } from "lucide-react";

export function LogoutButton({ to = "/login" }: { to?: string }) {
  const router = useRouter();
  return (
    <button
      type="button"
      onClick={async () => {
        await fetch("/api/auth/logout", { method: "POST" });
        router.push(to);
        router.refresh();
      }}
      className="btn display inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-[var(--radius)] border border-rule bg-transparent px-3 text-[13px] text-ink hover:bg-tint"
      aria-label="Sign out"
    >
      <LogOut size={16} strokeWidth={1.8} aria-hidden />
      <span className="hidden sm:inline">Sign out</span>
    </button>
  );
}

/**
 * Theme toggle. The stored preference is applied by an inline script in the layout BEFORE
 * paint (see app/layout.tsx), so a dark-mode user never sees a light flash; this component
 * only handles the click and keeps its label in sync.
 */
export function ThemeToggle() {
  const [dark, setDark] = useState(false);

  useEffect(() => {
    const root = document.documentElement;
    const isDark =
      root.getAttribute("data-theme") === "dark" ||
      (!root.hasAttribute("data-theme") &&
        window.matchMedia("(prefers-color-scheme: dark)").matches);
    setDark(isDark);
  }, []);

  return (
    <button
      type="button"
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      title={dark ? "Switch to light theme" : "Switch to dark theme"}
      onClick={() => {
        const next = dark ? "light" : "dark";
        document.documentElement.setAttribute("data-theme", next);
        try {
          localStorage.setItem("att_theme", next);
        } catch {
          /* private mode — the toggle still works for this page view */
        }
        setDark(!dark);
      }}
      className="btn inline-flex h-[38px] w-[38px] cursor-pointer items-center justify-center rounded-[var(--radius)] border border-rule bg-transparent text-ash hover:bg-tint hover:text-ink"
    >
      <span className="inline-flex transition-transform duration-300" style={{ transform: dark ? "rotate(0deg)" : "rotate(-90deg)" }}>
        {dark ? <SunMedium size={17} strokeWidth={1.8} aria-hidden /> : <Moon size={17} strokeWidth={1.8} aria-hidden />}
      </span>
    </button>
  );
}
