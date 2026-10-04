import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

import { type APIRequestContext, expect, type Page, request } from "@playwright/test";

import { ADMIN, COLLEGE_TZ, E2E_DIR_PARTS, WEB_URL } from "./config.mjs";

const OUTBOX = path.resolve(__dirname, "..", "..", ...E2E_DIR_PARTS, "outbox");

export const B = "/api/backend/api";

/** A short unique suffix so every test (and every browser project) gets its own people. */
export function uid(): string {
  return `${Date.now().toString(36).slice(-5)}${Math.floor(Math.random() * 1296).toString(36)}`.toUpperCase();
}

/** An API client signed in through the same cookie proxy the browser uses. */
export async function apiAs(username: string, password: string): Promise<APIRequestContext> {
  const ctx = await request.newContext({ baseURL: WEB_URL, extraHTTPHeaders: { Origin: WEB_URL } });
  const r = await ctx.post("/api/auth/login", { data: { username, password } });
  expect(r.ok(), `login ${username}: ${r.status()} ${await r.text()}`).toBeTruthy();
  return ctx;
}

export const adminApi = () => apiAs(ADMIN.username, ADMIN.password);

export async function json<T = Record<string, unknown>>(res: Promise<import("@playwright/test").APIResponse>): Promise<T> {
  const r = await res;
  expect(r.ok(), `${r.url()} → ${r.status()} ${await r.text()}`).toBeTruthy();
  return (await r.json()) as T;
}

/** Decoded text body of the newest email to `to` that contains `contains` (waits for the outbox). */
export async function latestMail(to: string, contains = "", timeoutMs = 30_000): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    let files: string[] = [];
    try {
      files = readdirSync(OUTBOX).filter((f) => f.endsWith(".eml"));
    } catch {
      /* outbox not created yet */
    }
    const newest = files
      .map((f) => path.join(OUTBOX, f))
      .sort((a, b) => statSync(b).mtimeMs - statSync(a).mtimeMs);
    for (const file of newest) {
      const raw = readFileSync(file, "utf8");
      if (!new RegExp(`^To: .*${to.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`, "mi").test(raw)) continue;
      const body = decodeMail(raw);
      if (body.includes(contains)) return body;
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  throw new Error(`no email to ${to} containing "${contains}" within ${timeoutMs} ms`);
}

/** Enough MIME decoding for our own mails: the text/plain part, quoted-printable or base64. */
function decodeMail(raw: string): string {
  const parts = raw.split(/\r?\n--[^\r\n]+\r?\n/);
  const plain = parts.find((p) => /Content-Type: text\/plain/i.test(p)) ?? raw;
  const [head, ...rest] = plain.split(/\r?\n\r?\n/);
  const body = rest.join("\n\n");
  if (/Content-Transfer-Encoding: base64/i.test(head)) return Buffer.from(body.replace(/\s+/g, ""), "base64").toString("utf8");
  if (/Content-Transfer-Encoding: quoted-printable/i.test(head)) {
    return body.replace(/=\r?\n/g, "").replace(/=([0-9A-F]{2})/gi, (_, h) => String.fromCharCode(parseInt(h, 16)));
  }
  return body;
}

export type Structure = { dept: number; batch: number; section: number; deptCode: string };

/** A branch, batch and class group of its own, so tests never collide. */
export async function makeClass(admin: APIRequestContext, tag: string): Promise<Structure> {
  const deptCode = `E${tag}`.slice(0, 10);
  const dept = (await json<{ id: number }>(admin.post(`${B}/departments`, { data: { code: deptCode, name: `E2E ${tag}` } }))).id;
  // Batches are unique by years and the API allows 1990-2100: try random years until one is free.
  let batch = 0;
  for (let attempt = 0; attempt < 20 && !batch; attempt++) {
    const year = 1990 + Math.floor(Math.random() * 105);
    const r = await admin.post(`${B}/batches`, { data: { start_year: year, end_year: year + 4 } });
    if (r.ok()) batch = ((await r.json()) as { id: number }).id;
    else expect([409, 422], await r.text()).toContain(r.status());
  }
  expect(batch, "could not create a batch").toBeGreaterThan(0);
  const section = (await json<{ id: number }>(admin.post(`${B}/sections`, {
    data: { department_id: dept, batch_id: batch, name: "A", year: 1, semester: 1 },
  }))).id;
  return { dept, batch, section, deptCode };
}

