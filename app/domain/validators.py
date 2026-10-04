"""Format rules that do not need the database."""

import re
from datetime import date

from app.domain.errors import AppError

MSISDN_RE = re.compile(r"^\+[1-9]\d{9,14}$")
INDIA_LOCAL_RE = re.compile(r"^[6-9]\d{9}$")


def luhn_valid(number: str) -> bool:
    """IMEI check digit. From the right, double every second digit."""
    total = 0
    for index, char in enumerate(number[::-1]):
        digit = int(char)
        if index % 2 == 1:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def validate_imei(value: str) -> str:
    digits = value.strip().replace(" ", "")
    if len(digits) != 15 or not digits.isdigit():
        raise AppError("IMEI must be exactly 15 digits", 422, "invalid_imei")
    if not luhn_valid(digits):
        raise AppError("IMEI failed the Luhn check", 422, "invalid_imei")
    return digits


def validate_iccid(value: str) -> str:
    digits = value.strip().replace(" ", "")
    if not digits.isdigit() or not 18 <= len(digits) <= 22:
        raise AppError("ICCID must be 18 to 22 digits", 422, "invalid_iccid")
    return digits


def normalize_msisdn(value: str) -> str:
    """Store one canonical form. A 10-digit Indian mobile becomes +91..."""
    raw = value.strip().replace(" ", "").replace("-", "")
    if INDIA_LOCAL_RE.fullmatch(raw):
        raw = "+91" + raw
    if raw.startswith("00"):
        raw = "+" + raw[2:]
    if not MSISDN_RE.fullmatch(raw):
        raise AppError("Enter a valid mobile number in international form", 422, "invalid_msisdn")
    return raw


def assert_adult(dob: date, today: date | None = None) -> None:
    today = today or date.today()
    if dob > today:
        raise AppError("Date of birth cannot be in the future", 422, "invalid_dob")
    years = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    if years < 18:
        raise AppError("An individual customer must be at least 18", 400, "underage")


def quota_included(limit: int) -> bool:
    """0 means the plan does not include this service. -1 means unlimited."""
    return limit != 0
