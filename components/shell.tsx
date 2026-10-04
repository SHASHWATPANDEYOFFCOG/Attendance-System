/**
 * The portal frame: sidebar + top bar around every signed-in page.
 *
 * A Server Component. The nav is built from the role the *backend* reports for this session,
 * so a student never even receives the authority menu. Hiding links is convenience only — every
 * page and every API call is still authorised on the server.
 */
import type { ReactNode } from "react";

import Link from "next/link";

import type { Me } from "@/lib/api";
import { LogoutButton, ThemeToggle } from "@/components/controls";
import { MobileNav, SidebarNav, type NavGroup } from "@/components/shell-nav";

const ROLE_LABEL: Record<string, string> = {
  super_admin: "Administrator",
  admin: "Head of department",
  faculty: "Teacher",
  student: "Student",
  parent: "Parent",
};

export function AppShell({
  me,
  groups,
  portal,
  topRight,
  children,
}: {
  me: Me;
  groups: NavGroup[];
  portal: string;
  topRight?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="relative z-[1] min-h-screen lg:grid lg:grid-cols-[240px_minmax(0,1fr)]">
      <a
        href="#content"
        className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[60] focus:rounded-[3px] focus:bg-card focus:px-3 focus:py-2"
      >
        Skip to content
      </a>

      <aside className="sticky top-0 hidden h-screen flex-col overflow-y-auto border-r border-rule bg-card px-3 py-5 lg:flex">
        <Link href="/" className="mb-6 block px-3 no-underline">
          <span
            className="display block text-[19px] leading-tight"
            style={{
              background: "linear-gradient(100deg, var(--ink) 30%, var(--oxide))",
              WebkitBackgroundClip: "text",
              backgroundClip: "text",
              color: "transparent",
            }}
          >
            Attendance Register
          </span>
          <span className="font-mono text-[11px] text-ash">{portal}</span>
        </Link>
        <SidebarNav groups={groups} />
        <div className="mt-auto border-t border-rule px-3 pt-4">
          <p className="m-0 truncate text-[14px] font-semibold">{me.display_name}</p>
          <p className="m-0 font-mono text-[11px] text-ash">
            {ROLE_LABEL[me.role] ?? me.role}
            {me.roll_number ? ` · ${me.roll_number}` : ""}
          </p>
        </div>
      </aside>

      <div className="flex min-w-0 flex-col">
        <div className="sticky top-0 z-40 flex items-center justify-between gap-2 border-b border-rule bg-card/95 px-4 py-2 backdrop-blur md:px-5">
          <div className="flex min-w-0 items-center gap-2">
            <MobileNav groups={groups} title={portal} />
            <span className="display truncate text-[14px] lg:hidden">Attendance Register</span>
          </div>
          <div className="flex items-center gap-2">
            {topRight}
            <ThemeToggle />
            <LogoutButton to={me.role === "student" || me.role === "parent" ? "/login" : "/authority/login"} />
          </div>
        </div>
        <div id="content" className="min-w-0 flex-1">
          {children}
        </div>
      </div>
    </div>
  );
}

/** Page title block, matching the register's existing header style. */
export function PageHeader({
  title,
  subtitle,
  actions,
}: {
  title: string;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <header className="mb-5 flex flex-wrap items-end justify-between gap-4 border-b-2 border-ink pb-3">
      <div className="min-w-0">
        <h1 className="display m-0 text-[24px] md:text-[26px]">{title}</h1>
        {subtitle ? <p className="mt-0.5 font-mono text-xs text-ash">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}

/** The content column every portal page sits in. */
export function Page({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  return (
    <main className={`mx-auto px-4 pb-16 pt-6 md:px-5 ${wide ? "max-w-[1240px]" : "max-w-[1100px]"}`}>
      {children}
    </main>
  );
}
