# Smart Attendance — Build Plan

Scope: extend the existing occlusion-robust attendance system into a two-portal Smart Attendance
System (Student portal + Authority portal) with CCTV, mobile-selfie and QR marking. Nothing in
this plan replaces the existing stack.

---

## 1. What already exists (verified by reading the code, baseline 219 tests passing)

| Layer | What is there | Kept as-is? |
|---|---|---|
| Backend | FastAPI (`app/api.py`, ~1.1k lines), SQLAlchemy 2, SQLite (WAL) by default, `ATTENDANCE_DB_URL` already accepts PostgreSQL | Kept, extended with routers |
| Face pipeline | Vendored `occlubio/`: InsightFace SCRFD + ArcFace 512-d, quality gate, occlusion estimate, PAD hook, FAISS cosine gallery | Kept |
| Auth | JWT access/refresh (`app/auth.py`), roles `super_admin > admin(HOD) > faculty > student > parent`, department scoping, ownership checks in queries | Kept, hardened |
| Crypto | Fernet-encrypted embeddings (`app/crypto.py`), PBKDF2 passwords | Embeddings kept; passwords move to argon2 (PBKDF2 still verified, rehashed on login) |
| Org model | Department → Program → Section; Subject; AcademicTerm; FacultyAssignment; TimetableSlot; Holiday; StudentProfile | Extended |
| Attendance | Immutable `sightings` → derived `attendance_records`; overrides survive recompute; manual marking (idempotent open, transactional upsert, lock window); leave requests table | Extended |
| CCTV | Threaded camera worker with reconnect/backoff, heartbeat, confirmation state machine (N agreeing frames, time spread, anti-spoof gate), disk spool | Reworked for class-group matching + review queue |
| Realtime | In-process event bus + SSE (staff, session-scoped) | Extended with per-user channel |
| Reports | Filtered records report, defaulters, daily absentees, CSV/XLSX/PDF export (openpyxl, reportlab) | Extended with daily / monthly / subject / student reports |
| Frontends | `web-next/` — Next.js 16 + Tailwind v4 + Zod, httpOnly-cookie BFF proxy, "register" design system (Barlow Condensed / IBM Plex, ink/oxide/amber/verdant tokens, dark mode). `web/` — legacy static pages served by FastAPI at `/static` | `web-next` is extended; `web/` untouched and still served |

### Decisions that follow from the existing code

* **Stack stays**: FastAPI + SQLAlchemy + Next.js 16. No framework replacement, so no stop-and-ask.
* **Face recognition stays in-process** with the API (as today) rather than a separate service. The
  pipeline is already isolated behind `PipelineService`; splitting it into a network service
  would add latency and a failure mode without a benefit at single-campus scale. The docker-compose
  file runs the API (which owns the camera workers), the web app and PostgreSQL.
* **Database**: SQLite stays the default (zero setup, existing data in `var/attendance.db`);
  PostgreSQL is supported via `ATTENDANCE_DB_URL` and used by docker-compose. Embeddings stay
  Fernet-encrypted blobs searched in memory (pgvector would require storing them decrypted).
* **Schema changes are additive only**, applied automatically at startup by the existing
  `app/migrate.py` (new tables via `create_all`, new columns via `ALTER TABLE ADD COLUMN` with
  server defaults). Existing rows keep working: existing students/enrollments default to
  `approved`.

### Mapping the requested model onto the existing one

| Requested | Implemented as |
|---|---|
| Branch | existing `Department` (code `CSE`, name) |
| Year (1st–4th) | integer `year` on `Section` and `Subject`; the valid range comes from `Program.duration_years` (edited with the program). No separate table is needed. |
| Batch (2023–2027) | **new** `Batch` table; `Section.batch_id` |
| Section / ClassGroup | existing `Section` (program→branch, year, semester, **batch**, name). One section row *is* a class group. |
| Subject (code, name, branch, year, semester) | existing `Subject` + new `year`, `semester` columns |
| TeacherAssignments | existing `FacultyAssignment` |
| Timetable | existing `TimetableSlot` (room validated against `Room`) |
| Rooms | **new** `Room` (name, building, optional per-room geofence) |
| Teacher / Admin / HOD | `faculty` / `super_admin` / `admin` (HOD, department-scoped). HOD fits the existing structure, so it is included. |

---

## 2. What will be added

### Database (new tables / columns)

New tables: `batches`, `rooms`, `email_otps`, `password_reset_tokens`, `profile_edit_requests`,
`face_enrollment_requests` (re-enrollment), `liveness_challenges`, `selfmark_attempts`,
`review_queue`, `leave_attachments` (files table `stored_files`), `issues`, `issue_comments`,
`conversations`, `messages`, `announcements`.

New columns (all nullable or server-defaulted):

