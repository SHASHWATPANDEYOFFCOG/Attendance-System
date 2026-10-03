"""Server-side input validation shared by sign-up, profile edits and bulk import.

Every rule returns a message a student can act on. The browser runs the same checks for instant
feedback, but these are the ones that count.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Optional

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
ROLL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/\-_.]{0,31}$")
GENDERS = ("female", "male", "non_binary", "prefer_not_to_say", "other")


class Invalid(ValueError):
    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field
        self.message = message


def email(value: Optional[str], field: str = "email", required: bool = True) -> Optional[str]:
    v = (value or "").strip().lower()
    if not v:
        if required:
            raise Invalid(field, "Email is required.")
        return None
    if len(v) > 200 or not EMAIL_RE.match(v):
        raise Invalid(field, "Enter a valid email address, e.g. name@college.edu.")
    return v


def phone(value: Optional[str], field: str = "mobile", required: bool = True) -> Optional[str]:
    raw = (value or "").strip()
    if not raw:
        if required:
            raise Invalid(field, "Mobile number is required.")
        return None
    digits = re.sub(r"[\s\-()]", "", raw)
    if not re.fullmatch(r"\+?\d{10,15}", digits):
        raise Invalid(field, "Enter a 10–15 digit mobile number (country code optional).")
    # Indian 10-digit numbers are stored with +91 so "98765 43210" and "+919876543210" match.
    if re.fullmatch(r"[6-9]\d{9}", digits):
        digits = "+91" + digits
    elif not digits.startswith("+"):
        digits = "+" + digits
    return digits


def password(value: str, field: str = "password") -> str:
    v = value or ""
    if len(v) < 8:
        raise Invalid(field, "Use at least 8 characters.")
    if len(v) > 128:
        raise Invalid(field, "Use at most 128 characters.")
    if not re.search(r"[A-Za-z]", v) or not re.search(r"\d", v):
        raise Invalid(field, "Use at least one letter and one number.")
    return v


def name(value: Optional[str], field: str = "full_name", required: bool = True,
         max_len: int = 128) -> Optional[str]:
    v = re.sub(r"\s+", " ", (value or "").strip())
    if not v:
        if required:
            raise Invalid(field, "This field is required.")
        return None
    if len(v) > max_len:
        raise Invalid(field, f"Use at most {max_len} characters.")
    if re.search(r"[<>{}\\]", v):
        raise Invalid(field, "Remove the special characters < > { } \\.")
    return v


def roll(value: Optional[str], field: str = "roll_number") -> str:
    v = (value or "").strip().upper()
    if not v:
        raise Invalid(field, "Roll number is required.")
    if not ROLL_RE.match(v):
        raise Invalid(field, "Use letters, digits and - / _ . only (max 32).")
    return v


def dob(value, field: str = "dob", required: bool = True) -> Optional[date]:
    if value in (None, ""):
        if required:
            raise Invalid(field, "Date of birth is required.")
        return None
    try:
        d = value if isinstance(value, date) else date.fromisoformat(str(value))
    except ValueError:
        raise Invalid(field, "Use the date picker (YYYY-MM-DD).")
    today = date.today()
    age = today.year - d.year - ((today.month, today.day) < (d.month, d.day))
    if age < 14 or age > 80:
        raise Invalid(field, "Check the year — that age does not look right for a student.")
    return d


def gender(value: Optional[str], field: str = "gender", required: bool = True) -> Optional[str]:
    v = (value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if not v:
        if required:
            raise Invalid(field, "Select an option.")
        return None
    if v not in GENDERS:
        raise Invalid(field, "Select one of the listed options.")
    return v


def text(value: Optional[str], field: str, max_len: int, required: bool = False,
         min_len: int = 0) -> Optional[str]:
    v = (value or "").strip()
    if not v:
        if required:
            raise Invalid(field, "This field is required.")
        return None
    if len(v) < min_len:
        raise Invalid(field, f"Write at least {min_len} characters.")
    if len(v) > max_len:
        raise Invalid(field, f"Use at most {max_len} characters.")
    return v
