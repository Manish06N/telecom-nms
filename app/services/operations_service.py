"""Jobs that a scheduler, Celery, or a staff member can run on demand."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import NotificationEvent, SubscriptionEventType, SubscriptionStatus
from app.models.network import Equipment
from app.models.subscription import Subscription, SubscriptionEvent
from app.services import sla_service
from app.services.network_service import _maintenance_notice
from app.services.records import notify
from app.utils.time import utcnow


def run_schedules(db: Session, background_tasks=None) -> dict:
    breaches = sla_service.mark_breaches(db, background_tasks)
    expired = _expire_subscriptions(db)
    activated = _activate_pending(db)
    expiry_notices = _warn_expiring(db)
    maintenance = _scan_maintenance(db)
    return {
        "sla_breaches_marked": breaches,
        "subscriptions_expired": expired,
        "subscriptions_activated": activated,
        "expiry_notifications": expiry_notices,
        "maintenance_notifications": maintenance,
    }


def _expire_subscriptions(db: Session) -> int:
    now = utcnow()
    rows = db.scalars(
        select(Subscription).where(
            Subscription.status.in_([SubscriptionStatus.ACTIVE.value, SubscriptionStatus.PENDING.value]),
            Subscription.cycle_end < now,
        )
    ).all()
    count = 0
    for sub in rows:
        if sub.status == SubscriptionStatus.PENDING.value and sub.start_date > now:
            continue
        sub.status = SubscriptionStatus.EXPIRED.value
        db.add(
            SubscriptionEvent(
                subscription_id=sub.id,
                event_type=SubscriptionEventType.EXPIRED.value,
                to_plan_id=sub.plan_id,
                note="cycle ended",
            )
        )
        count += 1
    return count


def _activate_pending(db: Session) -> int:
    now = utcnow()
    rows = db.scalars(
        select(Subscription).where(Subscription.status == SubscriptionStatus.PENDING.value, Subscription.start_date <= now, Subscription.cycle_end >= now)
    ).all()
    for sub in rows:
        sub.status = SubscriptionStatus.ACTIVE.value
    return len(list(rows))


def _warn_expiring(db: Session) -> int:
    from app.core.config import settings

    horizon = utcnow() + timedelta(days=settings.plan_expiry_warning_days)
    rows = db.scalars(
        select(Subscription).where(
            Subscription.status == SubscriptionStatus.ACTIVE.value,
            Subscription.expiry_notified.is_(False),
            Subscription.cycle_end <= horizon,
        )
    ).all()
    sent = 0
    for sub in rows:
        sub.expiry_notified = True
        if sub.customer.user_id:
            notify(
                db,
                sub.customer.user_id,
                NotificationEvent.PLAN_EXPIRY,
                "Plan expiring soon",
                f"Subscription {sub.code} ends on {sub.cycle_end.isoformat()}.",
                {"subscription_id": str(sub.id)},
            )
            sent += 1
    return sent


def _scan_maintenance(db: Session) -> int:
    rows = db.scalars(select(Equipment).where(Equipment.maintenance_notified.is_(False))).all()
    sent = 0
    for item in rows:
        before = item.maintenance_notified
        _maintenance_notice(db, item)
        if item.maintenance_notified and not before:
            sent += 1
    return sent
