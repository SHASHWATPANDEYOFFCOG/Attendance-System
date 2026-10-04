/**
 * Sign in, and put the tokens in httpOnly cookies.
 *
 * The browser never receives the JWT in a readable form: the backend returns it to this Route
 * Handler, which stores it httpOnly + sameSite=lax. Client JS cannot read it, so an XSS cannot
 * steal a session. Every later call attaches it server-side in lib/api.ts.
 */
import { NextResponse } from "next/server";

import { API_BASE } from "@/lib/api";
import { homeFor, setSessionCookies } from "@/lib/session";

const STAFF = new Set(["faculty", "admin", "super_admin"]);

export async function POST(request: Request) {
  let payload: { username?: string; password?: string; portal?: string };
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ error: "malformed request body" }, { status: 400 });
  }

  const { username, password, portal } = payload;
  if (!username || !password) {
    return NextResponse.json({ error: "Enter your username, email or roll number and password." }, { status: 400 });
  }

  let upstream: Response;
  try {
    upstream = await fetch(`${API_BASE}/api/auth/login`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Forwarded-For": request.headers.get("x-forwarded-for") ?? "",
      },
      body: JSON.stringify({ username, password }),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ error: "The attendance server is unreachable." }, { status: 502 });
  }

  if (!upstream.ok) {
    // Wrong user and wrong password stay indistinguishable ("no such user" vs "wrong password"
    // is a username-enumeration oracle). Lockout, rate limiting and an unverified email are
    // about an account the person has already proven they own, so those are passed through.
    const body = await upstream.json().catch(() => ({}));
    const detail = body?.detail;
    if (upstream.status === 429) {
      return NextResponse.json({ error: typeof detail === "string" ? detail : "Too many attempts." }, {
        status: 429,
      });
    }
    if (upstream.status === 403 && detail && typeof detail === "object") {
      return NextResponse.json({ error: detail.message, code: detail.code, email: detail.email }, {
        status: 403,
      });
    }
    return NextResponse.json({ error: "Invalid username or password." }, { status: 401 });
  }

  const body = await upstream.json();
  // Two doors: staff sign in at /authority/login, students and guardians at /login. An account
  // at the wrong door gets no cookies, just directions. (The tokens just issued are dropped
  // unused; they are short-lived and never reach the browser.)
  const staff = STAFF.has(body.role);
  if ((portal === "authority" && !staff) || (portal === "student" && staff)) {
    return NextResponse.json({
      code: "wrong_portal",
      login: staff ? "/authority/login" : "/login",
      error: staff
        ? "This is the student sign in. Teachers, HODs and admins use the authority sign in."
        : "This is the authority sign in, for teachers and administrators. Students use the student sign in.",
    }, { status: 403 });
  }
  const res = NextResponse.json({
    role: body.role,
    display_name: body.display_name,
    student_status: body.student_status ?? null,
    home: homeFor(body.role),
  });
  setSessionCookies(res, body);
  return res;
}
