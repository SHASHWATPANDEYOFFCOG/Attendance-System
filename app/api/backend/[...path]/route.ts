/**
 * Backend-for-frontend proxy.
 *
 * Client components cannot read the httpOnly session cookie — that is the point of it. This
 * route forwards their calls to FastAPI with the token attached server-side, so the browser
 * gets the data without ever holding the credential.
 *
 * It grants no authority of its own: it attaches *this user's* token and nothing else, so the
 * backend still enforces role, department scope and ownership on every request. It is a
 * transport, not a trust boundary.
 *
 * CSRF: the session cookie is SameSite=Lax, and every state-changing call must additionally
 * carry an Origin (or Referer) from this same site. A form on another site can neither read
 * the cookie nor pass that check.
 *
 * Next 16: route context `params` is a Promise.
 */
import { cookies } from "next/headers";

import { ACCESS_COOKIE, API_BASE } from "@/lib/api";

/** Only the API surface the frontend uses. Keeps the proxy from becoming a hole. */
const ALLOWED = [
  /^api\/attendance\/(sessions(\/\d+\/(roster|records|self-mark))?|qr|\d+)$/,
  /^api\/timetable\/today$/,
  /^api\/analytics\/(summary|trend|weekday|classes)$/,
  /^api\/reports\/[a-z-]+(\/\d+)?$/,
  /^api\/sessions(\/\d+(\/[a-z-]+(\/\d+(\/[a-z]+)?)?)?)?$/,
  /^api\/sessions\/(live|open)$/,
  /^api\/live\/stream$/,
  /^api\/me(\/[a-z-]+(\/[a-z-]+)?(\/\d+)?)?$/,
  /^api\/(departments|programs|batches|sections|subjects|rooms|holidays|terms|assignments|timetable)(\/\d+)?$/,
  /^api\/students(\/(import(\/template)?|\d+(\/[a-z-]+)?))?$/,
  /^api\/(edit-requests|face-enrollments|reenroll-requests)(\/\d+(\/[a-z]+)?)?$/,
  /^api\/(leaves|issues|conversations|announcements|notifications)(\/[a-z-]+)?(\/\d+)?(\/[a-z-]+)?$/,
  /^api\/messages\/broadcast$/,
  /^api\/review-queue(\/\d+\/[a-z]+)?$/,
  /^api\/cameras(\/\d+(\/[a-z]+)?)?$/,
  /^api\/files\/\d+$/,
  /^api\/admin\/(users(\/\d+(\/unlock)?)?|settings|retention|lock-stale-sessions|audit)$/,
  /^api\/approvals\/summary$/,
  /^api\/staff-registrations(\/\d+\/decide)?$/,
  /^api\/audit$/,
  /^api\/system\/status$/,
  /^api\/users(\/\d+\/biometrics)?$/,
  /^api\/dashboard$/,
];

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

async function forward(request: Request, path: string[], method: string) {
  const target = path.join("/");
  if (!ALLOWED.some((re) => re.test(target))) {
    return Response.json({ detail: `path not proxied: ${target}` }, { status: 404 });
  }
  if (method !== "GET" && !sameOrigin(request)) {
    return Response.json({ detail: "cross-site request refused" }, { status: 403 });
  }

  const store = await cookies();
  const token = store.get(ACCESS_COOKIE)?.value;
  if (!token) return Response.json({ detail: "not authenticated" }, { status: 401 });

  const url = new URL(request.url);
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  // Raw bytes plus the caller's own Content-Type, so multipart uploads (photos, attachments,
  // selfie frames) pass through intact — JSON is just one of the bodies this carries.
  const contentType = request.headers.get("content-type");
  if (method !== "GET" && contentType) headers["Content-Type"] = contentType;
  const fwd = request.headers.get("x-forwarded-for");
  if (fwd) headers["X-Forwarded-For"] = fwd;

  let upstream: Response;
  try {
    upstream = await fetch(`${API_BASE}/${target}${url.search}`, {
      method,
      headers,
      body: method === "GET" || method === "DELETE" ? undefined : await request.arrayBuffer(),
      cache: "no-store",
    });
  } catch {
    return Response.json(
      { detail: "The attendance server is unreachable. Try again in a moment." },
      { status: 502 },
    );
  }

  const type = upstream.headers.get("content-type") ?? "application/json";
  // Server-sent events: stream through untouched, never buffer.
  if (type.startsWith("text/event-stream")) {
    return new Response(upstream.body, {
      status: upstream.status,
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        "X-Accel-Buffering": "no",
      },
    });
  }

  // Bytes, not text: XLSX, PDF and JPEG are binary and `.text()` would corrupt them.
  const body = await upstream.arrayBuffer();
  const out: Record<string, string> = { "Content-Type": type };
  // Carry the download filename through, or the browser saves everything as "export".
  const disposition = upstream.headers.get("content-disposition");
  if (disposition) out["Content-Disposition"] = disposition;
  const retry = upstream.headers.get("retry-after");
  if (retry) out["Retry-After"] = retry;
  return new Response(body, { status: upstream.status, headers: out });
}

type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(request: Request, ctx: Ctx) {
  return forward(request, (await ctx.params).path, "GET");
}
export async function POST(request: Request, ctx: Ctx) {
  return forward(request, (await ctx.params).path, "POST");
}
export async function PATCH(request: Request, ctx: Ctx) {
  return forward(request, (await ctx.params).path, "PATCH");
}
export async function PUT(request: Request, ctx: Ctx) {
  return forward(request, (await ctx.params).path, "PUT");
}
export async function DELETE(request: Request, ctx: Ctx) {
  return forward(request, (await ctx.params).path, "DELETE");
}
