/**
 * The portal frame: sidebar + top bar around every signed-in page.
 *
 * A Server Component. The nav is built from the role the *backend* reports for this session,
 * so a student never even receives the authority menu. Hiding links is convenience only — every
 * page and every API call is still authorised on the server.
 */
import type { ReactNode } from "react";

import type { Me } from "@/lib/api";
import { AppFrame } from "@/components/app-frame";
import type { NavGroup } from "@/components/shell-nav";

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
    <AppFrame
      name={me.display_name}
      roleLabel={ROLE_LABEL[me.role] ?? me.role}
      roll={me.roll_number ?? null}
      groups={groups}
      portal={portal}
      logoutTo={me.role === "student" || me.role === "parent" ? "/login" : "/authority/login"}
      topRight={topRight}
    >
      {children}
    </AppFrame>
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
    <header className="relative mb-6 flex flex-wrap items-end justify-between gap-4 pb-4">
      <div className="min-w-0">
        <h1 className="headline m-0 text-[28px] md:text-[36px]">{title}</h1>
        {subtitle ? <p className="mt-1.5 text-[13.5px] text-ash">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      {/* Gradient hairline: the page's one strong accent line. */}
      <span aria-hidden className="absolute bottom-0 left-0 h-px w-full" style={{ background: "linear-gradient(90deg, var(--electric), var(--violet) 40%, transparent)" }} />
    </header>
  );
}

/** The content column every portal page sits in. */
export function Page({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  return (
    <main className={`animate-page-in mx-auto px-4 pb-16 pt-7 md:px-8 ${wide ? "max-w-[1280px]" : "max-w-[1120px]"}`}>
      {children}
    </main>
  );
}
