/**
 * Pair this browser as a registered tablet.
 *
 * The backend answers a valid pairing code with a long-lived device token. It must never reach
 * page scripts (an XSS could otherwise copy a tablet's identity), so this handler stores it in an
 * httpOnly cookie and returns only the tablet's public details. DELETE forgets the pairing on
 * this device.
 */
import { cookies } from "next/headers";
import { NextResponse } from "next/server";

import { ACCESS_COOKIE, API_BASE } from "@/lib/api";
import { DEVICE_COOKIE, DEVICE_MAX_AGE } from "@/lib/device";

function sameOrigin(request: Request): boolean {
  const host = request.headers.get("x-forwarded-host") ?? request.headers.get("host");
  const origin = request.headers.get("origin") ?? request.headers.get("referer");
  if (!host || !origin) return false;
  try {
    return new URL(origin).host === host;
  } catch {
    return false;
  }
}

const secure = process.env.NODE_ENV === "production" && process.env.ATTENDANCE_INSECURE_COOKIES !== "1";

export async function POST(request: Request) {
  if (!sameOrigin(request)) return NextResponse.json({ detail: "cross-site request refused" }, { status: 403 });
  const store = await cookies();
  const token = store.get(ACCESS_COOKIE)?.value;
  if (!token) return NextResponse.json({ detail: "not authenticated" }, { status: 401 });
  let body: { pairing_code?: string };
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ detail: "malformed request" }, { status: 400 });
  }
  let upstream: Response;
  try {
    upstream = await fetch(`${API_BASE}/api/tablets/pair`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
        "X-Forwarded-For": request.headers.get("x-forwarded-for") ?? "",
      },
      body: JSON.stringify({
        pairing_code: body.pairing_code ?? "",
        device_info: (request.headers.get("user-agent") ?? "").slice(0, 200),
      }),
      cache: "no-store",
    });
  } catch {
    return NextResponse.json({ detail: "The attendance server is unreachable." }, { status: 502 });
  }
  const data = await upstream.json().catch(() => ({}));
  if (!upstream.ok) return NextResponse.json(data, { status: upstream.status });
  const res = NextResponse.json({ tablet: data.tablet });
  res.cookies.set(DEVICE_COOKIE, data.device_token, {
    httpOnly: true, sameSite: "lax", secure, path: "/", maxAge: DEVICE_MAX_AGE,
  });
  return res;
}

export async function DELETE(request: Request) {
  if (!sameOrigin(request)) return NextResponse.json({ detail: "cross-site request refused" }, { status: 403 });
  const res = NextResponse.json({ forgotten: true });
  res.cookies.delete(DEVICE_COOKIE);
  return res;
}
