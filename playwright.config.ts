/**
 * Browser tests: real Next.js build + real FastAPI server on a throwaway database.
 *
 *   npm run build          # once, or after front-end changes
 *   npx playwright install # once: downloads Chromium, Firefox and WebKit
 *   npm run test:e2e
 *
 * Every spec runs on a 360 px phone (Chromium, and WebKit as Safari's engine) and on desktop
 * Chromium and Firefox.
 */
import { defineConfig, devices } from "@playwright/test";

import { API_PORT, WEB_PORT, WEB_URL } from "./e2e/config.mjs";

const phone = { width: 360, height: 740 };

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  // One SQLite database and one settings table are shared by every test: run them in order.
  workers: 1,
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: WEB_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium-phone", use: { ...devices["Galaxy S8"], viewport: phone } },
    // Safari's engine at phone size. Not the full iPhone descriptor: WebKit's "isMobile" emulation
    // is unavailable in Playwright's Windows build, so this is touch + iPhone user agent + 360 px.
    { name: "webkit-phone", use: { browserName: "webkit", viewport: phone, hasTouch: true,
                                    userAgent: devices["iPhone 13"].userAgent } },
    { name: "chromium-desktop", use: { ...devices["Desktop Chrome"] } },
    { name: "firefox-desktop", use: { ...devices["Desktop Firefox"] } },
  ],
  webServer: [
    {
      command: "node e2e/start-api.mjs",
      url: `http://127.0.0.1:${API_PORT}/api/public/academic-options`,
      timeout: 180_000,
      reuseExistingServer: false,
    },
    {
      command: `node node_modules/next/dist/bin/next start -p ${WEB_PORT} -H 127.0.0.1`,
      url: `${WEB_URL}/login`,
      timeout: 120_000,
      reuseExistingServer: false,
      env: { ATTENDANCE_API_BASE: `http://127.0.0.1:${API_PORT}`, ATTENDANCE_INSECURE_COOKIES: "1" },
    },
  ],
});
