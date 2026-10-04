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

test("by default a registered teacher signs in straight away", async ({ page }) => {
  const tag = uid();
  const admin = await adminApi();
  const cls = await makeClass(admin, tag);
  const email = `quick.${tag.toLowerCase()}@e2e.test`;

  await page.goto("/authority/register");
  await page.waitForLoadState("networkidle");
  await expect(page.getByText(/Your account is ready as soon as you register/)).toBeVisible();
  await page.getByLabel(/^Full name/).fill(`Quick ${tag}`);
  await page.getByLabel(/^Email/).fill(email);
  await page.getByLabel(/^Mobile number/).fill(`6${String(parseInt(tag, 36)).padStart(9, "0").slice(-9)}`);
  await page.getByLabel(/^Employee \/ staff ID/).fill(`QEMP${tag}`);
  await page.getByLabel(/^Branch/).selectOption(String(cls.dept));
  await page.getByLabel(/^Password/).fill("Teach-Pass-123");
  await page.getByLabel(/^Confirm password/).fill("Teach-Pass-123");
  await page.getByRole("button", { name: "Register" }).click();

  await page.waitForURL(/\/authority\/login\?registered=staff/);
  await expect(page.getByRole("status")).toContainText("your account is ready");

  await signIn(page, email, "Teach-Pass-123", "authority");
  await expect(page.getByRole("heading", { name: "Authority dashboard" })).toBeVisible();
  await admin.dispose();
});

test("with approval switched on, a registered teacher waits until an admin approves", async ({ page, browser }) => {
  const tag = uid();
  const admin = await adminApi();
  await admin.patch("/api/backend/api/admin/settings", { data: { staff_registration_approval: true } });
  const cls = await makeClass(admin, tag);
  const email = `staff.${tag.toLowerCase()}@e2e.test`;
  const name = `Teacher ${tag}`;

  await page.goto("/authority/login");
  await page.getByRole("link", { name: "New staff member? Register" }).click();
  await expect(page).toHaveURL(/\/authority\/register/);
  await page.waitForLoadState("networkidle");
  await page.getByLabel(/^Full name/).fill(name);
  await page.getByLabel(/^Email/).fill(email);
  await page.getByLabel(/^Mobile number/).fill(`7${String(parseInt(tag, 36)).padStart(9, "0").slice(-9)}`);
  await page.getByLabel(/^Employee \/ staff ID/).fill(`EMP${tag}`);
  await page.getByLabel(/^Branch/).selectOption(String(cls.dept));
  await page.getByLabel(/^Password/).fill("Teach-Pass-123");
  await page.getByLabel(/^Confirm password/).fill("Teach-Pass-123");
  await page.getByRole("button", { name: "Register" }).click();

  await page.waitForURL(/\/authority\/login\?registered=staff-pending/);
  await expect(page.getByRole("status")).toContainText("An administrator will approve");

  // Not yet: the account exists but grants nothing.
  await page.waitForLoadState("networkidle");
  await page.locator("#username").fill(email);
  await page.getByLabel("Password", { exact: true }).fill("Teach-Pass-123");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.locator("form [role=alert]")).toContainText("waiting for an administrator");

  // The admin approves it from Approvals → Staff.
  const ctx = await browser.newContext();
  const staff = await ctx.newPage();
  await signIn(staff, ADMIN.username, ADMIN.password, "authority");
  await staff.goto("/staff/approvals?tab=staff");
  const card = staff.locator("div").filter({ hasText: `EMP${tag}` }).filter({ has: staff.getByRole("button", { name: "Approve" }) }).last();
  await card.getByRole("button", { name: "Approve" }).click();
  await staff.getByRole("dialog").getByRole("button", { name: "Approve" }).click();
  await expect(staff.getByText(`EMP${tag}`)).toHaveCount(0);
  await ctx.close();

  await signIn(page, email, "Teach-Pass-123", "authority");
  await expect(page.getByRole("heading", { name: "Authority dashboard" })).toBeVisible();
  await admin.patch("/api/backend/api/admin/settings", { data: { staff_registration_approval: false } });
  await admin.dispose();
});
