"""RBAC checks against the *seeded* organisation over real HTTP.

    python tools/smoke_rbac.py --password demo-password

tests/test_rbac.py proves the rules on a two-department fixture. This proves them on the
150-student, 894-session demo database, where a scoping bug has somewhere to hide.
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


def login(c: httpx.Client, username: str, password: str):
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    if r.status_code != 200:
        return None, None
    b = r.json()
    return {"Authorization": f"Bearer {b['access_token']}"}, b["role"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8077")
    ap.add_argument("--password", required=True)
    args = ap.parse_args()

    c = httpx.Client(base_url=args.base, timeout=60.0)

    print("\nsign in")
    principal, r1 = login(c, "principal", args.password)
    hod_cse, _ = login(c, "hod.cse", args.password)
    hod_ece, _ = login(c, "hod.ece", args.password)
    check("super admin signs in", principal is not None and r1 == "super_admin", str(r1))
    check("HOD CSE signs in", hod_cse is not None)
    check("HOD ECE signs in", hod_ece is not None)
    if not (principal and hod_cse and hod_ece):
        print("\nseed missing -- run tools/seed_demo.py first")
        return 1

    # Super admin sees the whole org; each HOD sees a strict subset.
    print("\nsession visibility")
    all_sessions = c.get("/api/sessions", headers=principal).json()
    cse_sessions = c.get("/api/sessions", headers=hod_cse).json()
    ece_sessions = c.get("/api/sessions", headers=hod_ece).json()
    check("super admin sees sessions", len(all_sessions) > 0, str(len(all_sessions)))

    cse_ids = {s["id"] for s in cse_sessions}
    ece_ids = {s["id"] for s in ece_sessions}
    check("HOD session lists are non-empty", bool(cse_ids) and bool(ece_ids),
          f"cse={len(cse_ids)} ece={len(ece_ids)}")

    # The real test: reach into the other department by id.
    print("\ncross-department access")
    ece_only = sorted(ece_ids - cse_ids)
    if ece_only:
        target = ece_only[0]
        r = c.get(f"/api/sessions/{target}/attendance", headers=hod_cse)
        check("HOD CSE blocked from an ECE session", r.status_code == 403,
              f"session {target} -> {r.status_code}")
        r = c.get(f"/api/reports/attendance.csv?session_id={target}", headers=hod_cse)
        check("HOD CSE blocked from ECE csv export", r.status_code == 403, str(r.status_code))
        r = c.post(f"/api/sessions/{target}/recompute", headers=hod_cse)
        check("HOD CSE blocked from ECE recompute", r.status_code == 403, str(r.status_code))
        r = c.get(f"/api/sessions/{target}/attendance", headers=principal)
        check("super admin reaches the same ECE session", r.status_code == 200, str(r.status_code))
    else:
        check("ECE has sessions CSE does not", False, "department lists overlap completely")

    # Every session an HOD can list must actually open.
    print("\nlisted sessions are readable")
    opened = [c.get(f"/api/sessions/{sid}/attendance", headers=hod_cse).status_code
              for sid in sorted(cse_ids)[:12]]
    check("HOD opens every session it listed", all(s == 200 for s in opened), str(opened))

    print("\nstudent scope")
    students = [u for u in c.get("/api/users?q=21", headers=principal).json()
                if u.get("role") == "student"][:2]
    if len(students) >= 2:
        a_h, _ = login(c, students[0]["username"], args.password)
        if a_h:
            check("student blocked from cameras",
                  c.get("/api/cameras", headers=a_h).status_code == 403)
            check("student blocked from live stream",
                  c.get("/api/live/stream", headers=a_h).status_code == 403)
            check("student blocked from audit log",
                  c.get("/api/audit", headers=a_h).status_code == 403)
            body = c.get("/api/dashboard", headers=a_h).json()
            check("student dashboard is self-scoped", body.get("scope") == "self")
            check("student receives no cameras", body.get("cameras") == [])

            mine = c.get("/api/me/attendance", headers=a_h).json()
            check("student sees their own history", len(mine.get("records", [])) > 0,
                  str(len(mine.get("records", []))))

            # Every row returned must belong to this student.
            sids = [s["id"] for s in c.get("/api/sessions", headers=a_h).json()[:5]]
            leaked = 0
            for sid in sids:
                rows = c.get(f"/api/sessions/{sid}/attendance", headers=a_h).json()
                leaked += sum(1 for r in rows.get("records", [])
                              if r["user_id"] != students[0]["id"])
            check("no other student's row leaks into a session view", leaked == 0, str(leaked))
    else:
        check("students found in the seed", False, str(len(students)))

    print("\nparent scope")
    p_h, prole = login(c, f"parent.{students[0]['username']}", args.password) \
        if students else (None, None)
    if p_h:
        check("parent role is parent", prole == "parent", str(prole))
        check("parent blocked from live stream",
              c.get("/api/live/stream", headers=p_h).status_code == 403)
        check("parent blocked from cameras",
              c.get("/api/cameras", headers=p_h).status_code == 403)
        check("parent blocked from audit log",
              c.get("/api/audit", headers=p_h).status_code == 403)
        body = c.get("/api/dashboard", headers=p_h).json()
        check("parent dashboard is self-scoped", body.get("scope") == "self", str(body.get("scope")))
        check("parent receives no cameras", body.get("cameras") == [])
        check("parent is linked to their student",
              body.get("viewing_student_id") == students[0]["id"],
              f"{body.get('viewing_student_id')} != {students[0]['id']}")
    else:
        check("parent account exists", False, "login failed")

    print(f"\n{'ALL PASSED' if not FAILURES else str(len(FAILURES)) + ' FAILED: ' + ', '.join(FAILURES)}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
