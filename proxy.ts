/**
 * Next 16 renamed `middleware.ts` to `proxy.ts`. Same lifecycle, clearer name.
 *
 * Two jobs, neither of them authorization:
 *
 * 1. **Optimistic redirect.** A request with no session goes to /login, so nobody watches a
 *    dashboard skeleton render before being bounced. A forged cookie gets past this and is then
 *    rejected by the FastAPI backend, which is where roles, scope and ownership are enforced.
 * 2. **Silent refresh.** The access token lives 30 minutes; the refresh token 7 days. When the
 *    access cookie has expired but a refresh cookie remains, this swaps it for a new access
 *    token *before* the page renders — Server Components cannot set cookies themselves — and
 *    hands the fresh token to this same request so the render already sees it.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const ACCESS_COOKIE = "att_access";
const REFRESH_COOKIE = "att_refresh";
const API_BASE = process.env.ATTENDANCE_API_BASE ?? "http://127.0.0.1:8079";

const PUBLIC_PATHS = [
  "/login",
  "/authority/login",
  "/authority/register",
  "/signup",
  "/verify-email",
  "/forgot-password",
  "/reset-password",
  "/privacy",
  "/guide",
  "/api/public",
  "/manifest.webmanifest",
  "/sw.js",
  "/offline.html",
  "/icons",
];

async function refreshAccess(refresh: string, forwardedFor: string | null): Promise<string | null> {
  try {
    const res = await fetch(`${API_BASE}/api/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Forwarded-For": forwardedFor ?? "" },
      body: JSON.stringify({ refresh_token: refresh }),
      cache: "no-store",
    });
    if (!res.ok) return null;
    const body = await res.json();
    return typeof body.access_token === "string" ? body.access_token : null;
  } catch {
    return null;
  }
}

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const isPublic = PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));

  let access = request.cookies.get(ACCESS_COOKIE)?.value;
  const refresh = request.cookies.get(REFRESH_COOKIE)?.value;
  let refreshed: string | null = null;

  if (!access && refresh) {
    refreshed = await refreshAccess(refresh, request.headers.get("x-forwarded-for"));
    if (refreshed) access = refreshed;
  }

  if (!access && !isPublic) {
    if (pathname.startsWith("/api/")) {
      return NextResponse.json({ detail: "not authenticated" }, { status: 401 });
    }
    const url = request.nextUrl.clone();
    // Staff pages send a signed-out visitor to the authority sign in, everything else to the student one.
    const staffArea = ["/dashboard", "/staff", "/mark", "/reports", "/present", "/authority"]
      .some((p) => pathname === p || pathname.startsWith(`${p}/`));
    url.pathname = staffArea ? "/authority/login" : "/login";
    url.search = "";
    url.searchParams.set("next", pathname + request.nextUrl.search);
    const res = NextResponse.redirect(url);
    if (refresh) res.cookies.delete(REFRESH_COOKIE);          // it was rejected; drop it
    return res;
  }

  if (!refreshed) return NextResponse.next();

  // Make the new token visible to *this* request's render, then persist it for the next ones.
  request.cookies.set(ACCESS_COOKIE, refreshed);
  const res = NextResponse.next({ request: { headers: new Headers(request.headers) } });
  res.cookies.set(ACCESS_COOKIE, refreshed, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production" && process.env.ATTENDANCE_INSECURE_COOKIES !== "1",
    path: "/",
    maxAge: 60 * 30,
  });
  return res;
}

export const config = {
  // Everything except Next internals, the auth route handlers, and static assets.
  matcher: ["/((?!api/auth|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|webp|ico)$).*)"],
};
