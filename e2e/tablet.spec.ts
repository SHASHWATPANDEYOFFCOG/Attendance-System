/**
 * Tablets end to end, through the real pages: an administrator puts a teacher in a workspace;
 * the teacher registers a tablet, pairs this browser with the code shown, and can then take
 * attendance from a photo on their lecture. Before pairing, the lecture page says a registered
 * tablet is needed instead of offering controls the server would refuse.
 */
import { expect, request, test } from "@playwright/test";

import { WEB_URL } from "./config.mjs";
import { adminApi, B, json, latestMail, liveLecture, makeClass, signIn, uid } from "./helpers";

test("a teacher registers and pairs a tablet, then the lecture page allows photo attendance", async ({ page }) => {
  const tag = uid();
  const admin = await adminApi();
  const sessionId = await liveLecture(admin, await makeClass(admin, tag), tag);

  // The lecture's teacher sets their password from the invite email.
  const email = `teacher.${tag.toLowerCase()}@e2e.test`;
  const token = /token=([\w-]+)/.exec(await latestMail(email, "token="))![1];
  const pub = await request.newContext({ baseURL: WEB_URL, extraHTTPHeaders: { Origin: WEB_URL } });
  await json(pub.post("/api/public/auth/reset-password", { data: { token, password: "Teach-Pass-123" } }));
  await pub.dispose();
  const teacher = (await json<{ id: number; email: string }[]>(admin.get(`${B}/admin/users`))).find((u) => u.email === email)!;
  await json(admin.post(`${B}/workspaces`, { data: { name: `Block ${tag}`, member_ids: [teacher.id] } }));

  await signIn(page, email, "Teach-Pass-123", "authority");

  // Not a tablet yet: the lecture page explains instead of offering the camera.
  await page.goto(`/staff/sessions/${sessionId}`);
  await expect(page.getByText("Registered tablet needed").first()).toBeVisible();

  // Register a tablet and pair this browser with the code shown.
  await page.goto("/staff/tablets");
  await page.waitForLoadState("networkidle");
  await page.getByRole("button", { name: "+ Register a tablet" }).click();
  await page.getByLabel(/^Tablet name/).fill(`Room tablet ${tag}`);
  await page.getByRole("button", { name: "Register and get pairing code" }).click();
  const shown = await page.locator("p.font-mono").filter({ hasText: /^[A-Z0-9]{4}-[A-Z0-9]{4}$/ }).first().textContent();
  expect(shown).toMatch(/^[A-Z0-9]{4}-[A-Z0-9]{4}$/);
  await page.getByLabel("Pairing code").fill(shown!);
  await page.getByRole("button", { name: "Pair this device" }).click();
  await expect(page.getByText(`This browser is Room tablet ${tag}`)).toBeVisible();

  // Now the lecture page offers photo attendance from this device.
  await page.goto(`/staff/sessions/${sessionId}`);
  await expect(page.getByRole("button", { name: "Open camera" })).toBeVisible();
  await expect(page.getByText("Registered tablet needed")).toHaveCount(0);
  await admin.dispose();
});
