"use client";

import { useEffect, useState } from "react";

import { useRouter } from "next/navigation";

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
      className="display cursor-pointer rounded-[3px] border border-ink bg-transparent px-3.5 py-2 text-[12px] text-ink hover:bg-tint"
    >
      Sign out
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
      className="inline-flex h-[34px] w-[34px] cursor-pointer items-center justify-center rounded-[3px] border border-rule bg-transparent text-ash hover:border-ash hover:text-ink"
    >
      {dark ? (
        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" />
        </svg>
      )}
    </button>
  );
}
