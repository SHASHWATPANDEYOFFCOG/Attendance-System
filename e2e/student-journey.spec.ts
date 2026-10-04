/**
 * The path every student takes: register → verify email → wait → approved by staff → dashboard.
 * Driven entirely through the UI, in every browser project.
 */
import path from "node:path";

import { expect, test } from "@playwright/test";

import { ADMIN } from "./config.mjs";
import { adminApi, latestMail, makeClass, signIn, uid } from "./helpers";

const PHOTO = path.join(__dirname, "fixtures", "photo.jpg");

test("a student registers, verifies email, is approved and reaches the dashboard", async ({ page, browser }) => {
  const tag = uid();
  const admin = await adminApi();
  const cls = await makeClass(admin, tag);
  const email = `reg.${tag.toLowerCase()}@e2e.test`;
  const name = `Reg ${tag}`;
  const password = "Reg-Pass-123";

  // ---- register (four steps)
  await page.goto("/signup");
  await page.waitForLoadState("networkidle");   // typed before hydration, a field would be reset
  await page.getByLabel("Full name").fill(name);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Mobile number").fill(`8${String(parseInt(tag, 36)).padStart(9, "0").slice(-9)}`);
  await page.getByLabel(/^Password/).fill(password);
  await page.getByLabel("Confirm password").fill(password);
  await page.getByRole("button", { name: "Continue" }).click();

  await page.getByLabel("Branch").selectOption(String(cls.dept));
  await page.getByLabel("Year").selectOption("1");
  await page.getByLabel("Batch").selectOption(String(cls.batch));
  await page.getByLabel("Section").selectOption(String(cls.section));
  await page.getByLabel("Roll number").fill(`G${tag}`);
  await page.getByLabel("Enrollment / registration no.").fill(`ENG${tag}`);
  await page.getByRole("button", { name: "Continue" }).click();

  await page.getByLabel("Date of birth").fill("2006-04-12");
  await page.getByLabel("Gender").selectOption("female");
  await page.getByLabel("Parent / guardian name").fill("Guardian Person");
  await page.getByLabel("Guardian phone").fill("9123456780");
  await page.getByLabel("Address").fill("12 College Road, Pune");
  await page.getByRole("button", { name: "Continue" }).click();

  await page.locator('input[type="file"]').setInputFiles(PHOTO);
  await page.getByRole("button", { name: "Register" }).click();

  // ---- verify email with the code from the (test) outbox
  await page.waitForURL(/\/verify-email/);
  const code = /\b(\d{6})\b/.exec(await latestMail(email, "verification code"))![1];
  await page.getByLabel("Verification code").fill(code);
  await page.getByRole("button", { name: "Verify" }).click();
  await expect(page.getByRole("heading", { name: "Email verified" })).toBeVisible();

  // ---- signed in but waiting
  await signIn(page, email, password);
  await expect(page.getByText("Awaiting approval")).toBeVisible();

  // ---- staff approves from the Approvals page
  const staffCtx = await browser.newContext();
  const staff = await staffCtx.newPage();
  await signIn(staff, ADMIN.username, ADMIN.password);
  await staff.goto("/staff/approvals");
  const card = staff.locator("li, article, section").filter({ hasText: name }).last();
  await card.getByRole("button", { name: "Approve" }).click();
  await staff.getByRole("dialog").getByRole("button", { name: "Approve" }).click();
  await expect(staff.getByText(name)).toHaveCount(0);
  await staffCtx.close();

  // ---- the student now has the real dashboard, and was told by email
  await page.goto("/student");
  await expect(page.getByRole("heading", { name: "My attendance" })).toBeVisible();
  await expect(page.getByText("Awaiting approval")).toHaveCount(0);
  await latestMail(email, "approved");
  await admin.dispose();
});

test("registration refuses a duplicate email with a clear message", async ({ page }) => {
  const tag = uid();
  const admin = await adminApi();
  const cls = await makeClass(admin, tag);
  // An existing student owns the address.
  const taken = `taken.${tag.toLowerCase()}@e2e.test`;
  const r = await admin.post("/api/backend/api/students", {
    data: { full_name: "Already Here", email: taken, mobile: `7${String(parseInt(tag, 36)).padStart(9, "0").slice(-9)}`,
            roll_number: `T${tag}`, enrollment_no: `ENT${tag}`, section_id: cls.section },
  });
  expect(r.ok()).toBeTruthy();

  await page.goto("/signup");
  await page.waitForLoadState("networkidle");   // typed before hydration, a field would be reset
  await page.getByLabel("Full name").fill("Someone Else");
  await page.getByLabel("Email").fill(taken);
  await page.getByLabel("Mobile number").fill(`6${String(parseInt(tag, 36)).padStart(9, "0").slice(-9)}`);
  await page.getByLabel(/^Password/).fill("Other-Pass-123");
  await page.getByLabel("Confirm password").fill("Other-Pass-123");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Branch").selectOption(String(cls.dept));
  await page.getByLabel("Year").selectOption("1");
  await page.getByLabel("Batch").selectOption(String(cls.batch));
  await page.getByLabel("Section").selectOption(String(cls.section));
  await page.getByLabel("Roll number").fill(`U${tag}`);
  await page.getByLabel("Enrollment / registration no.").fill(`ENU${tag}`);
  await page.getByRole("button", { name: "Continue" }).click();
  await page.getByLabel("Date of birth").fill("2006-04-12");
  await page.getByLabel("Gender").selectOption("male");
  await page.getByLabel("Parent / guardian name").fill("Guardian Person");
  await page.getByLabel("Guardian phone").fill("9123456781");
  await page.getByLabel("Address").fill("12 College Road, Pune");
  await page.getByRole("button", { name: "Continue" }).click();
  await page.locator('input[type="file"]').setInputFiles(PHOTO);
  await page.getByRole("button", { name: "Register" }).click();

  await expect(page.getByRole("alert").filter({ hasText: /already registered/i })).toBeVisible();
  await expect(page).toHaveURL(/\/signup/);
  await admin.dispose();
});
