/**
 * Unauthenticated backend calls: sign-up, email verification, password reset, and the
 * dropdown options the sign-up form needs. No token is attached because none exists yet; the
 * backend rate-limits every one of these by client IP.
 */
const API_BASE = process.env.ATTENDANCE_API_BASE ?? "http://127.0.0.1:8079";

const ALLOWED = [
  /^auth\/(signup|verify-email|resend-otp|forgot-password|reset-password)$/,
  /^public\/academic-options$/,
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
    return Response.json({ detail: "not found" }, { status: 404 });
  }
  if (method !== "GET" && !sameOrigin(request)) {
    return Response.json({ detail: "cross-site request refused" }, { status: 403 });
  }
  const headers: Record<string, string> = {
    "X-Forwarded-For": request.headers.get("x-forwarded-for") ?? "",
  };
  const type = request.headers.get("content-type");
  if (method !== "GET" && type) headers["Content-Type"] = type;
  try {
    const upstream = await fetch(`${API_BASE}/api/${target}${new URL(request.url).search}`, {
      method,
      headers,
      body: method === "GET" ? undefined : await request.arrayBuffer(),
      cache: "no-store",
    });
    return new Response(await upstream.arrayBuffer(), {
      status: upstream.status,
      headers: { "Content-Type": upstream.headers.get("content-type") ?? "application/json" },
    });
  } catch {
    return Response.json({ detail: "The attendance server is unreachable." }, { status: 502 });
  }
}

type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(request: Request, ctx: Ctx) {
  return forward(request, (await ctx.params).path, "GET");
}
export async function POST(request: Request, ctx: Ctx) {
  return forward(request, (await ctx.params).path, "POST");
}
