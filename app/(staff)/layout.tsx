/**
 * Authority portal frame (teachers, HODs, administrators).
 *
 * The role check here is a routing convenience — a student who types /dashboard lands on their
 * own portal instead of a page of 403s. The authorization boundary is still the backend.
 */
import { redirect } from "next/navigation";

import { apiGet, getMe, isStaffRole } from "@/lib/api";
import { homeFor } from "@/lib/session";
import { staffNav } from "@/lib/nav";
import { AppShell } from "@/components/shell";

export const dynamic = "force-dynamic";

export default async function StaffLayout({ children }: { children: React.ReactNode }) {
  const me = await getMe();
  if (!me) redirect("/login");
  if (!isStaffRole(me.role)) redirect(homeFor(me.role));

  const approvals = await apiGet<{ total: number }>("/api/approvals/summary").catch(() => null);

  return (
    <AppShell me={me} groups={staffNav(me.role, { approvals: approvals?.total })} portal="Authority portal">
      {children}
    </AppShell>
  );
}
