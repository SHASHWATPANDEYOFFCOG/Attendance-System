# Running the attendance portal

For whoever installs and looks after the system: the college IT person or the developer.
Students and teachers want [USER_GUIDE.md](USER_GUIDE.md) instead.

## What runs where

```
 phones / laptops ──HTTPS──▶  reverse proxy (Caddy, nginx, IIS)  :443
                                   │
                                   ▼
                          web-next  (Next.js)  127.0.0.1:3001   pages + /api/backend proxy
                                   │   cookies → bearer token, same-origin check
                                   ▼
                          app.api   (FastAPI)  127.0.0.1:8079   all data and every permission check
                             ├─ scheduler thread: opens/closes lectures, sends email, weekly digest,
                             │                    camera health, deletes expired snapshots
                             ├─ one worker thread per running CCTV camera
                             └─ database (SQLite file or PostgreSQL) + var/uploads
```

- The browser only ever talks to Next.js. Keep port 8079 off the network (bind to 127.0.0.1).
- Run **one** API process (`--workers 1`). The scheduler, live-update channel and camera
  workers live inside it; two copies would open every lecture twice.
- Face recognition runs on the CPU. A normal 4-core desktop handles one or two cameras at the
  default one frame every 2 seconds; see `python tools/bench_cpu.py` for your machine.

## 1. Install

Python **3.10–3.12** and Node.js **20+**.

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1                # Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
python tools\check_env.py                 # downloads buffalo_l (~300 MB) once and proves it loads

cd web-next
npm ci
npm run build
```

## 2. Configure

```powershell
copy .env.example .env                    # API settings — fill in every value in the file
copy web-next\.env.example web-next\.env.local
```

| Variable | Needed | What it is |
|---|---|---|
| `ATTENDANCE_ENV` | yes | `production`: refuses to start without the two secrets, blocks the demo seed |
| `ATTENDANCE_JWT_SECRET` | yes | signs logins — `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `ATTENDANCE_FERNET_KEY` | yes | encrypts face templates, camera passwords, review crops — **store a copy safely** |
| `ATTENDANCE_DB_URL` | no | default `sqlite:///var/attendance.db`; PostgreSQL: `postgresql+psycopg://user:pw@host/db` |
| `ATTENDANCE_PUBLIC_URL` | yes | the HTTPS address students open; used in email links |
| `SMTP_HOST` `SMTP_PORT` `SMTP_SECURITY` `SMTP_USER` `SMTP_PASSWORD` `SMTP_FROM` | yes | outgoing email (OTP, approvals, alerts). Without it mail goes to `var/outbox/` and the dashboard warns |
| `ATTENDANCE_TRUSTED_PROXIES` | no | who may set `X-Forwarded-For` (default loopback — right for the layout above) |
| `ATTENDANCE_UPLOAD_DIR` / `ATTENDANCE_REVIEW_DIR` / `ATTENDANCE_OUTBOX` | no | storage folders under `var/` by default |
| `ATTENDANCE_API_BASE` (web-next) | no | where Next.js finds the API, default `http://127.0.0.1:8079` |
| `ATTENDANCE_INSECURE_COOKIES` (web-next) | dev only | `1` lets you sign in over plain `http://localhost`. Never on a real deployment |

Losing `ATTENDANCE_FERNET_KEY` means every student must enrol their face again and every
camera password must be re-entered. Changing `ATTENDANCE_JWT_SECRET` signs everyone out.

## 3. Create the first administrator

```powershell
python tools\seed.py --admin principal --password "<a strong password>"
```

Sign in at `https://<your address>/authority/login` (staff; students use `/login`), then in order:

1. **Settings** — college name, minimum attendance %, present/late windows, campus location.
2. **Academic setup** — branches, batches, class groups (sections), subjects, rooms, term,
   timetable, holidays.
3. **Staff & roles** — add teachers and HODs (they receive an email to set their password), or
   let them register at `/authority/register` and approve them under **Approvals → Staff**.
4. **Students** — import a spreadsheet (**Directory → Import CSV / Excel**), add them one by one, or let them
   self-register at `/signup` and approve them under **Approvals**.
5. **CCTV cameras** — optional, see below.

## 4. Run

```powershell
# API (one process)
python -m uvicorn app.api:app --env-file .env --host 127.0.0.1 --port 8079 --workers 1

# Web
cd web-next
npx next start -p 3001 -H 127.0.0.1
```

Keep both running as services:

