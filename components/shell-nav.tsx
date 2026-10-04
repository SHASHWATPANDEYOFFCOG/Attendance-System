"use client";

/**
 * Sidebar navigation. A fixed column on desktop; on phones a drawer behind a menu button, so
 * the content gets the full 360 px. Active state comes from the URL, never from local state,
 * so a reload or a deep link always highlights the right item.
 */
import { useEffect, useState } from "react";
import { createPortal } from "react-dom";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { clsx } from "clsx";

export type NavItem = { href: string; label: string; badge?: number; exact?: boolean };
export type NavGroup = { title?: string; items: NavItem[] };

function isActive(pathname: string, item: NavItem) {
  if (item.exact) return pathname === item.href;
  return pathname === item.href || pathname.startsWith(`${item.href}/`);
}

function Links({ groups, onNavigate }: { groups: NavGroup[]; onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <nav aria-label="Main" className="grid gap-5">
      {groups.map((g, gi) => (
        <div key={g.title ?? gi}>
          {g.title ? <p className="label m-0 mb-1.5 px-3 text-[11px]">{g.title}</p> : null}
          <ul className="m-0 grid list-none gap-0.5 p-0">
            {g.items.map((item) => {
              const active = isActive(pathname, item);
              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onClick={onNavigate}
                    aria-current={active ? "page" : undefined}
                    className={clsx(
                      "flex items-center justify-between gap-2 rounded-r-[3px] border-l-[3px] px-3 py-2 text-[14px] no-underline",
                      active
                        ? "border-ink bg-tint font-semibold text-ink"
                        : "border-transparent text-ink/80 hover:bg-tint hover:text-ink",
                    )}
                  >
                    <span>{item.label}</span>
                    {item.badge ? (
                      <span
                        className="min-w-[20px] rounded-full px-1.5 text-center font-mono text-[11px] font-semibold"
                        style={{ background: "var(--oxide)", color: "var(--card)" }}
                        aria-label={`${item.badge} new`}
                      >
                        {item.badge > 99 ? "99+" : item.badge}
                      </span>
                    ) : null}
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

export function SidebarNav({ groups }: { groups: NavGroup[] }) {
  return <Links groups={groups} />;
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
        className="inline-flex h-[38px] w-[38px] cursor-pointer items-center justify-center rounded-[3px] border border-rule bg-transparent text-ink lg:hidden"
      >
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
          <path d="M4 6h16M4 12h16M4 18h16" />
        </svg>
      </button>
      {/* Portalled to <body>: the sticky top bar has a backdrop blur, and a blurred ancestor
          becomes the containing block for `position: fixed` — the drawer would be clipped to the
          bar's 70 px height instead of covering the screen. */}
      {open && typeof document !== "undefined" ? createPortal(
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="Menu" id="mobile-drawer">
          <button
            type="button"
            aria-label="Close menu"
            className="absolute inset-0 cursor-default border-0 bg-black/40"
            onClick={() => setOpen(false)}
          />
          <div className="absolute inset-y-0 left-0 w-[82%] max-w-[300px] overflow-y-auto border-r border-rule bg-card p-4 shadow-lift">
            <div className="mb-4 flex items-center justify-between">
              <span className="display text-[15px]">{title}</span>
              <button
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Close menu"
                className="h-[34px] w-[34px] cursor-pointer rounded-[3px] border border-rule bg-transparent text-ash"
              >
                ✕
              </button>
            </div>
            <Links groups={groups} onNavigate={() => setOpen(false)} />
          </div>
        </div>,
        document.body,
      ) : null}
    </>
  );
}
