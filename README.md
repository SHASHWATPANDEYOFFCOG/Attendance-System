# Occlusion-robust live attendance

A live attendance system built on the [occlubio](https://github.com/SHASHWATPANDEYOFFCOG/occlubio)
face-recognition pipeline. A camera watches a door or a room; when an enrolled person appears,
the system recognises them through masks, glasses and partial cover, confirms it is not a photo
or a one-frame fluke, and stamps them present. Faculty and students sign into the same dashboard;
role decides what fills it.

> **Read [PRIVACY.md](PRIVACY.md) before pointing a camera at anyone.** This is biometric
> identification by a fixed camera — the most legally sensitive configuration here.

## The attendance portal

A complete web portal is built on top of the recognition pipeline (`web-next/` front end,
`app/` API):

- **Students** register themselves (email OTP, profile photo, staff approval), enrol their face
  with consent and a liveness check, and mark attendance from their phone or laptop during a
  live lecture — face check or rotating classroom QR/code, inside a campus geofence. They see
  their percentage overall and per subject, how many classes they can still miss, a calendar
  and full history (PDF), apply for leave, raise issues, and message teachers.
- **Teachers / HODs / admins** manage branches, batches, class groups, subjects, rooms, terms,
  timetable and holidays; approve registrations, profile edits and face enrolments; run live
  sessions (auto-started from the timetable, projector QR, manual P/L/A/O/E with reasons and an
  audit log); review uncertain CCTV matches; approve leave; answer issues; send messages and
  notices; and pull daily, monthly, subject-wise, student-wise and defaulter reports as CSV,
  Excel or PDF. Teachers only ever see their own classes — enforced by the API, not the menu.
- **CCTV**: RTSP cameras mapped to rooms recognise only the students rostered for the lecture
  running in that room, only while it runs; unsure matches go to review, never auto-marked.
- Email + real-time in-app notifications, installable as a phone app (PWA), dark mode,
  works at 360 px.

**Try it locally** (Python 3.10–3.12, Node 20+):

```powershell
py -3.12 -m venv .venv; .venv\Scripts\Activate.ps1; pip install -e ".[dev]"
$env:ATTENDANCE_DB_URL = "sqlite:///var/demo.db"
python tools\seed_portal.py --password "Demo-Pass-123"      # demo college; prints the logins
python -m uvicorn app.api:app --host 127.0.0.1 --port 8079   # terminal 1 (same DB URL)

cd web-next; npm ci; npm run build
$env:ATTENDANCE_INSECURE_COOKIES = "1"; npx next start -p 3001   # terminal 2
# open http://localhost:3001  — admin / teacher.cse / 23cse001, password Demo-Pass-123
```

**Deploy for real:** [docs/DEPLOY.md](docs/DEPLOY.md) — environment variables
([.env.example](.env.example)), HTTPS, adding CCTV cameras and finding RTSP addresses, campus
geofence, tuning the face threshold, backups. **Users:** [docs/USER_GUIDE.md](docs/USER_GUIDE.md)
(also in the app at `/guide`).

---

## Status — what is verified, and what is not

Stated plainly, because a dashboard on an unverified pipeline is a demo, not a system.

### Verified by execution on this machine

- `buffalo_l` downloads and runs CPU-only (AMD Ryzen, `onnxruntime 1.28`, no CUDA provider).
- **Measured per-stage cost** (`tools/bench_cpu.py`, medians over 15 runs):

  | stage | cost |
  |---|---|
  | SCRFD detect @ 640×640 | **160 ms** |
  | SCRFD detect @ 480×480 | 88 ms |
  | SCRFD detect @ 320×320 | 38 ms |
  | ArcFace embed, 1 face | **66 ms** |
  | align / quality / occlusion | < 1 ms combined |
  | FAISS search, 1 200 identities | **0.3 ms** |
  | FAISS search, 5 000 identities | 1.0 ms |

  Frame budget, one face in frame: 4.4 FPS at stride 1, **8.4 FPS at stride 3** (the shipped
  `detect_every_n_frames`), 10.2 FPS at stride 5. Detection dominates; search is free.
  This contradicts the upstream README's "roughly 0.4 FPS on video" — that figure is ~20×
  pessimistic for this hardware.
- Embedding dimension is 512 and L2-normalisation round-trips to unit norm, so `IndexFlatIP`
  really is cosine similarity.
- **The automated test suite passes** (`pytest -q`): state machine, attendance rules, authorization,
  recompute/override/CSV, a worker integration suite driven by a fake camera, and the portal APIs.
- **34 HTTP checks pass** against a live `uvicorn` server (`tools/smoke_http.py`): every page
  serves, login/refresh work, role boundaries hold, CSV matches JSON.

### NOT verified — requires real people and a real camera

The Part A acceptance gate cannot be closed without human subjects, and none of it is claimed
here:

- [ ] Two real people enrolled from real photos.
- [ ] Recognition of those people clean, then masked, with the score drop reported.
- [ ] A third un-enrolled person correctly returning *unknown*.
- [ ] `recognize_video.py` against a physical camera, with end-to-end "face enters frame →
      dashboard stamps present" latency measured.
- [ ] Thresholds derived from a ROC curve — **the shipped values are the spec's placeholders.**

Run `tools/roc.py` (below) to close the last one; it prints the exact lines to paste into
`configs/default.yaml`. Until then the false-accept and false-reject rates of this deployment are
unknown, and the dashboard says so on every page.

### Hooks still missing weights

- **Anti-spoofing.** `occlubio/pipeline/antispoof.py` is a hook with no model. Without weights it
  returns `live=True` for everything, including a phone screen. `attendance.antispoof_mode:
  strict` (the default) makes a live camera **refuse to start**; `permissive` starts it behind a
  loud banner. Supply a MiniFASNet ONNX at `antispoof.onnx_path`.
- Trained occlusion-type classifier, biometric template protection, gait/body-ReID fusion,
  DeepStream deployment — all noted in the upstream architecture doc, none built here.

---

## Two upstream issues found

**1. `occlubio/data/` is missing from the published repository.** The upstream `.gitignore` line
20 is a bare `data/`, which git applies at every directory level, so the package was silently
never committed. `scripts/make_occluded_dataset.py` imports `from occlubio.data import
OcclusionAugmentor` and fails on a fresh clone with `ModuleNotFoundError`. Since the whole
threshold-derivation workflow depends on it, the module has been **reconstructed** here
(`occlubio/data/occlusion_aug.py`) to the interface the upstream script expects, with occluder
geometry aligned to the detection bands in `occlubio/pipeline/occlusion.py`. It is clearly marked
as a reconstruction, not upstream code. This project's `.gitignore` uses `/data/` to avoid
repeating the bug.

**2. Config keys named in the build spec do not exist upstream.** `review_threshold`,
`dup_threshold` and `min_enroll_images` are referenced throughout the spec but absent from
`configs/default.yaml`. They have been added under `gallery:` and flagged UNVALIDATED. Upstream
values that *do* exist (`match_threshold 0.45`, `quality.min_score 0.35`, `score_thresh 0.5`,
`det_size 640×640`) match the spec's starting points and were left unchanged.

---

## Install

Python **3.10–3.12** (3.13+ has no wheels for parts of the CV stack; this was built on 3.12.6).

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

First run downloads `buffalo_l` (~300 MB) into `~/.insightface`.

```powershell
python tools\check_env.py     # proves the pipeline imports and the model loads
python tools\bench_cpu.py     # measures per-stage cost on YOUR hardware
```

### Required environment

```powershell
$env:ATTENDANCE_JWT_SECRET = "<32+ random bytes>"
$env:ATTENDANCE_FERNET_KEY = "<output of Fernet.generate_key()>"
$env:ATTENDANCE_ENV        = "production"   # refuses to start without the two keys above
```

In development both are auto-generated (the Fernet key is persisted to `var/dev_fernet.key` so
templates survive a restart) with a warning. `ATTENDANCE_ENV=production` turns that off.

## Run

The portal: see [The attendance portal](#the-attendance-portal) above and
[docs/DEPLOY.md](docs/DEPLOY.md).

The original no-build kiosk dashboard is still served by the API:

```powershell
python tools\seed.py --admin root --password "<strong password>" --demo
python -m uvicorn app.api:app --port 8077
# http://127.0.0.1:8077  ->  /static/login.html
```

## Derive your thresholds

```powershell
#  data/enroll/<person>/*.jpg   — one folder per person, >= 2 images each
python tools\roc.py --images data\enroll --out var\roc
```

Reports genuine/impostor distributions and TAR at FAR 1e-3 and 1e-4, separately for **clean,
masked and sunglasses** subsets, then prints the three threshold lines to paste into
`configs/default.yaml`. With fewer than ~10 identities it says so — a FAR of 1e-4 needs ~10 000
impostor pairs to mean anything.

---

## How it works

```
frame ─▶ SCRFD detect ─▶ IoU track ─▶ align 112×112 ─▶ quality gate ─▶ occlusion score
                                                            │
                                        anti-spoof ◀────────┤
                                                            ▼
                                    ArcFace 512-d ─▶ L2 norm ─▶ FAISS IndexFlatIP
                                                                       │
                                                          confirmation state machine
                                                                       ▼
                                                  sighting ─▶ compute_attendance ─▶ record
```

Two invariants everything downstream depends on:

- **Embeddings are L2-normalised before insert and before search.** `IndexFlatIP` over unit
  vectors is cosine similarity; skip the normalise and every threshold becomes meaningless.
- **The database is the source of truth; the FAISS index is derived.** It is rebuilt from
  `enrollments` at startup and after every enrolment, deletion and erasure.

### Nobody is marked present on one frame

`app/confirm.py`. A track is CONFIRMED only when **all** hold: `confirm_frames` (5) agreeing
frames for the same identity, inside `confirm_window_s` (6 s), median score ≥ `match_threshold`,
at least one frame through the quality gate, anti-spoof clean, and the evidence spread over
`min_distinct_windows` (2) time buckets spanning `min_span_seconds` (1.5 s) — so a briefly-held
photo cannot confirm. Identity flip-flop → `AMBIGUOUS` → review, never a guess.

The module is pure: no I/O, no clock reads, timestamps injected. That is why it is testable
without a camera or a model, and it is what the dashboard's confirmation pips are showing.

### Weak evidence never auto-marks absent

`app/rules.py::compute_attendance` is pure — no I/O, no DB, no globals, no clock. `absent`
requires *no sighting at all*. A sighting that existed but never confirmed becomes
`needs_review`, and a human decides. A wrong absent costs someone a grade or a day's pay; a
review row costs faculty thirty seconds.

Records are fully recomputable from sightings + config, which
`POST /api/sessions/{id}/recompute` proves. Human overrides survive recompute — a faculty
decision outranks a derived one.

### Performance choices, from the measurements above

- Confirmed tracks **stop being embedded**: detection and tracking continue so presence time
  keeps accumulating, but align→embed→search is skipped. At 66 ms per face per processed frame
  this is the single largest CPU saving available, and
  `test_confirmed_tracks_stop_being_embedded` guards it.
- `detect_every_n_frames: 3` from the measured curve — past ~5 the embedding cost dominates and
  raising it further buys almost nothing.
- The worker always processes the **newest** frame and drops stale ones. A backlog would mean
  stamping people present from thirty seconds ago.

---

## Layout

```
occlubio/        vendored upstream pipeline — NEVER EDITED (except the restored data/ package)
configs/         default.yaml: upstream block + the added `attendance:` block
app/
  confirm.py       identity confirmation state machine   (pure)
  rules.py         compute_attendance()                  (pure)
  worker.py        one supervised thread per camera
  api.py           FastAPI: auth, enrol, cameras, sessions, SSE, reports
  routes/          portal API: accounts, students, academic setup, sessions, face, leaves,
                   issues, messaging, notifications, cameras, reports, admin
  session_service.py marking_service.py selfmark.py liveness.py geo.py cctv.py scheduler.py
  models.py db.py migrate.py auth.py crypto.py scope.py notify.py mailer.py settings_service.py
  gallery_service.py  attendance_service.py  pipeline_service.py  schemas.py
web-next/        the portal front end (Next.js): student portal, staff portal, PWA; e2e/ tests
web/             original kiosk dashboard — no framework, no build step
tools/           seed_portal (demo data), seed (first admin), backup, roc, check_env, bench_cpu
tests/           backend tests, none needing a model download or a camera
docs/            DEPLOY.md, USER_GUIDE.md, SCHEMA.md; upstream/ = original occlubio docs
```

**Nothing under `occlubio/` is edited.** Behaviour changes go in `configs/default.yaml` or in
`app/`. `app/pipeline_service.py` composes the upstream stages rather than calling
`RecognitionEngine.process_frame`, for two reasons documented in that file: `process_frame`
fuses embeddings across a track buffer (which would make "N independent agreeing frames" untrue),
and `gallery.identify()` discards the raw score the state machine needs to tell a review-band
candidate from a genuine non-match.

Every threshold lives in `configs/default.yaml`. There are no magic numbers in `app/`.

## Tests

```powershell
pytest -q                                  # backend: rules, permissions, every portal API, tools
cd web-next; npm run test:e2e              # browsers: Chromium/WebKit at 360 px, Chromium/Firefox desktop
python tools\smoke_http.py --password ...  # checks against a running kiosk server
```

`tests/test_worker_integration.py` drives the **real** tracker, FAISS gallery, state machine,
session resolution and recompute path through a fake camera, stubbing only the two CNNs. It
proves the attendance machinery is wired correctly. It does **not** prove face recognition works
on real faces — only `tools/roc.py` on real identities can.

## Out of scope

AdaFace fine-tuning, DeepStream/Jetson port, a native mobile app (the portal is an installable
web app instead), multi-tenancy. PostgreSQL works via `ATTENDANCE_DB_URL` but is not exercised by
the test suite, which runs on SQLite. Seams are left clean.

Revisit fine-tuning only if masked-face TAR is measurably poor **and** thresholding cannot fix
it — the stock `buffalo_l` embedder plus a well-chosen threshold is enough to get an attendance
system working.
