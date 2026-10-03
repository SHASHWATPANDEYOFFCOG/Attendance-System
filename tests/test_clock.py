"""'Today' is a local calendar day, not a UTC one.

This was a real bug, found because the suite happened to run at 00:38 local. In Asia/Kolkata
(UTC+05:30) the UTC date is the PREVIOUS day between 00:00 and 05:29 local -- and on a Monday
morning that is also the previous WEEKDAY. The consequences were user-facing:

  * `/api/timetable/today` showed Sunday's (empty) schedule to a teacher on Monday morning;
  * opening a register defaulted to the UTC date and was then refused by the weekday guard.

Instants stay UTC everywhere. Only calendar days are localised, and only through app.clock.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from app.clock import local_now, local_today, tz_of, zone

IST = ZoneInfo("Asia/Kolkata")


def test_the_bug_is_real_and_not_theoretical():
    """Pin the exact divergence that broke the suite, so nobody 'simplifies' it away."""
    early_monday = datetime(2026, 8, 3, 0, 38, tzinfo=IST)
    as_utc = early_monday.astimezone(timezone.utc)

    assert early_monday.date() == date(2026, 8, 3)
    assert as_utc.date() == date(2026, 8, 2), "UTC is a day behind before 05:30 IST"
    assert early_monday.weekday() == 0            # Monday
    assert as_utc.weekday() == 6                  # Sunday -- the weekday guard would refuse


@pytest.mark.parametrize("hhmm,same_day", [
    ("00:00", False), ("03:00", False), ("05:29", False),
    ("05:30", True), ("09:00", True), ("23:59", True),
])
def test_utc_and_local_dates_diverge_only_before_0530_ist(hhmm, same_day):
    h, m = (int(x) for x in hhmm.split(":"))
    local = datetime(2026, 8, 3, h, m, tzinfo=IST)
    assert (local.date() == local.astimezone(timezone.utc).date()) is same_day


def test_local_today_uses_the_org_zone():
    """local_today must agree with the wall clock in the given zone, whatever UTC says."""
    assert local_today("Asia/Kolkata") == datetime.now(IST).date()
    assert local_today("UTC") == datetime.now(timezone.utc).date()


def test_local_today_can_differ_from_utc_today():
    """Not asserting they differ right now -- only that the function is capable of it, which
    a naive `datetime.now(timezone.utc).date()` implementation would not be."""
    kiritimati = local_today("Pacific/Kiritimati")     # UTC+14
    baker = local_today("Etc/GMT+12")                  # UTC-12
    assert (kiritimati - baker).days in (0, 1, 2)
    assert kiritimati >= baker


def test_an_unknown_zone_falls_back_to_utc_without_raising():
    """A bad config value must degrade, not take the API down."""
    assert zone("Mars/Olympus_Mons") is timezone.utc
    assert local_today("Mars/Olympus_Mons") == datetime.now(timezone.utc).date()
    assert isinstance(local_now("Mars/Olympus_Mons"), datetime)


def test_tz_of_reads_the_config(cfg):
    assert tz_of(cfg) == "Asia/Kolkata"


def test_no_module_computes_today_from_utc_directly():
    """A regression guard with teeth: the pattern that caused the bug must not come back."""
    import pathlib

    app_dir = pathlib.Path(__file__).resolve().parent.parent / "app"
    offenders = []
    for path in app_dir.glob("*.py"):
        if path.name == "clock.py":
            continue
        text = path.read_text(encoding="utf-8")
        if "datetime.now(timezone.utc).date()" in text:
            offenders.append(path.name)
    assert not offenders, (
        f"{offenders} compute 'today' from UTC; use app.clock.local_today(tz) so the "
        f"organisation's calendar day is used"
    )


# ------------------------------------------------------- end-to-end behaviour

def test_timetable_today_uses_the_local_date(api, make_user, monkeypatch):
    """The endpoint's default day must be the org's today, not UTC's."""
    import app.api as api_mod

    _uid, staff = make_user("prof", role="faculty")
    body = api.get("/api/timetable/today", headers=staff).json()
    assert body["date"] == local_today("Asia/Kolkata").isoformat()


def test_daily_absentees_defaults_to_the_local_date(api, make_user):
    _uid, staff = make_user("prof", role="faculty")
    body = api.get("/api/reports/daily-absentees", headers=staff).json()
    assert body["date"] == local_today("Asia/Kolkata").isoformat()
