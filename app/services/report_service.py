"""Date-bounded reports. Filters that do not apply to a report are ignored."""

import csv
import io
from datetime import date, datetime, time, timedelta

from openpyxl import Workbook
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.enums import SubscriptionEventType
from app.domain.uptime import downtime_minutes, uptime_percent
from app.models.catalog import ServicePlan
from app.models.customer import Customer, CustomerAddress
from app.models.network import Outage, Tower, outage_towers
from app.models.operations import ServiceRequest, Technician, Ticket
from app.models.subscription import Subscription, SubscriptionEvent, UsageDaily
from app.utils.time import utcnow


def resolve_range(date_from: date | None, date_to: date | None, default_days: int = 30) -> tuple[datetime, datetime]:
    end_day = date_to or utcnow().date()
    start_day = date_from or (end_day - timedelta(days=default_days))
    if start_day > end_day:
        from app.domain.errors import AppError

        raise AppError("date_from cannot be after date_to", 400, "invalid_date_range")
    start = datetime.combine(start_day, time.min)
    end = datetime.combine(end_day + timedelta(days=1), time.min)
    return start, end


def customer_growth(db: Session, start: datetime, end: datetime, city: str | None) -> list[dict]:
    day = func.date(Customer.created_at)
    stmt = select(day, func.count()).where(Customer.deleted_at.is_(None), Customer.created_at >= start, Customer.created_at < end)
    if city:
        stmt = stmt.where(
            Customer.id.in_(select(CustomerAddress.customer_id).where(CustomerAddress.city.ilike(city.strip())))
        )
    rows = db.execute(stmt.group_by(day).order_by(day)).all()
    return [{"date": str(value), "new_customers": count} for value, count in rows]


def subscription_trends(db: Session, start: datetime, end: datetime, plan_id=None) -> list[dict]:
    created_day = func.date(Subscription.created_at)
    created = select(created_day, func.count()).where(Subscription.created_at >= start, Subscription.created_at < end)
    if plan_id:
        created = created.where(Subscription.plan_id == plan_id)
    created_rows = {str(day): count for day, count in db.execute(created.group_by(created_day)).all()}
    cancelled_day = func.date(Subscription.cancelled_at)
    cancelled = select(cancelled_day, func.count()).where(
        Subscription.cancelled_at.is_not(None),
        Subscription.cancelled_at >= start,
        Subscription.cancelled_at < end,
    )
    if plan_id:
        cancelled = cancelled.where(Subscription.plan_id == plan_id)
    cancelled_rows = {str(day): count for day, count in db.execute(cancelled.group_by(cancelled_day)).all()}
    days = sorted(set(created_rows) | set(cancelled_rows))
    return [
        {"date": day, "new_subscriptions": created_rows.get(day, 0), "cancelled_subscriptions": cancelled_rows.get(day, 0)}
        for day in days
    ]


def plan_popularity(db: Session, start: datetime, end: datetime, plan_id=None) -> list[dict]:
    stmt = (
        select(ServicePlan.code, ServicePlan.name, func.count(Subscription.id))
        .join(Subscription, Subscription.plan_id == ServicePlan.id)
        .where(Subscription.created_at >= start, Subscription.created_at < end)
        .group_by(ServicePlan.code, ServicePlan.name)
        .order_by(func.count(Subscription.id).desc())
    )
    if plan_id:
        stmt = stmt.where(ServicePlan.id == plan_id)
    return [{"plan_code": code, "plan_name": name, "subscriptions": count} for code, name, count in db.execute(stmt).all()]


def data_consumption(db: Session, start: datetime, end: datetime, customer_id=None, plan_id=None, city: str | None = None) -> list[dict]:
    day = func.date(UsageDaily.usage_date)
    stmt = (
        select(day, func.coalesce(func.sum(UsageDaily.data_mb), 0))
        .where(UsageDaily.usage_date >= start.date(), UsageDaily.usage_date < end.date())
    )
    if customer_id:
        stmt = stmt.where(UsageDaily.customer_id == customer_id)
    if plan_id:
        stmt = stmt.join(Subscription, Subscription.id == UsageDaily.subscription_id).where(Subscription.plan_id == plan_id)
    if city:
        stmt = stmt.where(
            UsageDaily.customer_id.in_(
                select(CustomerAddress.customer_id).where(CustomerAddress.city.ilike(city.strip()))
            )
        )
    rows = db.execute(stmt.group_by(day).order_by(day)).all()
    return [{"date": str(value), "data_mb": str(total)} for value, total in rows]


def network_uptime(db: Session, start: datetime, end: datetime, city: str | None = None) -> list[dict]:
    towers = select(Tower).where(Tower.deleted_at.is_(None))
    if city:
        towers = towers.where(Tower.city.ilike(city.strip()))
    result = []
    for tower in db.scalars(towers).all():
        windows = db.execute(
            select(Outage.start_time, func.coalesce(Outage.actual_resolution, end))
            .join(outage_towers, outage_towers.c.outage_id == Outage.id)
            .where(outage_towers.c.tower_id == tower.id, Outage.start_time < end)
        ).all()
        clipped = [(begin, finish if finish is not None else end) for begin, finish in windows]
        down = downtime_minutes(clipped, start, end)
        result.append(
            {
                "tower_code": tower.tower_code,
                "city": tower.city,
                "downtime_minutes": round(down, 2),
                "uptime_percent": uptime_percent(down, start, end),
            }
        )
    return result