- **Windows:** create two tasks in Task Scheduler ("At startup", "Run whether user is logged on
  or not") or wrap them with [NSSM](https://nssm.cc/). Set the working folder to the project root
  (and `web-next` for the web task).
- **Linux:** two systemd units, for example:

```ini
# /etc/systemd/system/attendance-api.service
[Service]
WorkingDirectory=/opt/attendance
ExecStart=/opt/attendance/.venv/bin/python -m uvicorn app.api:app --env-file .env --host 127.0.0.1 --port 8079 --workers 1
Restart=always
User=attendance

# /etc/systemd/system/attendance-web.service
[Service]
WorkingDirectory=/opt/attendance/web-next
ExecStart=/usr/bin/npx next start -p 3001 -H 127.0.0.1
Restart=always
User=attendance
```

### HTTPS (required)

Phone browsers only allow the camera and location on HTTPS, and login cookies are HTTPS-only.
You need a domain name (e.g. `attendance.your-college.edu`) pointing at the server. Caddy gets
and renews the certificate by itself:

```
# Caddyfile
attendance.your-college.edu {
    encode gzip
    reverse_proxy 127.0.0.1:3001
}
```

With nginx or IIS, proxy `:443` to `127.0.0.1:3001`, pass `X-Forwarded-For`, raise the request
body limit to 20 MB (selfie and enrolment uploads), and disable response buffering for
`/api/backend/api/live/stream` and `/api/backend/api/notifications/stream` (live updates use
Server-Sent Events).

## 5. Add a CCTV camera

**CCTV cameras → Add camera**, then fill in:

- **Room** — must match the room name used in the timetable. The camera only recognises
  students rostered for the lecture running in that room, and only while it runs.
- **Stream address** — the camera's RTSP URL *without* the username and password.
- **Username / Password** — the camera's login. Stored encrypted; never shown again.
- **Start automatically during lectures in this room** — usually on.

Press **Test** — it grabs one frame and reports whether the stream works.

Finding the RTSP address: check the camera's label or manual, or the NVR's web page (often
"Network → Advanced → RTSP"). Common forms (use the *sub-stream* — lower resolution is plenty and
much cheaper to process):

| Brand | Sub-stream address |
|---|---|
| Hikvision | `rtsp://CAMERA-IP:554/Streams/Channels/102` |
| Dahua / CP Plus | `rtsp://CAMERA-IP:554/cam/realmonitor?channel=1&subtype=1` |
| Uniview | `rtsp://CAMERA-IP:554/unicast/c1/s1/live` |
| Anything ONVIF | find it with *ONVIF Device Manager* (free) → Live video → stream URI |

Test it first in VLC (**Media → Open Network Stream**). For a quick trial without CCTV, a USB
webcam on the server works as stream address `0`.

Mounting: faces should be at least ~80 pixels wide in the frame — a camera over the front
whiteboard facing the class, not on the ceiling looking down. Matches the camera is unsure about
go to **Camera review** for a teacher to confirm; nothing uncertain is marked automatically.
Cameras that stop responding during a lecture alert the admins.

## 6. Campus location (geofence for phone attendance)

**Settings → Mobile**: set **Campus latitude/longitude** (right-click the campus centre in Google
Maps and copy the two numbers) and a **radius** that covers the buildings — 150–300 m is typical.
Rooms in **Academic setup → Rooms** can have their own point and radius, which then wins over the
campus one. While the fence is on and no location is set, phone attendance is refused (it fails
closed, it does not let everyone in). Turn on **Require the rotating session code** if you also
want students to type or scan the code shown on the classroom screen (Live sessions → Present).

## 7. Tune face matching for your students

The shipped thresholds are reasonable starting values, not measured on your students. Once you
have real photos of at least ~10 consenting people (2+ each, some masked or with glasses):

```powershell
#  data/enroll/<person>/*.jpg — one folder per person
python tools\roc.py --images data\enroll --out var\roc
```

It reports false-accept and false-reject rates and prints recommended values; enter them under
**Settings → Face** (match threshold, and the lower review threshold). Raise the match threshold
if wrong people are being marked; lower it if real students keep failing and going to review.

## 8. Backups

```powershell
python tools\backup.py create --dest D:\attendance-backups --keep 14
python tools\backup.py list   --dest D:\attendance-backups
python tools\backup.py verify D:\attendance-backups\attendance-20261004-020000
python tools\backup.py restore D:\attendance-backups\attendance-20261004-020000 --yes   # stop the API first
```

A backup is the database (an online-safe copy; `pg_dump` for PostgreSQL) plus uploaded photos
and attachments, with checksums. Schedule `create` nightly, and copy the folder to a different
machine or cloud storage. The Fernet key is deliberately **not** in the backup — keep it in your
password manager.

## 9. Trying it with demo data (never on the real database)

```powershell
$env:ATTENDANCE_DB_URL = "sqlite:///var/demo.db"
python tools\seed_portal.py --password "Demo-Pass-123"
```

Creates a small college — admin, an HOD, 3 teachers, 30 students, 8 weeks of attendance, leave,
issues and messages — and prints the logins. It refuses to run when `ATTENDANCE_ENV=production`.

## 10. Tests

```powershell
python -m pytest -q                       # backend: permissions, attendance rules, every API
cd web-next
npm run build                             # the browser tests run against the production build
npx playwright install                    # once: Chromium, Firefox, WebKit
npm run test:e2e                          # all four browser projects
npx playwright test --project=webkit-phone   # or one at a time on a small machine
```

The Playwright suite starts its own API (port 8098) and web server (3098) on a throwaway
database in `var/e2e/`, so it never touches real data. It covers registration → email code →
approval, phone attendance refusals (location blocked, outside campus, wrong code) and success,
duplicate registration, students locked out of staff pages, and every main page at 360 px with no
sideways scrolling — on phone Chromium, phone WebKit (Safari's engine), desktop Chromium and
desktop Firefox.

## Troubleshooting

| Symptom | Cause |
|---|---|
| "EMAIL NOT DELIVERED" on the dashboard | `SMTP_HOST` not set; mail is in `var/outbox/` |
| Students cannot open the camera on their phone | site is not on HTTPS |
| "Campus location has not been configured" | set it in Settings → Mobile, or turn the geofence off |
| Camera shows *offline* | wrong RTSP address or password, or the server cannot reach the camera's network; press **Test** |
| Everyone signed out after restart | `ATTENDANCE_JWT_SECRET` changed or not set (development generates a new one) |
| A student is stuck on "waiting for approval" | **Approvals → Registrations** |
