"""End-to-end HTTP smoke test against a running server.

    python tools/smoke_http.py --base http://127.0.0.1:8077 --user root --password ...

Exercises the paths a browser actually takes: static pages, login, dashboard, session
attendance, CSV, system status and the role boundaries.
"""
from __future__ import annotations

import argparse
import sys

import httpx

FAILURES: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}{('  -> ' + detail) if detail and not ok else ''}")
    if not ok:
        FAILURES.append(name)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8077")
    ap.add_argument("--user", default="root")
    ap.add_argument("--password", required=True)
    args = ap.parse_args()

    c = httpx.Client(base_url=args.base, timeout=30.0, follow_redirects=False)

    print("\nstatic pages")
    for page in ("login.html", "dashboard.html", "enroll.html", "sessions.html",
                 "reports.html", "app.css", "app.js"):
        r = c.get(f"/static/{page}")
        check(f"GET /static/{page}", r.status_code == 200, str(r.status_code))
    check("GET / redirects to login", c.get("/").status_code in (302, 307))

    print("\nauth")
    r = c.post("/api/auth/login", json={"username": args.user, "password": args.password})
    check("login", r.status_code == 200, r.text[:160])
    if r.status_code != 200:
        return 1
    body = r.json()
    admin = {"Authorization": f"Bearer {body['access_token']}"}
    check("role is admin", body["role"] == "admin", body["role"])

    check("bad password rejected",
          c.post("/api/auth/login",
                 json={"username": args.user, "password": "wrong"}).status_code == 401)
    check("anonymous dashboard rejected", c.get("/api/dashboard").status_code in (401, 403))

    r = c.post("/api/auth/refresh", json={"refresh_token": body["refresh_token"]})
    check("refresh token works", r.status_code == 200, r.text[:160])

    print("\ndashboard")
    r = c.get("/api/dashboard", headers=admin)
    check("GET /api/dashboard", r.status_code == 200, r.text[:200])
    d = r.json() if r.status_code == 200 else {}
    check("payload is staff-scoped", d.get("scope") == "staff", str(d.get("scope")))
    check("system warnings present", bool(d.get("system", {}).get("warnings")))
    check("timezone rendered", d.get("timezone") == "Asia/Kolkata", str(d.get("timezone")))

    warnings = " ".join(d.get("system", {}).get("warnings", []))
    check("anti-spoof warning surfaced", "ANTI-SPOOF" in warnings.upper())
    check("unvalidated thresholds surfaced", "UNVALIDATED" in warnings.upper())

    print("\nsessions and reports")
    sessions = c.get("/api/sessions", headers=admin).json()
    check("sessions listed", len(sessions) >= 1, str(len(sessions)))
    if sessions:
        sid = sessions[0]["id"]
        r = c.get(f"/api/sessions/{sid}/attendance", headers=admin)
        check("session attendance", r.status_code == 200, r.text[:200])
        recs = r.json().get("records", [])
        check("roster produced records", len(recs) >= 1, str(len(recs)))

        valid = {"present", "late", "absent", "partial", "left_early", "needs_review"}
        check("every status is a known value",
              all(x["effective_status"] in valid for x in recs),
              str([x["effective_status"] for x in recs]))

        # The invariant that actually matters, and that survives demo data: a rostered
        # person with no matched frames and no human override must read `absent` -- weak
        # evidence never silently becomes attendance.
        unevidenced = [x for x in recs
                       if not x.get("frames_matched") and not x.get("overridden_status")]
        check("no-evidence rows read absent",
              all(x["effective_status"] == "absent" for x in unevidenced),
              str([(x["display_name"], x["effective_status"]) for x in unevidenced]))

        r = c.get(f"/api/reports/attendance.csv?session_id={sid}", headers=admin)
        check("csv export", r.status_code == 200 and "user_id" in r.text, str(r.status_code))
        check("csv row count matches json",
              len(r.text.strip().splitlines()) == len(recs) + 1)

        r = c.post(f"/api/sessions/{sid}/recompute", headers=admin)
        check("recompute", r.status_code == 200, r.text[:160])

    print("\ncameras")
    r = c.get("/api/cameras", headers=admin)
    check("cameras listed", r.status_code == 200 and len(r.json()) >= 1)

    print("\nrole boundaries")
    r = c.post("/api/auth/register", json={
        "username": "smoke_student", "password": "password123",
        "display_name": "Smoke Student", "roll_number": "SMOKE1"})
    check("public register creates a student", r.status_code in (201, 409), r.text[:160])
    r = c.post("/api/auth/login", json={"username": "smoke_student", "password": "password123"})
    if r.status_code == 200:
        stu = {"Authorization": f"Bearer {r.json()['access_token']}"}
        check("student blocked from cameras", c.get("/api/cameras", headers=stu).status_code == 403)
        check("student blocked from live stream",
              c.get("/api/live/stream", headers=stu).status_code == 403)
        check("student blocked from audit log",
              c.get("/api/audit", headers=stu).status_code == 403)
        sd = c.get("/api/dashboard", headers=stu).json()
        check("student dashboard is self-scoped", sd.get("scope") == "self")
        check("student dashboard has no cameras", sd.get("cameras") == [])

    print(f"\n{'ALL PASSED' if not FAILURES else str(len(FAILURES)) + ' FAILED: ' + ', '.join(FAILURES)}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
