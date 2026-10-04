/**
 * Every main page renders without errors and without sideways scrolling, in each browser and
 * at phone width. Also: the server — not the menu — keeps students out of staff pages.
 */
import { expect, test } from "@playwright/test";

import { ADMIN } from "./config.mjs";
import { adminApi, approvedStudent, expectNoHorizontalScroll, makeClass, signIn, uid } from "./helpers";

const PUBLIC = ["/login", "/signup", "/forgot-password", "/privacy", "/guide"];
const STAFF = ["/dashboard", "/staff/sessions", "/mark", "/staff/reports", "/staff/students", "/staff/approvals",
  "/staff/leaves", "/staff/issues", "/staff/messages", "/staff/setup", "/staff/cameras", "/staff/admin/settings"];
const STUDENT = ["/student", "/student/mark", "/student/history", "/student/leaves", "/student/issues",
  "/student/messages", "/student/profile", "/student/face"];

function watchErrors(page: import("@playwright/test").Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => {
    // WebKit reports a same-origin request cut off by the next navigation (a Next.js prefetch,
    // the service-worker fetch) as "… due to access control checks". Nothing failed.
    if (/due to access control checks/.test(e.message)) return;
    errors.push(e.message);
  });
  return errors;
}

test("public pages", async ({ page }) => {
  const errors = watchErrors(page);
  for (const path of PUBLIC) {
    const res = await page.goto(path);
    expect(res?.status(), path).toBeLessThan(400);
    await expect(page.locator("h1").first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expectNoHorizontalScroll(page);
  }
  expect(errors).toEqual([]);
});

test("staff pages", async ({ page }) => {
  const errors = watchErrors(page);
  await signIn(page, ADMIN.username, ADMIN.password, "authority");
  for (const path of STAFF) {
    const res = await page.goto(path);
    expect(res?.status(), path).toBeLessThan(400);
    await expect(page.locator("h1").first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expectNoHorizontalScroll(page);
  }
  expect(errors).toEqual([]);
});

test("student pages, and staff pages stay closed to students", async ({ page }) => {
  const tag = uid();
  const admin = await adminApi();
  const student = await approvedStudent(admin, await makeClass(admin, tag), tag);
  const errors = watchErrors(page);
  await signIn(page, student.email, student.password);
  for (const path of STUDENT) {
    const res = await page.goto(path);
    expect(res?.status(), path).toBeLessThan(400);
    await expect(page.locator("h1").first()).toBeVisible();
    await page.waitForLoadState("networkidle");
    await expectNoHorizontalScroll(page);
  }
  expect(errors).toEqual([]);

  // Typing a staff URL lands back in the student portal…
  await page.goto("/staff/students");
  await expect(page).toHaveURL(/\/student/);
  // …and the API refuses outright, whatever the UI does.
  const r = await page.request.get("/api/backend/api/students");
  expect(r.status()).toBe(403);
  await admin.dispose();
});
