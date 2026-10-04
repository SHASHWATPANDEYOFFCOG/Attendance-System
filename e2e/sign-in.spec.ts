/**
 * Two doors: students sign in at /login, staff at /authority/login. Each door turns the other
 * kind of account away (no session is created) and points to the right one.
 */
import { expect, test } from "@playwright/test";

import { ADMIN } from "./config.mjs";
import { adminApi, approvedStudent, makeClass, signIn, uid } from "./helpers";

test("staff sign in at the authority door and land on the authority dashboard", async ({ page }) => {
  await signIn(page, ADMIN.username, ADMIN.password, "authority");
  await expect(page).toHaveURL(/\/dashboard/);
  await expect(page.getByRole("heading", { name: "Authority dashboard" })).toBeVisible();
});

test("each door refuses the other kind of account and links to the right one", async ({ page }) => {
  // Staff at the student door.
  await page.goto("/login");
  await page.waitForLoadState("networkidle");
  await page.locator("#username").fill(ADMIN.username);
  await page.getByLabel("Password", { exact: true }).fill(ADMIN.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.locator("form [role=alert]")).toContainText("authority sign in");
  await expect(page).toHaveURL(/\/login/);
  expect((await page.request.get("/api/backend/api/me")).status()).toBe(401);   // no session
  await page.locator("form [role=alert]").getByRole("link").click();
  await expect(page).toHaveURL(/\/authority\/login/);

  // Student at the authority door.
  const tag = uid();
  const admin = await adminApi();
  const student = await approvedStudent(admin, await makeClass(admin, tag), tag);
  await page.waitForLoadState("networkidle");
  await page.locator("#username").fill(student.email);
  await page.getByLabel("Password", { exact: true }).fill(student.password);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.locator("form [role=alert]")).toContainText("Students use the student sign in");
  expect((await page.request.get("/api/backend/api/me")).status()).toBe(401);
  await admin.dispose();
});

test("a signed-out visit to a staff page goes to the authority sign in", async ({ page }) => {
  await page.goto("/staff/students");
  await expect(page).toHaveURL(/\/authority\/login\?next=%2Fstaff%2Fstudents/);
  await page.goto("/student/leaves");
  await expect(page).toHaveURL(/\/login\?next=%2Fstudent%2Fleaves/);
});
