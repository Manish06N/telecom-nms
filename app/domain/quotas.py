"""Prepaid stops at the pack. Postpaid may go past it and is billed later."""

from decimal import Decimal

from app.domain.enums import BillingType
from app.domain.errors import AppError


def authorize_usage(
    *,
    limit: int,
    already_used: Decimal,
    requested: Decimal,
    billing_type: str,
    unit: str,
) -> str | None:
    """Return 'over_limit' when postpaid exceeds the quota. Refuse otherwise.

    limit -1: unlimited. limit 0: this unit is not in the plan.
    """
    if requested < 0:
        raise AppError(f"{unit} usage cannot be negative", 422, "invalid_usage")
    if requested == 0:
        return None
    if limit == 0:
        raise AppError(f"This plan does not include {unit}", 409, "quota_not_included")
    if limit < 0:
        return None
    projected = already_used + requested
    cap = Decimal(limit)
    if projected <= cap:
        return None
    if billing_type == BillingType.PREPAID:
        remaining = max(Decimal("0"), cap - already_used)
        raise AppError(
            f"Prepaid {unit} quota exceeded. Remaining: {remaining}",
            409,
            "quota_exceeded",
        )
    return "over_limit"


def usage_percent(limit: int, used: Decimal) -> Decimal | None:
    if limit <= 0:
        return None
    percent = (used / Decimal(limit)) * Decimal(100)
    return min(percent, Decimal("999.99")).quantize(Decimal("0.01"))


def remaining_quota(limit: int, used: Decimal) -> Decimal | None:
    if limit < 0:
        return None
    if limit == 0:
        return Decimal("0")
    return max(Decimal("0"), Decimal(limit) - used)
