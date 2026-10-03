/** Student portal frame. Staff and parents are routed to their own portals. */
import { redirect } from "next/navigation";

import { apiGet, getMe } from "@/lib/api";
import { homeFor } from "@/lib/session";
import { studentNav, type Counts } from "@/lib/nav";
import { AppShell } from "@/components/shell";
import { NotificationBell } from "@/components/notification-bell";

export const dynamic = "force-dynamic";

export default async function StudentLayout({ children }: { children: React.ReactNode }) {
  const me = await getMe();
  if (!me) redirect("/login");
  if (me.role !== "student") redirect(homeFor(me.role));

  const counts = ((await apiGet<Counts>("/api/notifications/counts").catch(() => null)) ?? {}) as Counts;

  return (
    <AppShell
      me={me}
      groups={studentNav(counts)}
      portal="Student portal"
      topRight={<NotificationBell initial={counts.notifications ?? 0} allHref="/student/notifications" />}
    >
      {children}
    </AppShell>
  );
}
