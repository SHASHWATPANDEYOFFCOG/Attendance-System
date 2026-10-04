/**
 * Marking attendance from a phone with the classroom code: every refusal a student can hit,
 * each with an explanation they can act on, then success.
 */
import { expect, test } from "@playwright/test";

import { CAMPUS } from "./config.mjs";
import { adminApi, approvedStudent, B, json, liveLecture, makeClass, signIn, uid } from "./helpers";

test("phone attendance: blocked location, outside campus, wrong code, then marked present", async ({ browser }) => {
  const tag = uid();
  const admin = await adminApi();
  await json(admin.patch(`${B}/admin/settings`, {
    data: { geofence_enabled: true, campus_lat: CAMPUS.latitude, campus_lng: CAMPUS.longitude, geofence_radius_m: 300 },
  }));
  const cls = await makeClass(admin, tag);
  const sessionId = await liveLecture(admin, cls, tag);
  const student = await approvedStudent(admin, cls, tag);
  const currentCode = async () => (await json<{ code: string }>(admin.get(`${B}/sessions/${sessionId}/code`))).code;

  // 1. Location permission refused: the page explains how to allow it; nothing reaches the server.
  const denied = await browser.newContext({ permissions: [] });
  const p1 = await denied.newPage();
  await signIn(p1, student.email, student.password);
  await p1.goto("/student/mark");
  await p1.getByRole("tab", { name: "Classroom code / QR" }).click();
  await p1.getByLabel("Classroom code").fill(await currentCode());
  await p1.getByRole("button", { name: "Mark me present" }).click();
  await expect(p1.getByText(/Location access is blocked|could not find its location/)).toBeVisible();
  await denied.close();

  // 2. Location allowed but 9 km from campus.
  const ctx = await browser.newContext({
    permissions: ["geolocation"],
    geolocation: { latitude: CAMPUS.latitude + 0.08, longitude: CAMPUS.longitude, accuracy: 10 },
  });
  const page = await ctx.newPage();
  await signIn(page, student.email, student.password);
  await page.goto("/student/mark");
  await page.getByRole("tab", { name: "Classroom code / QR" }).click();
  await page.getByLabel("Classroom code").fill(await currentCode());
  await page.getByRole("button", { name: "Mark me present" }).click();
  await expect(page.getByText(/outside campus/i)).toBeVisible();

  // 3. On campus, wrong code.
  await ctx.setGeolocation({ latitude: CAMPUS.latitude + 0.0004, longitude: CAMPUS.longitude, accuracy: 12 });
  const right = await currentCode();
  const wrong = String((Number(right) + 500_000) % 1_000_000).padStart(6, "0");
  await page.getByLabel("Classroom code").fill(wrong);
  await page.getByRole("button", { name: "Mark me present" }).click();
  await expect(page.getByText(/code is wrong or has expired/i)).toBeVisible();

  // 4. On campus, right code: marked, and the card says so after it refreshes.
  await page.getByLabel("Classroom code").fill(await currentCode());
  await page.getByRole("button", { name: "Mark me present" }).click();
  await expect(page.getByText(/You are marked (present|late)/)).toBeVisible();

  // The teacher's live view agrees.
  const live = await json<{ students: { email?: string; display_name?: string; status: string | null }[] }>(
    admin.get(`${B}/sessions/${sessionId}/live`));
  expect(JSON.stringify(live)).toMatch(/"(present|late)"/);
  await ctx.close();
  await admin.dispose();
});