def outage_frequency(db: Session, start: datetime, end: datetime, city: str | None = None) -> list[dict]:
    stmt = select(Outage.outage_type, Outage.severity, func.count()).where(Outage.start_time >= start, Outage.start_time < end)
    if city:
        stmt = (
            stmt.join(outage_towers, outage_towers.c.outage_id == Outage.id)
            .join(Tower, Tower.id == outage_towers.c.tower_id)
            .where(Tower.city.ilike(city.strip()))
        )
    rows = db.execute(stmt.group_by(Outage.outage_type, Outage.severity).order_by(func.count().desc())).all()
    return [{"outage_type": kind, "severity": severity, "count": count} for kind, severity, count in rows]


def ticket_resolution(db: Session, start: datetime, end: datetime, status: str | None = None, customer_id=None) -> dict:
    stmt = select(Ticket).where(Ticket.resolved_at.is_not(None), Ticket.resolved_at >= start, Ticket.resolved_at < end)
    if status:
        stmt = stmt.where(Ticket.status == status)
    if customer_id:
        stmt = stmt.where(Ticket.customer_id == customer_id)
    rows = list(db.scalars(stmt).all())
    hours = [((row.resolved_at - row.created_at).total_seconds() / 3600) for row in rows if row.resolved_at]
    average = round(sum(hours) / len(hours), 2) if hours else 0
    return {
        "resolved_tickets": len(rows),
        "average_resolution_hours": average,
        "items": [
            {"code": row.code, "ticket_type": row.ticket_type, "priority": row.priority, "resolution_hours": round((row.resolved_at - row.created_at).total_seconds() / 3600, 2)}
            for row in rows
        ],
    }


def sla_performance(db: Session, start: datetime, end: datetime, customer_id=None) -> dict:
    stmt = select(Ticket).where(Ticket.created_at >= start, Ticket.created_at < end)
    if customer_id:
        stmt = stmt.where(Ticket.customer_id == customer_id)
    rows = list(db.scalars(stmt).all())
    finished = [row for row in rows if row.status in {"resolved", "closed"}]
    breached = [row for row in rows if row.sla_breached]
    rate = round((len(breached) / len(rows)) * 100, 2) if rows else 0
    return {
        "tickets": len(rows),
        "finished": len(finished),
        "breached": len(breached),
        "breach_rate_percent": rate,
    }


def technician_performance(db: Session, start: datetime, end: datetime) -> list[dict]:
    techs = list(db.scalars(select(Technician)).all())
    report = []
    for tech in techs:
        rows = list(
            db.scalars(
                select(Ticket).where(
                    Ticket.assigned_technician_id == tech.id,
                    Ticket.resolved_at.is_not(None),
                    Ticket.resolved_at >= start,
                    Ticket.resolved_at < end,
                )
            ).all()
        )
        hours = [((row.resolved_at - row.created_at).total_seconds() / 3600) for row in rows]
        report.append(
            {
                "employee_code": tech.employee_code,
                "completed_jobs": len(rows),
                "average_resolution_hours": round(sum(hours) / len(hours), 2) if hours else 0,
            }
        )
    report.sort(key=lambda item: item["completed_jobs"], reverse=True)
    return report


def service_trends(db: Session, start: datetime, end: datetime, customer_id=None) -> dict:
    ticket_stmt = select(Ticket.ticket_type, func.count()).where(Ticket.created_at >= start, Ticket.created_at < end)
    request_stmt = select(ServiceRequest.request_type, func.count()).where(
        ServiceRequest.created_at >= start, ServiceRequest.created_at < end
    )
    if customer_id:
        ticket_stmt = ticket_stmt.where(Ticket.customer_id == customer_id)
        request_stmt = request_stmt.where(ServiceRequest.customer_id == customer_id)
    upgrades = db.scalar(
        select(func.count()).select_from(SubscriptionEvent).where(
            SubscriptionEvent.event_type == SubscriptionEventType.UPGRADED.value,
            SubscriptionEvent.created_at >= start,
            SubscriptionEvent.created_at < end,
        )
    ) or 0
    return {
        "tickets_by_type": [{"ticket_type": kind, "count": count} for kind, count in db.execute(ticket_stmt.group_by(Ticket.ticket_type)).all()],
        "requests_by_type": [{"request_type": kind, "count": count} for kind, count in db.execute(request_stmt.group_by(ServiceRequest.request_type)).all()],
        "plan_upgrades": upgrades,
    }


def page_rows(rows: list, page: int, page_size: int) -> dict:
    total = len(rows)
    start = (page - 1) * page_size
    return {"items": rows[start : start + page_size], "total": total, "page": page, "page_size": page_size}


def rows_to_csv(rows: list[dict]) -> str:
    buffer = io.StringIO()
    if not rows:
        return ""
    writer = csv.DictWriter(buffer, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def rows_to_xlsx(rows: list[dict]) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "report"
    if rows:
        sheet.append(list(rows[0].keys()))
        for row in rows:
            sheet.append([_cell(row[key]) for key in rows[0].keys()])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def _cell(value):
    if isinstance(value, (dict, list)):
        return str(value)
    return value
