/**
 * Sidebar menus per role. Pure data: the layouts decide which one a session receives, from the
 * role the backend reports, and pass live counts for the badges.
 */
import type { NavGroup } from "@/components/shell-nav";

export type Counts = Partial<Record<
  "approvals" | "notifications" | "messages" | "announcements" | "leaves" | "issues" | "review", number
>>;

const HELP: NavGroup = {
  title: "Help",
  items: [
    { href: "/guide", label: "User guide" },
    { href: "/privacy", label: "Privacy" },
  ],
};

export function staffNav(role: string, counts: Counts = {}): NavGroup[] {
  const admin = role === "admin" || role === "super_admin";
  return [
    {
      items: [
        { href: "/dashboard", label: "Dashboard", exact: true },
        { href: "/staff/sessions", label: "Live sessions" },
        { href: "/mark", label: "Registers" },
        { href: "/staff/reports", label: "Reports" },
      ],
    },
    {
      title: "Students",
      items: [
        { href: "/staff/students", label: "Directory" },
        { href: "/staff/approvals", label: "Approvals", badge: counts.approvals },
        { href: "/staff/review", label: "Camera review", badge: counts.review },
        { href: "/staff/leaves", label: "Leave", badge: counts.leaves },
        { href: "/staff/issues", label: "Issues", badge: counts.issues },
      ],
    },
    {
      title: "Communicate",
      items: [
        { href: "/staff/messages", label: "Messages", badge: counts.messages },
        { href: "/staff/announcements", label: "Notice board" },
        { href: "/staff/notifications", label: "Notifications", badge: counts.notifications },
      ],
    },
    {
      title: "Setup",
      items: [
        { href: "/staff/setup", label: "Academic setup" },
        { href: "/staff/cameras", label: "CCTV cameras" },
      ],
    },
    {
      title: "Administration",
      items: [
        ...(admin ? [{ href: "/staff/admin/users", label: "Staff & roles" }] : []),
        { href: "/staff/admin/settings", label: "Settings" },
        ...(role === "super_admin" ? [{ href: "/staff/admin/audit", label: "Audit log" }] : []),
      ],
    },
    HELP,
  ];
}

export function studentNav(counts: Counts = {}): NavGroup[] {
  return [
    {
      items: [
        { href: "/student", label: "Dashboard", exact: true },
        { href: "/student/mark", label: "Mark attendance" },
        { href: "/student/history", label: "History" },
      ],
    },
    {
      title: "Requests",
      items: [
        { href: "/student/leaves", label: "Leave" },
        { href: "/student/issues", label: "Issues & queries" },
      ],
    },
    {
      title: "Inbox",
      items: [
        { href: "/student/messages", label: "Messages", badge: (counts.messages ?? 0) + (counts.announcements ?? 0) || undefined },
        { href: "/student/notifications", label: "Notifications", badge: counts.notifications },
      ],
    },
    {
      title: "Account",
      items: [
        { href: "/student/profile", label: "My profile" },
        { href: "/student/face", label: "Face check" },
      ],
    },
    HELP,
  ];
}
