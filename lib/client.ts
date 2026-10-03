/**
 * Browser-side calls to the backend, through the same-origin proxy at /api/backend.
 *
 * The browser never holds the session token: the proxy attaches it. Every failure is turned
 * into an `ApiFailure` carrying the backend's own human-readable message, so forms can show
 * "Roll number CSE-014 is already registered in CSE 2023-2027" rather than "Error 409".
 */
export class ApiFailure extends Error {
  constructor(
    readonly status: number,
    message: string,
    readonly detail?: Record<string, unknown>,
  ) {
    super(message);
    this.name = "ApiFailure";
  }
}

async function failure(res: Response): Promise<ApiFailure> {
  let message = `${res.status} ${res.statusText}`;
  let detail: Record<string, unknown> | undefined;
  try {
    const body = await res.json();
    const d = body?.detail ?? body?.error ?? body?.message;
    if (typeof d === "string") message = d;
    else if (Array.isArray(d)) {
      // FastAPI validation errors: [{loc, msg}], surfaced as "field: message".
      message = d
        .map((e: { loc?: unknown[]; msg?: string }) =>
          [Array.isArray(e.loc) ? e.loc.filter((p) => p !== "body").join(".") : "", e.msg]
            .filter(Boolean)
            .join(": "),
        )
        .join("; ");
    } else if (d && typeof d === "object") {
      detail = d as Record<string, unknown>;
      message = String((d as { message?: unknown }).message ?? JSON.stringify(d));
    }
  } catch {
    /* non-JSON error body */
  }
  if (res.status === 401) message = "Your session has expired. Sign in again.";
  if (res.status === 502 && !message) message = "The server is unreachable.";
  return new ApiFailure(res.status, message, detail);
}

const base = (path: string) => `/api/backend${path.startsWith("/") ? path : `/${path}`}`;

async function send<T>(path: string, init: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(base(path), { ...init, cache: "no-store", credentials: "same-origin" });
  } catch {
    throw new ApiFailure(0, "No connection. Check your network and try again.");
  }
  if (!res.ok) throw await failure(res);
  if (res.status === 204) return undefined as T;
  const type = res.headers.get("content-type") ?? "";
  return (type.includes("application/json") ? res.json() : res.blob()) as Promise<T>;
}

export const api = {
  get: <T = unknown>(path: string) => send<T>(path, { method: "GET" }),
  post: <T = unknown>(path: string, body?: unknown) =>
    send<T>(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    }),
  patch: <T = unknown>(path: string, body?: unknown) =>
    send<T>(path, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body ?? {}),
    }),
  put: <T = unknown>(path: string, body?: unknown) =>
    send<T>(path, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body ?? {}),
    }),
  del: <T = unknown>(path: string) => send<T>(path, { method: "DELETE" }),
  /** multipart/form-data — the browser sets the boundary, so no Content-Type here. */
  upload: <T = unknown>(path: string, form: FormData, method: "POST" | "PATCH" = "POST") =>
    send<T>(path, { method, body: form }),
};

/** Save a Blob as a download (exports). */
export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Fetch an export through the proxy and save it with the server-provided filename. */
export async function download(path: string, fallbackName: string) {
  const res = await fetch(base(path), { cache: "no-store" });
  if (!res.ok) throw await failure(res);
  const disposition = res.headers.get("content-disposition") ?? "";
  const match = /filename="?([^";]+)"?/i.exec(disposition);
  saveBlob(await res.blob(), match?.[1] ?? fallbackName);
}
