"""SLA deadlines are chosen when the ticket is opened, not typed in by the agent."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import EscalationStatus, NotificationEvent, TicketStatus
from app.domain.errors import AppError
from app.domain.sla import PolicyView, choose_policy
from app.models.identity import User
from app.models.operations import SlaPolicy, Ticket
from app.services.records import notify
from app.utils.time import utcnow

OPEN = {
    TicketStatus.OPEN.value,
    TicketStatus.ASSIGNED.value,
    TicketStatus.IN_PROGRESS.value,
    TicketStatus.WAITING_FOR_CUSTOMER.value,
}


def policies(db: Session):
    return list(db.scalars(select(SlaPolicy).where(SlaPolicy.is_active.is_(True)).order_by(SlaPolicy.resolution_minutes)).all())


def resolve_policy(db: Session, ticket_type: str, priority: str, customer_type: str) -> SlaPolicy:
    rows = policies(db)
    views = [
        PolicyView(row.ticket_type, row.priority, row.customer_type, row.resolution_minutes, row.name) for row in rows
    ]
    try:
        chosen = choose_policy(views, ticket_type, priority, customer_type)
    except LookupError as exc:
        raise AppError("No SLA policy is configured", 400, "sla_not_configured") from exc
    for row in rows:
        if (
            row.ticket_type == chosen.ticket_type
            and row.priority == chosen.priority
            and row.customer_type == chosen.customer_type
            and row.resolution_minutes == chosen.resolution_minutes
            and row.name == chosen.name
        ):
            return row
    raise AppError("No SLA policy is configured", 400, "sla_not_configured")


def deadline_for(policy: SlaPolicy, started):
    return started + timedelta(minutes=policy.resolution_minutes)


def create_policy(db: Session, actor: User, data) -> SlaPolicy:
    row = SlaPolicy(
        name=data.name.strip(),
        ticket_type=data.ticket_type.value if data.ticket_type else None,
        priority=data.priority.value if data.priority else None,
        customer_type=data.customer_type.value if data.customer_type else None,
        resolution_minutes=data.resolution_minutes,
        is_active=True,
    )
    db.add(row)
    db.flush()
    return row


def mark_breaches(db: Session, background_tasks=None) -> int:
    now = utcnow()
    rows = db.scalars(
        select(Ticket).where(
            Ticket.sla_breached.is_(False),
            Ticket.sla_deadline.is_not(None),
            Ticket.sla_deadline < now,
            Ticket.status.in_(OPEN),
        )
    ).all()
    for ticket in rows:
        _flag(db, ticket)
    if rows:
        from app.services.records import spawn

        spawn(background_tasks)
    return len(list(rows))


def flag_if_late(db: Session, ticket: Ticket) -> bool:
    if ticket.sla_breached or ticket.sla_deadline is None:
        return False
    if ticket.status not in OPEN:
        return False
    if ticket.sla_deadline >= utcnow():
        return False
    _flag(db, ticket)
    return True


def _flag(db: Session, ticket: Ticket) -> None:
    ticket.sla_breached = True
    ticket.escalation_status = EscalationStatus.BREACHED.value
    recipient = ticket.assigned_agent_id or ticket.created_by
    notify(
        db,
        recipient,
        NotificationEvent.SLA_BREACH,
        f"SLA breached on {ticket.code}",
        ticket.subject,
        {"ticket_id": str(ticket.id)},
    )


def watch(db: Session, within_minutes: int, background_tasks=None) -> dict:
    mark_breaches(db, background_tasks)
    now = utcnow()
    horizon = now + timedelta(minutes=within_minutes)
    open_rows = db.scalars(select(Ticket).where(Ticket.status.in_(OPEN), Ticket.sla_deadline.is_not(None))).all()
    breached = [row for row in open_rows if row.sla_breached or (row.sla_deadline and row.sla_deadline < now)]
    soon = [
        row
        for row in open_rows
        if not row.sla_breached and row.sla_deadline and now <= row.sla_deadline <= horizon
    ]
    return {"breached": breached, "soon": soon}
