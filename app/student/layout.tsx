/** Student portal frame. Staff and parents are routed to their own portals. */
import { redirect } from "next/navigation";

import { getMe } from "@/lib/api";
import { homeFor } from "@/lib/session";
import { studentNav } from "@/lib/nav";
import { AppShell } from "@/components/shell";

export const dynamic = "force-dynamic";

export default async function StudentLayout({ children }: { children: React.ReactNode }) {
  const me = await getMe();
  if (!me) redirect("/login");
  if (me.role !== "student") redirect(homeFor(me.role));

  return (
    <AppShell me={me} groups={studentNav()} portal="Student portal">
      {children}
    </AppShell>
  );
}
