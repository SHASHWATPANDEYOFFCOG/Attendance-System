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
 * Next 16: route context `params` is a Promise.
 */
import { cookies } from "next/headers";

import { ACCESS_COOKIE, API_BASE } from "@/lib/api";

/** Only the API surface the frontend actually uses. Keeps the proxy from becoming a hole. */
const ALLOWED = [
  /^api\/attendance\/sessions(\/\d+\/(roster|records))?$/,
  /^api\/timetable\/today$/,
  /^api\/analytics\/(summary|trend|weekday)$/,
  /^api\/reports\/(defaulters|attendance|options|daily-absentees|export)$/,
  /^api\/sessions\/\d+\/attendance$/,
  /^api\/me(\/(attendance|summary))?$/,
];

async function forward(request: Request, path: string[], method: string) {
  const target = path.join("/");
  if (!ALLOWED.some((re) => re.test(target))) {
    return Response.json({ error: `path not proxied: ${target}` }, { status: 404 });
  }

  const store = await cookies();
  const token = store.get(ACCESS_COOKIE)?.value;
  if (!token) return Response.json({ error: "not authenticated" }, { status: 401 });

  const url = new URL(request.url);
  const upstream = await fetch(`${API_BASE}/${target}${url.search}`, {
    method,
    headers: {
      Authorization: `Bearer ${token}`,
      ...(method === "GET" ? {} : { "Content-Type": "application/json" }),
    },
    body: method === "GET" ? undefined : await request.text(),
    cache: "no-store",
  });

  // Bytes, not text: XLSX and PDF are binary and `.text()` would corrupt them.
  const body = await upstream.arrayBuffer();
  const headers: Record<string, string> = {
    "Content-Type": upstream.headers.get("content-type") ?? "application/json",
  };
  // Carry the download filename through, or the browser saves everything as "export".
  const disposition = upstream.headers.get("content-disposition");
  if (disposition) headers["Content-Disposition"] = disposition;

  return new Response(body, { status: upstream.status, headers });
}

export async function GET(request: Request, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(request, (await ctx.params).path, "GET");
}
export async function POST(request: Request, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(request, (await ctx.params).path, "POST");
}
export async function PATCH(request: Request, ctx: { params: Promise<{ path: string[] }> }) {
  return forward(request, (await ctx.params).path, "PATCH");
}
