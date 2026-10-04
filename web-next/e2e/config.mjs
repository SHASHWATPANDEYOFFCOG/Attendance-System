// Shared by the Playwright config, the API launcher and the tests.
export const API_PORT = 8098;
export const WEB_PORT = 3098;
export const WEB_URL = `http://127.0.0.1:${WEB_PORT}`;
/** Everything a run writes, relative to the repository root. Wiped at the start of each run. */
export const E2E_DIR_PARTS = ["var", "e2e"];
export const ADMIN = { username: "e2e.admin", password: "E2e-Admin-Pass-1" };
/** The college's timezone (configs/default.yaml `timezone`), for building a lecture that runs "now". */
export const COLLEGE_TZ = "Asia/Kolkata";
export const CAMPUS = { latitude: 18.52, longitude: 73.85 };
