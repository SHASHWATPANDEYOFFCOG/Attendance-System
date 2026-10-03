/**
 * Sign in, and put the tokens in httpOnly cookies.
 *
 * The browser never receives the JWT in a readable form: the backend returns it to this Route
 * Handler, which stores it httpOnly + sameSite=lax. Client JS cannot read it, so an XSS cannot
 * steal a session. Every later call attaches it server-side in lib/api.ts.
 */
import { NextResponse } from "next/server";

import { ACCESS_COOKIE, API_BASE, REFRESH_COOKIE } from "@/lib/api";

export async function POST(request: Request) {
  let payload: { username?: string; password?: string };
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ error: "malformed request body" }, { status: 400 });
  }

  const { username, password } = payload;
  if (!username || !password) {
    return NextResponse.json({ error: "username and password are required" }, { status: 400 });
  }

  const upstream = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
    cache: "no-store",
  });

  if (!upstream.ok) {
    // Deliberately not forwarding the upstream message verbatim: "no such user" versus
    // "wrong password" is a username-enumeration oracle.
    return NextResponse.json({ error: "invalid username or password" }, { status: 401 });
  }

  const body = await upstream.json();
  const res = NextResponse.json({
    role: body.role,
    display_name: body.display_name,
  });

  const secure = process.env.NODE_ENV === "production";
  res.cookies.set(ACCESS_COOKIE, body.access_token, {
    httpOnly: true,
    sameSite: "lax",
    secure,
    path: "/",
    maxAge: 60 * 30,
  });
  if (body.refresh_token) {
    res.cookies.set(REFRESH_COOKIE, body.refresh_token, {
      httpOnly: true,
      sameSite: "lax",
      secure,
      path: "/",
      maxAge: 60 * 60 * 24 * 7,
    });
  }
  return res;
}