/** Wall-clock "now" in the college's timezone, as the backend's timetable sees it. */
export function collegeNow(): { weekday: number; minute: number } {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: COLLEGE_TZ, weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(new Date());
  const get = (t: string) => parts.find((p) => p.type === t)!.value;
  const weekday = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"].indexOf(get("weekday"));
  return { weekday, minute: Number(get("hour")) * 60 + Number(get("minute")) };
}

const hhmm = (m: number) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;

/** A timetabled lecture for `s` that started a minute ago, opened and live. Returns the session id. */
export async function liveLecture(admin: APIRequestContext, s: Structure, tag: string): Promise<number> {
  // The timetable belongs to a term; make one covering today if the database has none.
  const terms = await json<{ is_active: boolean }[]>(admin.get(`${B}/terms`));
  if (!terms.some((t) => t.is_active)) {
    const day = (offset: number) => new Date(Date.now() + offset * 86_400_000).toISOString().slice(0, 10);
    await json(admin.post(`${B}/terms`, { data: { name: "E2E term", start_date: day(-30), end_date: day(120), is_active: true } }));
  }
  const subject = (await json<{ id: number }>(admin.post(`${B}/subjects`, {
    data: { code: `S${tag}`.slice(0, 12), name: `Subject ${tag}`, department_id: s.dept },
  }))).id;
  const teacher = (await json<{ id: number }>(admin.post(`${B}/admin/users`, {
    data: { full_name: `Teacher ${tag}`, email: `teacher.${tag.toLowerCase()}@e2e.test`, role: "faculty", department_id: s.dept },
  }))).id;
  const { weekday, minute } = collegeNow();
  const start = Math.max(0, minute - 1);
  const end = Math.min(24 * 60 - 1, start + 50);
  const slot = (await json<{ id: number }>(admin.post(`${B}/timetable`, {
    data: { section_id: s.section, subject_id: subject, faculty_id: teacher, day_of_week: weekday,
            start_time: hhmm(start), end_time: hhmm(end), room: `R-${tag}` },
  }))).id;
  const session = await json<{ id: number; state: string }>(admin.post(`${B}/sessions/open`, { data: { slot_id: slot, start: true } }));
  expect(session.state).toBe("active");
  return session.id;
}

/** An approved student added by staff, with a password set through the emailed invite. */
export async function approvedStudent(admin: APIRequestContext, s: Structure, tag: string) {
  const email = `student.${tag.toLowerCase()}@e2e.test`;
  const password = "Stud-Pass-123";
  await json(admin.post(`${B}/students`, {
    data: { full_name: `Student ${tag}`, email, mobile: `9${String(parseInt(tag, 36)).padStart(9, "0").slice(-9)}`,
            roll_number: `R${tag}`, enrollment_no: `EN${tag}`, section_id: s.section },
  }));
  const token = /token=([\w-]+)/.exec(await latestMail(email, "token="))![1];
  const pub = await request.newContext({ baseURL: WEB_URL, extraHTTPHeaders: { Origin: WEB_URL } });
  await json(pub.post("/api/public/auth/reset-password", { data: { token, password } }));
  await pub.dispose();
  return { email, password };
}

export async function signIn(page: Page, username: string, password: string) {
  await page.goto("/login");
  await page.waitForLoadState("networkidle");
  await page.getByLabel("Username, email or roll number").fill(username);
  await page.getByLabel("Password", { exact: true }).fill(password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL((u) => !u.pathname.startsWith("/login"));
}

/** True when nothing on the page is wider than the viewport (no sideways scrolling on a phone). */
export async function expectNoHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  expect(overflow, `page ${page.url()} scrolls sideways by ${overflow}px`).toBeLessThanOrEqual(0);
}
