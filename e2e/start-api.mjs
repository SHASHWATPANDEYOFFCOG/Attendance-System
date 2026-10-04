// Starts the FastAPI server for the browser tests on a throwaway database.
//
// Everything the run writes lives under var/e2e/ (database, uploads, emails) and is wiped at the
// start of every run, so tests never touch a developer's data. The first super admin is created
// with tools/seed.py — the same command an operator runs.
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { ADMIN, API_PORT, E2E_DIR_PARTS, WEB_URL } from "./config.mjs";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const python = [
  path.join(root, ".venv", "Scripts", "python.exe"),
  path.join(root, ".venv", "bin", "python"),
].find(existsSync) ?? "python";
const E2E_DIR = path.join(root, ...E2E_DIR_PARTS);

rmSync(E2E_DIR, { recursive: true, force: true });
mkdirSync(E2E_DIR, { recursive: true });

const env = {
  ...process.env,
  ATTENDANCE_ENV: "development",
  ATTENDANCE_DB_URL: `sqlite:///${path.join(E2E_DIR, "e2e.db").replaceAll("\\", "/")}`,
  ATTENDANCE_UPLOAD_DIR: path.join(E2E_DIR, "uploads"),
  ATTENDANCE_REVIEW_DIR: path.join(E2E_DIR, "review"),
  ATTENDANCE_OUTBOX: path.join(E2E_DIR, "outbox"),
  ATTENDANCE_PUBLIC_URL: WEB_URL,
  ATTENDANCE_DISABLE_RATE_LIMIT: "1",
  // SMTP must not leak in from a developer's shell: mail goes to the outbox the tests read.
  SMTP_HOST: "",
  PYTHONIOENCODING: "utf-8",
};

const seed = spawnSync(python, ["tools/seed.py", "--admin", ADMIN.username, "--password", ADMIN.password],
  { cwd: root, env, stdio: "inherit" });
if (seed.status !== 0) process.exit(seed.status ?? 1);

const api = spawn(python, ["-m", "uvicorn", "app.api:app", "--host", "127.0.0.1", "--port", String(API_PORT)],
  { cwd: root, env, stdio: "inherit" });
const stop = () => api.kill();
process.on("SIGINT", stop);
process.on("SIGTERM", stop);
api.on("exit", (code) => process.exit(code ?? 0));