* `users`: `failed_logins`, `locked_until`, `email_verified_at`, `last_login_at`
* `student_profiles`: `roll_number`, `enrollment_no`, `department_id`, `batch_id`, `year`,
  `dob`, `gender`, `guardian_name`, `guardian_phone`, `guardian_email`, `address`,
  `photo_file_id`, `status` (pending/approved/rejected), `rejection_reason`, `approved_by_id`,
  `approved_at`, `below_min_notified`
* `sections`: `batch_id`; `subjects`: `year`, `semester`
* `sessions`: `status` (scheduled/active/closed), `started_at`, `closed_at`, `started_by_id`,
  `code_secret`
* `attendance_records`: `method` is the existing `source` column, extended with `cctv`,
  `mobile`, `qr`; new `marked_by_id`, `marked_at`, `confidence`
* `enrollments`: `status` (pending/approved/rejected, existing rows `approved`),
  `reviewed_by_id`, `reviewed_at`, `review_note`, `samples_encrypted` (encrypted face chips for
  teacher review, wiped on decision)
* `cameras`: `username_encrypted`, `password_encrypted`, `enabled`, `auto_start`
* `leave_requests`: `explanation`, `session_ids` (specific lectures), `attachment_file_id`,
  `updated_at`; `notifications`: `title`, `body`, `link`
* Status values gain `on_leave` (excluded from the denominator, like `excused`).

Constraints: `uq_profile_roll_branch_batch (department_id, batch_id, roll_number)`, existing
`uq_record_session_user` (one record per student per session — also the duplicate-request
guard), unique `users.email`, new unique `users.phone`, `uq_review_session_user_open`.

### API (new routers under `app/routes/`)

| Area | Endpoints (prefix `/api`) |
|---|---|
| Auth | `auth/signup`, `auth/verify-email`, `auth/resend-otp`, `auth/forgot-password`, `auth/reset-password`, `me/password`; login accepts username, email or roll number; lockout + rate limits |
| Public | `public/academic-options` (dropdowns for signup), `public/privacy` |
| Academic | CRUD `departments`, `programs`, `batches`, `sections`, `subjects`, `rooms`, `holidays`, `terms`, `assignments`, `timetable`; `students/import` (CSV/XLSX) + `students/import/template` |
| Students | `students` directory (filters), `students/{id}` detail, approve/reject, profile edit requests, `me/profile`, `me/edit-requests` |
| Face | `me/face/consent`, `me/face/challenge`, `me/face/check-frame`, `me/face/enroll`, `face-enrollments` (review), `me/face/reenroll-request` |
| Sessions | `sessions/live` (today, scoped), `sessions/{id}/start`, `.../stop`, `.../code` (rotating code + QR payload), `.../live` (counts + roster), `.../review-queue`, `me/sessions/active`, `attendance/sessions/{id}/self-mark` (mobile selfie), `attendance/qr` |
| Leaves | `me/leaves` CRUD (pending only), `leaves` list/approve/reject/bulk |
| Issues | `me/issues`, `issues`, `issues/{id}/comments`, assign, status |
| Messages | `conversations`, `conversations/{id}/messages`, `messages/broadcast`, `announcements` |
| Notifications | `notifications`, `notifications/read`, `notifications/stream` (SSE) |
| Cameras | create/update with encrypted credentials, `cameras/{id}/test` (live preview JPEG) |
| Reports | `reports/daily`, `reports/monthly`, `reports/subjects`, `reports/student/{id}`, each with `?format=csv|xlsx|pdf` |
| Admin | `admin/users` (teachers/admins, roles), `admin/settings`, existing `audit` with filters |
| Files | `files/{id}` — authorised download only |

Every route enforces role + ownership on the server; the Next.js proxy is a transport only.

### Pages (web-next)

* Public: `/login` (existing, extended), `/signup`, `/verify-email`, `/forgot-password`,
  `/reset-password`, `/privacy`, `/guide`.
* Student (`/student/...`): dashboard, history (+PDF), mark, leaves, issues, messages,
  notifications, profile, face enrollment. `/my-attendance` keeps working (redirects to the new
  dashboard for students, still serves parents).
* Authority (`/staff/...` plus the existing `/dashboard`, `/mark`, `/reports`): dashboard
  (extended), students + detail, approvals, live session + full-screen QR, review queue, leaves,
  issues, messages + announcements, reports, setup (academic structure, timetable, rooms,
  holidays, cameras, import), admin (users, settings, audit log).
* Shared shell: sidebar + top bar with notification bell (SSE), unread badges, theme toggle,
  toasts, loading/empty/error states, installable PWA manifest.

### Folder changes

