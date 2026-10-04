"use client";

/**
 * The interactive part of the portal frame: a collapsible glass sidebar (choice remembered in
 * this browser), the top bar with search / theme / sign-out, and the command palette.
 */
import { useEffect, useState } from "react";
import type { ReactNode } from "react";

import Link from "next/link";

import { PanelLeftClose, PanelLeftOpen, ScanFace } from "lucide-react";

import { CommandButton, CommandPalette } from "@/components/command-palette";
import { LogoutButton, ThemeToggle } from "@/components/controls";
import { MobileNav, NavLinks, type NavGroup } from "@/components/shell-nav";

const COLLAPSE_KEY = "att_sidebar_collapsed";

function initials(name: string) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase()).join("") || "?";
}

export function Logo({ compact = false }: { compact?: boolean }) {
  return (
    <span className="flex items-center gap-2.5">
      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-[var(--radius)] text-white shadow-[var(--shadow-glow)]"
            style={{ backgroundImage: "var(--grad-primary)" }}>
        <ScanFace size={19} strokeWidth={2} aria-hidden />
      </span>
      {!compact ? (
        <span className="min-w-0">
          <span className="display block text-[16px] leading-tight text-ink">Attendance</span>
          <span className="block text-[11.5px] leading-tight text-ash">Register</span>
        </span>
      ) : null}
    </span>
  );
}

export function AppFrame({
  name, roleLabel, roll, groups, portal, logoutTo, topRight, children,
}: {
  name: string; roleLabel: string; roll: string | null; groups: NavGroup[]; portal: string;
  logoutTo: string; topRight?: ReactNode; children: ReactNode;
}) {
  const [collapsed, setCollapsed] = useState(false);
  useEffect(() => {
    try { setCollapsed(localStorage.getItem(COLLAPSE_KEY) === "1"); } catch { /* private mode */ }
  }, []);
  const toggle = () => {
    setCollapsed((c) => {
      try { localStorage.setItem(COLLAPSE_KEY, c ? "0" : "1"); } catch { /* private mode */ }
      return !c;
    });
  };

  return (
    <div className="relative z-[1] min-h-screen" data-collapsed={collapsed || undefined}>
      <a href="#content"
         className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[60] focus:rounded-[var(--radius)] focus:bg-card focus:px-3 focus:py-2">
        Skip to content
      </a>

      <aside
        className="glass fixed inset-y-0 left-0 z-30 hidden flex-col border-r border-rule py-5 transition-[width] duration-300 lg:flex"
        style={{ width: collapsed ? 76 : 252 }}
        aria-label="Sidebar"
      >
        <div className={collapsed ? "mb-6 flex justify-center" : "mb-6 px-4"}>
          <Link href="/" className="no-underline" aria-label="Home"><Logo compact={collapsed} /></Link>
          {!collapsed ? <p className="m-0 mt-2 font-mono text-[11px] text-ash">{portal}</p> : null}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto px-2.5">
          <NavLinks groups={groups} collapsed={collapsed} />
        </div>
        <div className={collapsed ? "mt-3 flex flex-col items-center gap-2 px-2" : "mt-3 px-3"}>
          <div className={collapsed ? "" : "flex items-center gap-2.5 rounded-[var(--radius)] border border-rule p-2.5"}>
            <span className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-[13px] font-semibold text-white"
                  style={{ backgroundImage: "var(--grad-cool)" }} title={collapsed ? `${name} · ${roleLabel}` : undefined}>
              {initials(name)}
            </span>
            {!collapsed ? (
              <span className="min-w-0">
                <span className="block truncate text-[13.5px] font-semibold">{name}</span>
                <span className="block truncate text-[11.5px] text-ash">{roleLabel}{roll ? ` · ${roll}` : ""}</span>
              </span>
            ) : null}
          </div>
          <button type="button" onClick={toggle}
                  className={`mt-2 inline-flex cursor-pointer items-center gap-2 rounded-[var(--radius)] border-0 bg-transparent px-2 py-1.5 text-[12.5px] text-ash hover:bg-tint hover:text-ink ${collapsed ? "" : "w-full"}`}
                  aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} aria-pressed={collapsed}>
            {collapsed ? <PanelLeftOpen size={17} strokeWidth={1.8} aria-hidden /> : <><PanelLeftClose size={17} strokeWidth={1.8} aria-hidden /> Collapse</>}
          </button>
        </div>
      </aside>

      {/* The fixed sidebar's width, reserved for the content column on desktop only. */}
      <style>{`@media (min-width: 1024px) { #frame-main { padding-left: ${collapsed ? 76 : 252}px; } }`}</style>
      <div id="frame-main" className="flex min-h-screen min-w-0 flex-col transition-[padding] duration-300">
          <div className="glass sticky top-0 z-40 flex items-center justify-between gap-2 border-b border-rule px-4 py-2.5 md:px-6">
            <div className="flex min-w-0 items-center gap-2">
              <MobileNav groups={groups} title={portal} />
              <span className="lg:hidden"><Logo compact /></span>
              <CommandButton />
            </div>
            <div className="flex items-center gap-2">
              {topRight}
              <ThemeToggle />
              <LogoutButton to={logoutTo} />
            </div>
          </div>
          <div id="content" className="min-w-0 flex-1">
            {children}
          </div>
      </div>
      <CommandPalette groups={groups} logoutTo={logoutTo} />
    </div>
  );
}
