/**
 * Next 16 renamed `middleware.ts` to `proxy.ts`. Same lifecycle, clearer name.
 *
 * This is an OPTIMISTIC check only — it redirects a request with no session cookie to /login so
 * the user does not watch a dashboard skeleton render before being bounced. It is NOT the
 * authorization boundary: a forged cookie gets past this and is then rejected by the FastAPI
 * backend, which is where roles, department scope and ownership are actually enforced.
 */
import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

const ACCESS_COOKIE = "att_access";
const PUBLIC_PATHS = ["/login"];

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;

  if (PUBLIC_PATHS.some((p) => pathname.startsWith(p))) {
    return NextResponse.next();
  }

  const signedIn = Boolean(request.cookies.get(ACCESS_COOKIE)?.value);
  if (!signedIn) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("next", pathname);
    return NextResponse.redirect(url);
  }
  return NextResponse.next();
}

export const config = {
  // Everything except Next internals, the auth route handlers, and static assets.
  matcher: ["/((?!api/auth|_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|webp)$).*)"],
};
