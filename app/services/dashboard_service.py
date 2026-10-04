"""Operations totals. Redis is used when configured; the database stays the source of truth."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.cache import cache_get, cache_set
from app.core.config import settings
from app.domain.enums import (
    CustomerStatus,
    OutageStatus,
    SimStatus,
    SubscriptionStatus,
    TicketStatus,
    TowerStatus,
)
from app.models.catalog import ServicePlan
from app.models.customer import Customer
from app.models.inventory import Sim
from app.models.network import Outage, Tower
from app.models.operations import ServiceRequest, Ticket
from app.models.subscription import Subscription, UsageDaily
from app.services.technician_service import workload_board
from app.utils.time import utcnow

CACHE_KEY = "dashboard:operations"


def operations_dashboard(db: Session) -> dict:
    cached = cache_get(CACHE_KEY)
    if cached is not None:
        return cached
    payload = _build(db)
    cache_set(CACHE_KEY, payload, settings.dashboard_cache_seconds)
    return payload


def _count(db, model, *filters) -> int:
    stmt = select(func.count()).select_from(model)
    if filters:
        stmt = stmt.where(*filters)
    return db.scalar(stmt) or 0


def _build(db: Session) -> dict:
    month_start = utcnow().date().replace(day=1)
    data_usage = db.scalar(
        select(func.coalesce(func.sum(UsageDaily.data_mb), 0)).where(UsageDaily.usage_date >= month_start)
    )
    tower_rows = db.execute(select(Tower.status, func.count()).where(Tower.deleted_at.is_(None)).group_by(Tower.status)).all()
    plan_rows = db.execute(
        select(ServicePlan.code, func.count(Subscription.id))
        .join(Subscription, Subscription.plan_id == ServicePlan.id)
        .where(Subscription.status == SubscriptionStatus.ACTIVE.value, ServicePlan.deleted_at.is_(None))
        .group_by(ServicePlan.code)
        .order_by(func.count(Subscription.id).desc())
    ).all()
    open_requests = {
        "submitted",
        "under_review",
        "approved",
        "in_progress",
    }
    return {
        "total_customers": _count(db, Customer, Customer.deleted_at.is_(None)),
        "active_customers": _count(db, Customer, Customer.deleted_at.is_(None), Customer.status == CustomerStatus.ACTIVE.value),
        "active_subscriptions": _count(db, Subscription, Subscription.status == SubscriptionStatus.ACTIVE.value),
        "active_sims": _count(db, Sim, Sim.deleted_at.is_(None), Sim.status == SimStatus.ACTIVE.value),
        "data_usage_mb_this_month": str(data_usage or 0),
        "open_outages": _count(db, Outage, Outage.status != OutageStatus.RESOLVED.value),
        "open_tickets": _count(db, Ticket, Ticket.status.notin_([TicketStatus.RESOLVED.value, TicketStatus.CLOSED.value])),
        "sla_breaches": _count(db, Ticket, Ticket.sla_breached.is_(True), Ticket.status.notin_([TicketStatus.RESOLVED.value, TicketStatus.CLOSED.value])),
        "open_service_requests": _count(db, ServiceRequest, ServiceRequest.status.in_(open_requests)),
        "tower_status": {status: count for status, count in tower_rows},
        "plan_utilization": [{"plan_code": code, "active_subscriptions": count} for code, count in plan_rows],
        "technician_workload": [
            {
                "technician_id": str(item["technician_id"]),
                "employee_code": item["employee_code"],
                "availability": item["availability"],
                "pending_jobs": item["pending_jobs"],
                "completed_jobs": item["completed_jobs"],
            }
            for item in workload_board(db)
        ],
        "generated_at": utcnow().isoformat(),
    }


def tower_status_counts(db: Session) -> dict[str, int]:
    rows = db.execute(
        select(Tower.status, func.count()).where(Tower.deleted_at.is_(None)).group_by(Tower.status)
    ).all()
    base = {status.value: 0 for status in TowerStatus}
    for status, count in rows:
        base[status] = count
    return base
