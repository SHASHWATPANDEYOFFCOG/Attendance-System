/**
 * Authority portal frame (teachers, HODs, administrators).
 *
 * The role check here is a routing convenience — a student who types /dashboard lands on their
 * own portal instead of a page of 403s. The authorization boundary is still the backend.
 */
import { redirect } from "next/navigation";

import { apiGetAll, getMe, isStaffRole } from "@/lib/api";
import { homeFor } from "@/lib/session";
import { staffNav, type Counts } from "@/lib/nav";
import { AppShell } from "@/components/shell";
import { NotificationBell } from "@/components/notification-bell";

export const dynamic = "force-dynamic";

export default async function StaffLayout({ children }: { children: React.ReactNode }) {
  const me = await getMe();
  if (!me) redirect("/login");
  if (!isStaffRole(me.role)) redirect(homeFor(me.role));

  const raw = await apiGetAll({ approvals: "/api/approvals/summary", counts: "/api/notifications/counts" });
  const approvals = raw.approvals as { total: number } | null;
  const counts = (raw.counts ?? {}) as Counts;

  return (
    <AppShell
      me={me}
      groups={staffNav(me.role, { ...counts, approvals: approvals?.total })}
      portal="Authority portal"
      topRight={<NotificationBell initial={counts.notifications ?? 0} allHref="/staff/notifications" />}
    >
      {children}
    </AppShell>
  );
}
