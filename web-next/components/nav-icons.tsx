/**
 * One icon per destination, from one library (Lucide), one stroke width. Keyed by route so the
 * nav data in lib/nav.ts stays plain and serialisable.
 */
import {
  BadgeCheck,
  BarChart3,
  Bell,
  BookOpen,
  Boxes,
  CalendarOff,
  Camera,
  ClipboardCheck,
  Fingerprint,
  GraduationCap,
  History,
  Home,
  KeyRound,
  LayoutDashboard,
  LifeBuoy,
  Lock,
  type LucideIcon,
  Megaphone,
  MessageSquare,
  Radio,
  ScanFace,
  ScrollText,
  Settings,
  ShieldCheck,
  Tablet,
  User,
  Users,
  Video,
} from "lucide-react";

const ICONS: Record<string, LucideIcon> = {
  "/dashboard": LayoutDashboard,
  "/staff/sessions": Radio,
  "/mark": ClipboardCheck,
  "/staff/reports": BarChart3,
  "/staff/students": Users,
  "/staff/approvals": BadgeCheck,
  "/staff/review": ScanFace,
  "/staff/leaves": CalendarOff,
  "/staff/issues": LifeBuoy,
  "/staff/messages": MessageSquare,
  "/staff/announcements": Megaphone,
  "/staff/notifications": Bell,
  "/staff/setup": GraduationCap,
  "/staff/cameras": Video,
  "/staff/workspaces": Boxes,
  "/staff/tablets": Tablet,
  "/staff/admin/users": ShieldCheck,
  "/staff/admin/settings": Settings,
  "/staff/admin/audit": ScrollText,
  "/staff/admin/access": KeyRound,
  "/guide": BookOpen,
  "/privacy": Lock,
  "/student": Home,
  "/student/mark": Fingerprint,
  "/student/history": History,
  "/student/leaves": CalendarOff,
  "/student/issues": LifeBuoy,
  "/student/messages": MessageSquare,
  "/student/notifications": Bell,
  "/student/profile": User,
  "/student/face": Camera,
};

export function NavIcon({ href, size = 17 }: { href: string; size?: number }) {
  const Icon = ICONS[href] ?? LayoutDashboard;
  return <Icon size={size} strokeWidth={1.8} aria-hidden="true" className="shrink-0" />;
}
