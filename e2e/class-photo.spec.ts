/**
 * Tablet photo attendance with the REAL face model: the teacher uploads a group photo during a
 * live lecture and sees the faces found. Uses the sample group photo that ships with InsightFace
 * (not copied into this repository); skipped if that package is not installed.
 */
import { existsSync } from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { ADMIN } from "./config.mjs";
import { adminApi, liveLecture, makeClass, signIn, uid } from "./helpers";

const GROUP = path.resolve(__dirname, "..", "..", ".venv", "Lib", "site-packages", "insightface", "data", "images", "t1.jpg");

test("a teacher photographs the class and sees every face found", async ({ page }) => {
  test.skip(!existsSync(GROUP), "InsightFace sample photo not found in .venv");
  test.setTimeout(240_000);                    // first use loads the face model
  const tag = uid();
  const admin = await adminApi();
  const sessionId = await liveLecture(admin, await makeClass(admin, tag), tag);

  await signIn(page, ADMIN.username, ADMIN.password, "authority");
  await page.goto(`/staff/sessions/${sessionId}`);
  await expect(page.getByRole("heading", { name: "Tablet photo" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Open camera" })).toBeVisible();
  await page.locator('input[type="file"][accept="image/*"]').setInputFiles(GROUP);

  await expect(page.getByText(/photo 1 · 6 face\(s\)/)).toBeVisible({ timeout: 200_000 });
  // Nobody in this new class has enrolled a face: the page says so instead of guessing.
  await expect(page.getByText("No faces to match yet")).toBeVisible();
  await expect(page.getByRole("button", { name: /Mark 0 students as here/ })).toBeDisabled();
  await admin.dispose();
});
