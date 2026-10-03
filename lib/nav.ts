/**
 * Sidebar menus per role. Pure data: the layouts decide which one a session receives, from the
 * role the backend reports.
 */
import type { NavGroup } from "@/components/shell-nav";

export type Counts = Partial<Record<string, number>>;

export function staffNav(role: string, counts: Counts = {}): NavGroup[] {
  const groups: NavGroup[] = [
    {
      items: [
        { href: "/dashboard", label: "Dashboard", exact: true },
        { href: "/mark", label: "Mark attendance" },
        { href: "/reports", label: "Reports" },
      ],
    },
  ];
  void role;
  void counts;
  return groups;
}

export function studentNav(counts: Counts = {}): NavGroup[] {
  void counts;
  return [{ items: [{ href: "/student", label: "Dashboard", exact: true }] }];
}
