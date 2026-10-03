/**
 * Session cookies. Both tokens are httpOnly + SameSite=Lax, Secure in production: client JS
 * can never read them, so an XSS cannot steal a session.
 */
import type { NextResponse } from "next/server";

import { ACCESS_COOKIE, REFRESH_COOKIE } from "@/lib/api";

export const ACCESS_MAX_AGE = 60 * 30;
export const REFRESH_MAX_AGE = 60 * 60 * 24 * 7;

const secure = () => process.env.NODE_ENV === "production" && process.env.ATTENDANCE_INSECURE_COOKIES !== "1";

export function setSessionCookies(
  res: NextResponse,
  tokens: { access_token: string; refresh_token?: string | null },
) {
  res.cookies.set(ACCESS_COOKIE, tokens.access_token, {
    httpOnly: true,
    sameSite: "lax",
    secure: secure(),
    path: "/",
    maxAge: ACCESS_MAX_AGE,
  });
  if (tokens.refresh_token) {
    res.cookies.set(REFRESH_COOKIE, tokens.refresh_token, {
      httpOnly: true,
      sameSite: "lax",
      secure: secure(),
      path: "/",
      maxAge: REFRESH_MAX_AGE,
    });
  }
}

/** Where each role lands after signing in. */
export function homeFor(role?: string | null): string {
  if (role === "student") return "/student";
  if (role === "parent") return "/my-attendance";
  return "/dashboard";
}
