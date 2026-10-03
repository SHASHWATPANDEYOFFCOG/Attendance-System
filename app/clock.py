"""One definition of "today".

Every *instant* in this system is stored UTC — that rule is not negotiable and is enforced by
`UTCDateTime` in models.py. But a **calendar day** is a local concept: "today's timetable",
"the register for today", "today's absentees" all mean today *where the college is*, not today
in UTC.

Conflating the two is a real bug, not a theoretical one. In Asia/Kolkata (UTC+05:30) the UTC
date is the previous day between 00:00 and 05:29 local, and on a Monday morning that is also
the previous *weekday*:

    IST 00:38 Mon  ->  UTC 2026-08-02 19:08 Sun
    IST 05:29 Mon  ->  UTC 2026-08-02 23:59 Sun
    IST 05:31 Mon  ->  UTC 2026-08-03 00:01 Mon

So a teacher opening the app before 05:30 would be shown Sunday's (empty) timetable on a Monday,
and opening a register would be refused by the weekday guard. Anything that means "today" must
go through `local_today`.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

from occlubio.utils import get_logger

log = get_logger("app.clock")

_warned: set[str] = set()


def zone(tz: str):
    """Resolve a timezone name, falling back to UTC rather than failing the request.

    A bad config value should degrade to something defensible, not take the app down — but it
    warns once per name so it does not pass unnoticed.
    """
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(tz)
    except Exception:                                    # noqa: BLE001 - bad name or no tzdata
        if tz not in _warned:
            _warned.add(tz)
            log.warning("unknown timezone %r; falling back to UTC", tz)
        return timezone.utc


def local_now(tz: str) -> datetime:
    """The current instant, expressed in the organisation's zone."""
    return datetime.now(timezone.utc).astimezone(zone(tz))


def local_today(tz: str) -> date:
    """Today's calendar date where the organisation is. Use this, never `.date()` on a UTC now."""
    return local_now(tz).date()


def tz_of(cfg) -> str:
    return str(getattr(cfg.attendance, "timezone", "UTC"))
