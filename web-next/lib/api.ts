/**
 * Server-side client for the FastAPI backend.
 *
 * The access token lives in an httpOnly cookie and is attached here, on the server. It is
 * never serialised into a Server Component's payload and never reachable from client JS, so
 * an XSS cannot exfiltrate it.
 *
 * Next 16: `cookies()` is async-only — synchronous access was removed in this major.
 */
import { cookies } from "next/headers";

export const API_BASE = process.env.ATTENDANCE_API_BASE ?? "http://127.0.0.1:8079";

export const ACCESS_COOKIE = "att_access";
export const REFRESH_COOKIE = "att_refresh";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function authHeader(): Promise<Record<string, string>> {
  const store = await cookies();
  const token = store.get(ACCESS_COOKIE)?.value;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** GET a JSON resource as the signed-in user. Throws ApiError on a non-2xx. */
export async function apiGet<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { ...(init?.headers ?? {}), ...(await authHeader()) },
    // Attendance is live operational data; a cached roster would show a teacher
    // yesterday's marks and let them "confirm" a register that has already moved on.
    cache: "no-store",
  });

  if (!res.ok) {
    throw new ApiError(res.status, await describe(res));
  }
  return (await res.json()) as T;
}

export async function apiSend<T>(
  path: string,
  method: "POST" | "PATCH" | "DELETE" | "PUT",
  body?: unknown,
): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: {
      "Content-Type": "application/json",
      ...(await authHeader()),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    cache: "no-store",
  });
  if (!res.ok) throw new ApiError(res.status, await describe(res));
  return (await res.json()) as T;
}

async function describe(res: Response): Promise<string> {
  try {
    const body = await res.json();
    const detail = body?.detail ?? body?.message;
    if (typeof detail === "string") return detail;
    if (detail && typeof detail === "object") return detail.message ?? JSON.stringify(detail);
    return `${res.status} ${res.statusText}`;
  } catch {
    return `${res.status} ${res.statusText}`;
  }
}

/**
 * Fetch several resources at once, tolerating individual failures.
 *
 * A dashboard is a composition of independent panels: if the defaulter query 403s for this
 * role, the trend chart should still render. Returning `null` per slot keeps one failing
 * panel from blanking the whole page.
 */
export async function apiGetAll<T extends Record<string, string>>(
  paths: T,
): Promise<{ [K in keyof T]: unknown | null }> {
  const entries = Object.entries(paths) as [keyof T, string][];
  const results = await Promise.all(
    entries.map(async ([key, path]) => {
      try {
        return [key, await apiGet(path)] as const;
      } catch {
        return [key, null] as const;
      }
    }),
  );
  return Object.fromEntries(results) as { [K in keyof T]: unknown | null };
}

export type Me = {
  id: number;
  username: string;
  display_name: string;
  role: "super_admin" | "admin" | "faculty" | "student" | "parent";
  roll_number: string | null;
  email: string | null;
  phone: string | null;
  consent_given: boolean;
  has_biometrics: boolean;
  department_id: number | null;
  student_status: "pending" | "approved" | "rejected" | "revoked" | null;
  rejection_reason: string | null;
  email_verified: boolean;
};

export const STAFF_ROLES = ["faculty", "admin", "super_admin"] as const;
export const isStaffRole = (role?: string | null) =>
  (STAFF_ROLES as readonly string[]).includes(role ?? "");
export const isAdminRole = (role?: string | null) => role === "admin" || role === "super_admin";

/** The signed-in user, or null when the session is missing or rejected. */
export async function getMe(): Promise<Me | null> {
  try {
    return await apiGet<Me>("/api/me");
  } catch {
    return null;
  }
}

export async function isSignedIn(): Promise<boolean> {
  const store = await cookies();
  return Boolean(store.get(ACCESS_COOKIE)?.value);
}
