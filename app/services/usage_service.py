"""Daily rows are the source of truth. Monthly figures and percentages are sums over a cycle."""

from datetime import date
from decimal import Decimal

from sqlalchemy import extract, func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.domain.enums import BillingType, NotificationEvent, SubscriptionStatus
from app.domain.errors import AppError
from app.domain.quotas import authorize_usage, remaining_quota, usage_percent
from app.models.identity import User
from app.models.inventory import Sim
from app.models.subscription import Subscription, UsageDaily
from app.services.records import notify, spawn
from app.services.subscription_service import get_subscription

ZERO = Decimal("0")


def _sums(db: Session, subscription: Subscription) -> tuple[Decimal, Decimal, int]:
    start = subscription.cycle_start.date()
    end = subscription.cycle_end.date()
    row = db.execute(
        select(
            func.coalesce(func.sum(UsageDaily.data_mb), 0),
            func.coalesce(func.sum(UsageDaily.voice_minutes), 0),
            func.coalesce(func.sum(UsageDaily.sms_count), 0),
        ).where(
            UsageDaily.subscription_id == subscription.id,
            UsageDaily.usage_date >= start,
            UsageDaily.usage_date <= end,
        )
    ).one()
    return Decimal(row[0]), Decimal(row[1]), int(row[2])


def utilization(db: Session, actor: User, subscription_id) -> dict:
    sub = get_subscription(db, actor, subscription_id)
    data_used, voice_used, sms_used = _sums(db, sub)
    plan = sub.plan
    return {
        "subscription_id": sub.id,
        "plan_code": plan.code,
        "cycle_start": sub.cycle_start,
        "cycle_end": sub.cycle_end,
        "data": _bucket(plan.data_limit_mb, data_used),
        "voice": _bucket(plan.voice_limit_minutes, voice_used),
        "sms": _bucket(plan.sms_limit, Decimal(sms_used)),
    }


def _bucket(limit: int, used: Decimal) -> dict:
    return {
        "limit": limit,
        "used": used,
        "remaining": remaining_quota(limit, used),
        "percent": usage_percent(limit, used),
        "unlimited": limit < 0,
        "included": limit != 0,
    }


def record_usage(db: Session, actor: User, data, background_tasks=None) -> dict:
    sim = db.get(Sim, data.sim_id)
    if sim is None or sim.deleted_at is not None:
        raise AppError("SIM not found", 404, "not_found")
    sub = db.scalar(
        select(Subscription).where(
            Subscription.sim_id == sim.id,
            Subscription.status == SubscriptionStatus.ACTIVE.value,
        )
    )
    if sub is None:
        raise AppError("This SIM has no active subscription", 409, "no_active_subscription")
    usage_day: date = data.usage_date
    if not (sub.cycle_start.date() <= usage_day <= sub.cycle_end.date()):
        raise AppError("Usage date is outside the current billing cycle", 409, "outside_cycle")
    data_used, voice_used, sms_used = _sums(db, sub)
    flags = []
    for flag in (
        authorize_usage(
            limit=sub.plan.data_limit_mb,
            already_used=data_used,
            requested=data.data_mb,
            billing_type=sub.plan.billing_type,
            unit="data",
        ),
        authorize_usage(
            limit=sub.plan.voice_limit_minutes,
            already_used=voice_used,
            requested=data.voice_minutes,
            billing_type=sub.plan.billing_type,
            unit="voice",
        ),
        authorize_usage(
            limit=sub.plan.sms_limit,
            already_used=Decimal(sms_used),
            requested=Decimal(data.sms_count),
            billing_type=sub.plan.billing_type,
            unit="SMS",
        ),
    ):
        if flag:
            flags.append(flag)

    row = db.scalar(
        select(UsageDaily).where(UsageDaily.sim_id == sim.id, UsageDaily.usage_date == usage_day)
    )
    if row is None:
        row = UsageDaily(
            subscription_id=sub.id,
            sim_id=sim.id,
            customer_id=sub.customer_id,
            usage_date=usage_day,
            data_mb=ZERO,
            voice_minutes=ZERO,
            sms_count=0,
        )
        db.add(row)
    row.data_mb = Decimal(row.data_mb) + data.data_mb
    row.voice_minutes = Decimal(row.voice_minutes) + data.voice_minutes
    row.sms_count = int(row.sms_count) + data.sms_count
    db.flush()

    fresh = utilization(db, actor, sub.id)
    _maybe_threshold(db, sub, fresh, background_tasks)
    fresh["over_limit"] = sub.plan.billing_type == BillingType.POSTPAID.value and bool(flags)
    fresh["usage_date"] = usage_day
    return fresh


def _maybe_threshold(db, sub: Subscription, fresh: dict, background_tasks) -> None:
    if sub.threshold_notified:
        return
    percents = [bucket["percent"] for bucket in (fresh["data"], fresh["voice"], fresh["sms"]) if bucket["percent"] is not None]
    if not percents or max(percents) < settings.usage_alert_percent:
        return
    sub.threshold_notified = True
    customer = sub.customer
    if customer.user_id:
        notify(
            db,
            customer.user_id,
            NotificationEvent.USAGE_THRESHOLD,
            "Usage threshold reached",
            f"Subscription {sub.code} has used at least {settings.usage_alert_percent}% of a quota.",
            {"subscription_id": str(sub.id)},
        )
        spawn(background_tasks)


def customer_usage(db: Session, actor: User, customer_id, month: str | None):
    from app.services.customer_service import get_customer

    customer = get_customer(db, actor, customer_id)
    stmt = select(UsageDaily).where(UsageDaily.customer_id == customer.id)
    stmt = _month_filter(stmt, month)
    rows = list(db.scalars(stmt.order_by(UsageDaily.usage_date.desc())).all())
    return {"customer_id": customer.id, "items": rows, "totals": _totals(rows)}


def sim_usage(db: Session, actor: User, sim_id, month: str | None):
    from app.services.sim_service import get_sim

    sim = get_sim(db, actor, sim_id)
    stmt = select(UsageDaily).where(UsageDaily.sim_id == sim.id)
    stmt = _month_filter(stmt, month)
    rows = list(db.scalars(stmt.order_by(UsageDaily.usage_date.desc())).all())
    return {"sim_id": sim.id, "items": rows, "totals": _totals(rows)}


def _month_filter(stmt, month: str | None):
    if not month:
        return stmt
    try:
        year_text, month_text = month.split("-")
        year, month_number = int(year_text), int(month_text)
    except ValueError as exc:
        raise AppError("month must look like 2026-09", 422, "invalid_month") from exc
    if not 1 <= month_number <= 12:
        raise AppError("month must look like 2026-09", 422, "invalid_month")
    return stmt.where(extract("year", UsageDaily.usage_date) == year, extract("month", UsageDaily.usage_date) == month_number)


def _totals(rows: list[UsageDaily]) -> dict:
    return {
        "data_mb": sum((row.data_mb for row in rows), ZERO),
        "voice_minutes": sum((row.voice_minutes for row in rows), ZERO),
        "sms_count": sum(row.sms_count for row in rows),
    }