```
app/routes/            new FastAPI routers (one per area)
app/settings_service.py   typed runtime settings over the existing `settings` table
app/mailer.py, app/notify.py, app/scheduler.py, app/ratelimit.py, app/uploads.py,
app/liveness.py, app/geo.py, app/session_code.py, app/selfmark.py, app/leave_service.py,
app/roster_match.py
tools/seed_portal.py, tools/backup.py, tools/restore.py
tests/test_portal_*.py
web-next/app/(public|student|staff)/...  web-next/components/portal/...
web-next/e2e/  (Playwright)
docker-compose.yml, Dockerfile.api, web-next/Dockerfile, .env.example
docs/USER_GUIDE.md
```

### Third-party libraries

Backend: `argon2-cffi` (password hashing), `python-magic` is **not** used (no Windows wheel
without libmagic) — file types are verified by magic bytes in `app/uploads.py`; `openpyxl` and
`reportlab` (already installed, now declared). Frontend: `qrcode` (render the rotating QR),
`@playwright/test` (e2e). Liveness runs server-side on InsightFace landmarks, so no MediaPipe
download is needed; the browser only guides capture.

---

## 3. Key behaviour decisions

* **Time window** (settings, default): present ≤ 10 min after start, late ≤ 20 min, after that a
  self-mark is refused and the student is absent unless a teacher changes it.
* **Session lifecycle**: a scheduler thread opens sessions from the timetable at start time
  (skipping holidays), teachers can start/stop manually, sessions close at end time. Closing
  fills every unmarked approved student as `absent`, or `on_leave` if an approved leave covers
  the date/lecture. Approving a leave later rewrites already-closed sessions too.
* **CCTV** matches only against the session's roster (1:N over ~60 templates, not the whole
  gallery), marks after N agreeing frames (setting, default 3), sends near-threshold matches to
  the review queue with a face crop (deleted after 7 days), ignores and never stores unknown
  faces, and never writes video to disk.
* **Mobile selfie** requires: approved student, rostered, active session, inside the time window,
  inside the geofence, valid rotating code (if enabled), server-verified head-turn liveness and a
  1:1 face match. Failures are logged and limited to 3 per session.
* **Liveness** is a random head-turn challenge verified on the server from facial landmarks: a
  flat photo (printed or on a phone) cannot change its yaw on cue. A replayed *video* of the
  student can defeat it unless PAD weights are configured — stated in the UI and docs.
* **Manual changes** of an existing status require a reason, recorded per change in the audit log.
* **Email**: SMTP from env. Without `SMTP_HOST`, mail is written to `var/outbox/*.eml` and the
  system-status panel says so (development only; production refuses to start without SMTP).

---

## 4. Build order (each phase: run app, run tests, commit)

| # | Phase | Main work |
|---|---|---|
| 1 | Explore + this plan | done |
| 2 | Schema, roles, auth, role routing | new models + migration, argon2, lockout, rate limits, login by email/roll, role-based redirect, portal shell |
| 3 | Academic structure, registration, OTP, approvals, profile | CRUD + CSV import, signup + OTP, approval flow, edit requests, password reset |
| 4 | Sessions, timetable, manual, QR, student dashboard | scheduler, start/stop/close, absent/leave fill, rotating code + QR, reasons on edits, student dashboard + history |
| 5 | Leaves, issues, messaging, announcements, notifications | services + pages, SSE notifications, email |
| 6 | Face enrollment, liveness, mobile attendance + geofence | consent, guided capture, server checks, review/approval, self-mark |
| 7 | CCTV | encrypted credentials, test connection, roster matching, review queue, health alerts, auto start/stop |
| 8 | Reports, exports, charts, defaulters | daily/monthly/subject/student reports, CSV/XLSX/PDF |
| 9 | Security + privacy + polish | audit viewer, privacy page, CSRF origin check, upload hardening, dark mode, 360 px pass, PWA |
| 10 | Seed, docs, full testing | seed script, README, user guide, backup/restore, pytest + Playwright |

Effort is dominated by phases 3–7 (most of the new surface area).

## 5. Known constraints up front

* **Real hardware is needed** to verify recognition accuracy, CCTV against a real RTSP camera,
  geolocation on a phone, and Safari/Android camera permissions end to end. Automated tests use a
  stub pipeline and synthetic frames for these paths.
* **Thresholds are still placeholders** until `tools/roc.py` is run on real enrolled faces.
* **Anti-spoofing weights** are not bundled; with `antispoof_mode: strict` (default) a CCTV worker
  refuses to start until PAD weights are configured or the admin switches to `permissive`.
* **Docker is not installed on the build machine**, so `docker-compose.yml` is written but not
  executed here.
* **Roll numbers stay globally unique** on `users.roll_number` (existing constraint used for
  login); the new per-branch+batch constraint is enforced in addition.
