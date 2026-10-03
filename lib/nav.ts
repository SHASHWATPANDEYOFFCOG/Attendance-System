/**
 * Sidebar menus per role. Pure data: the layouts decide which one a session receives, from the
 * role the backend reports, and pass live counts for the badges.
 */
import type { NavGroup } from "@/components/shell-nav";

export type Counts = Partial<Record<"approvals" | "notifications" | "messages" | "leaves" | "issues" | "review", number>>;

export function staffNav(role: string, counts: Counts = {}): NavGroup[] {
  const admin = role === "admin" || role === "super_admin";
  const groups: NavGroup[] = [
    {
      items: [
        { href: "/dashboard", label: "Dashboard", exact: true },
        { href: "/staff/sessions", label: "Live sessions" },
        { href: "/mark", label: "Registers" },
        { href: "/reports", label: "Reports" },
      ],
    },
    {
      title: "Students",
      items: [
        { href: "/staff/students", label: "Directory" },
        { href: "/staff/approvals", label: "Approvals", badge: counts.approvals },
      ],
    },
    { title: "Setup", items: [{ href: "/staff/setup", label: "Academic setup" }] },
  ];
  const adminItems = [
    ...(admin ? [{ href: "/staff/admin/users", label: "Staff & roles" }] : []),
    { href: "/staff/admin/settings", label: "Settings" },
    ...(role === "super_admin" ? [{ href: "/staff/admin/audit", label: "Audit log" }] : []),
  ];
  groups.push({ title: "Administration", items: adminItems });
  return groups;
}

export function studentNav(counts: Counts = {}): NavGroup[] {
  void counts;
  return [
    {
      items: [
        { href: "/student", label: "Dashboard", exact: true },
        { href: "/student/mark", label: "Mark attendance" },
        { href: "/student/history", label: "History" },
        { href: "/student/profile", label: "My profile" },
      ],
    },
  ];
}
