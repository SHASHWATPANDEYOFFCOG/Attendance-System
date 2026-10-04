"use client";

/**
 * Sidebar navigation. A glass column on desktop (collapsible to icons); on phones a drawer
 * behind a menu button, so the content gets the full width. Active state comes from the URL,
 * never from local state, so a reload or a deep link always highlights the right item.
 */
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { clsx } from "clsx";
import { Menu, X } from "lucide-react";

import { NavIcon } from "@/components/nav-icons";

export type NavItem = { href: string; label: string; badge?: number; exact?: boolean };
export type NavGroup = { title?: string; items: NavItem[] };

function isActive(pathname: string, item: NavItem) {
  if (item.exact) return pathname === item.href;
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}

function Badge({ n, dot = false }: { n: number; dot?: boolean }) {
  if (dot) {
    return <span aria-label={`${n} new`} className="absolute right-1.5 top-1.5 h-2 w-2 rounded-full" style={{ background: "var(--magenta)" }} />;
  }
  return (
    <span className="min-w-[20px] rounded-full px-1.5 text-center font-mono text-[11px] font-semibold leading-[18px]"
          style={{ backgroundImage: "var(--grad-warm)", color: "#fff" }} aria-label={`${n} new`}>
      {n > 99 ? "99+" : n}
    </span>
  );
}

export function NavLinks({ groups, onNavigate, collapsed = false }: { groups: NavGroup[]; onNavigate?: () => void; collapsed?: boolean }) {
  const pathname = usePathname();
  return (
    <nav aria-label="Main" className="grid gap-5">
      {groups.map((g, gi) => (
        <div key={g.title ?? gi}>
          {g.title && !collapsed ? <p className="label m-0 mb-1.5 px-3 text-[10.5px] text-muted">{g.title}</p> : null}
          {g.title && collapsed ? <div className="mx-3 mb-2 border-t border-rule" aria-hidden /> : null}
          <ul className="m-0 grid list-none gap-0.5 p-0">
            {g.items.map((item) => {
              const active = isActive(pathname, item);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    title={collapsed ? item.label : undefined}
                    aria-label={collapsed ? item.label : undefined}
                    className={clsx(
                      "group relative flex items-center gap-2.5 rounded-[var(--radius)] px-3 py-2 text-[14px] no-underline transition-colors duration-150",
                      collapsed && "justify-center px-0",
                      active ? "font-semibold text-ink" : "text-ash hover:bg-tint hover:text-ink",
                    )}
                    style={active ? { background: "color-mix(in srgb, var(--accent) 12%, transparent)" } : undefined}
                  >
                    {active ? (
                      <span aria-hidden className="absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-full" style={{ backgroundImage: "var(--grad-primary)" }} />
                    ) : null}
                    <span style={active ? { color: "var(--accent)" } : undefined} className="transition-transform duration-150 group-hover:scale-110">
                      <NavIcon href={item.href} />
                    </span>
                    {!collapsed ? <span className="min-w-0 flex-1 truncate">{item.label}</span> : null}
                    {item.badge ? <Badge n={item.badge} dot={collapsed} /> : null}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );
}

/** Back-compat name used by older imports. */
export function SidebarNav({ groups }: { groups: NavGroup[] }) {
  return <NavLinks groups={groups} />;
}

export function MobileNav({ groups, title }: { groups: NavGroup[]; title: string }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = "";
    };
  }, [open]);

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Open menu"
        aria-expanded={open}
        aria-controls="mobile-drawer"
        className="inline-flex h-[40px] w-[40px] cursor-pointer items-center justify-center rounded-[var(--radius)] border border-rule bg-transparent text-ink lg:hidden"
      >
        <Menu size={18} strokeWidth={1.8} aria-hidden />
      </button>
      {/* Portalled to <body>: the sticky top bar has a backdrop blur, and a blurred ancestor
          becomes the containing block for `position: fixed` — the drawer would be clipped to the
          bar's height instead of covering the screen. */}
      {open && typeof document !== "undefined" ? createPortal(
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="Menu" id="mobile-drawer">
          <button
            type="button"
            aria-label="Close menu"
            className="absolute inset-0 cursor-default border-0 bg-black/50 backdrop-blur-[2px]"
            onClick={() => setOpen(false)}
          />
          <div className="glass animate-pop-in absolute inset-y-0 left-0 w-[84%] max-w-[310px] overflow-y-auto border-r border-rule p-4 shadow-lift">
            <div className="mb-4 flex items-center justify-between">
              <span className="display text-[15px]">{title}</span>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Close menu"
                className="inline-flex h-[40px] w-[40px] cursor-pointer items-center justify-center rounded-[var(--radius)] border border-rule bg-transparent text-ash"
              >
                <X size={18} strokeWidth={1.8} aria-hidden />
              </button>
            </div>
            <NavLinks groups={groups} onNavigate={() => setOpen(false)} />
          </div>
        </div>,
        document.body,
      ) : null}
    </>
  );
}
