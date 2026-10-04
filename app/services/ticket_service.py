"""Tickets move through a fixed status map. Agents do not type the next status as a free string."""

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.domain.enums import Availability, Priority, Role, TicketStatus
from app.domain.errors import AppError
from app.domain.skills import skill_covers
from app.domain.transitions import TICKET_TRANSITIONS, assert_transition, bump_priority
from app.models.customer import CustomerAddress
from app.models.identity import User
from app.models.operations import Technician, Ticket, TicketComment, TicketEvent
from app.repositories.common import apply_sort, next_code, paginate
from app.services import sla_service, technician_service
from app.services.access import assert_customer_visible, is_customer, require_linked_customer
from app.services.records import log_action, notify, spawn
from app.domain.enums import NotificationEvent
from app.utils.time import utcnow

TERMINAL = {TicketStatus.RESOLVED.value, TicketStatus.CLOSED.value}


def _get(db: Session, ticket_id) -> Ticket:
    ticket = db.get(Ticket, ticket_id)
    if ticket is None:
        raise AppError("Ticket not found", 404, "not_found")
    return ticket


def visible(db: Session, actor: User, ticket: Ticket) -> Ticket:
    customer = ticket.customer
    assert_customer_visible(actor, customer)
    if Role(actor.role) == Role.FIELD_TECHNICIAN:
        tech = technician_service.for_user(db, actor)
        if tech is None or ticket.assigned_technician_id != tech.id:
            raise AppError("Ticket not found", 404, "not_found")
    return ticket


def get_ticket(db: Session, actor: User, ticket_id) -> Ticket:
    return visible(db, actor, _get(db, ticket_id))


def _touch(db, ticket: Ticket, actor: User, from_status: str | None, to_status: str | None, note: str | None):
    db.add(
        TicketEvent(
            ticket_id=ticket.id,
            from_status=from_status,
            to_status=to_status,
            note=note,
            actor_id=actor.id,
        )
    )


def create_ticket(db: Session, actor: User, data) -> Ticket:
    from app.services.customer_service import get_customer

    if Role(actor.role) not in {
        Role.CUSTOMER,
        Role.SUPPORT_AGENT,
        Role.OPERATIONS_MANAGER,
        Role.SUPER_ADMIN,
    }:
        raise AppError("You cannot open a ticket", 403, "forbidden")
    if is_customer(actor):
        customer = require_linked_customer(db, actor)
        if data.customer_id and data.customer_id != customer.id:
            raise AppError("Customer not found", 404, "not_found")
    else:
        if data.customer_id is None:
            raise AppError("customer_id is required", 422, "invalid_ticket")
        customer = get_customer(db, actor, data.customer_id)
    priority = (data.priority or Priority.MEDIUM).value
    policy = sla_service.resolve_policy(db, data.ticket_type.value, priority, customer.customer_type)
    started = utcnow()
    ticket = Ticket(
        code=next_code(db, "ticket", "TKT"),
        customer_id=customer.id,
        ticket_type=data.ticket_type.value,
        subject=data.subject.strip(),
        description=data.description.strip(),
        status=TicketStatus.OPEN.value,
        priority=priority,
        sla_policy_id=policy.id,
        sla_started_at=started,
        sla_deadline=sla_service.deadline_for(policy, started),
        created_by=actor.id,
    )
    db.add(ticket)
    db.flush()
    _touch(db, ticket, actor, None, TicketStatus.OPEN.value, "opened")
    log_action(
        db,
        actor_id=actor.id,
        action="ticket.created",
        entity="ticket",
        entity_id=ticket.id,
        new={"code": ticket.code, "ticket_type": ticket.ticket_type, "priority": ticket.priority, "sla_deadline": ticket.sla_deadline.isoformat()},
    )
    return ticket


def assign(db: Session, actor: User, ticket_id, agent_id, technician_id, background_tasks=None) -> Ticket:
    ticket = get_ticket(db, actor, ticket_id)
    if ticket.status in TERMINAL:
        raise AppError("A closed ticket cannot be assigned", 409, "invalid_transition")
    previous_status = ticket.status
    if agent_id is not None:
        agent = db.get(User, agent_id)
        if agent is None or agent.deleted_at is not None or not agent.is_active:
            raise AppError("Agent not found", 404, "not_found")
        if Role(agent.role) not in {Role.SUPPORT_AGENT, Role.OPERATIONS_MANAGER, Role.SUPER_ADMIN}:
            raise AppError("That user is not a support agent", 409, "invalid_assignee")
        ticket.assigned_agent_id = agent.id
        notify(db, agent.id, NotificationEvent.TICKET_ASSIGNED, f"Ticket {ticket.code} assigned", ticket.subject, {"ticket_id": str(ticket.id)})
    if technician_id is not None:
        _assign_technician(db, ticket, technician_id)
    if ticket.status == TicketStatus.OPEN.value and (ticket.assigned_agent_id or ticket.assigned_technician_id):
        assert_transition(TICKET_TRANSITIONS, ticket.status, TicketStatus.ASSIGNED, "ticket")
        ticket.status = TicketStatus.ASSIGNED.value
    _touch(db, ticket, actor, previous_status, ticket.status, "assigned")
    log_action(
        db,
        actor_id=actor.id,
        action="ticket.assigned",
        entity="ticket",
        entity_id=ticket.id,
        new={"agent_id": str(ticket.assigned_agent_id) if ticket.assigned_agent_id else None, "technician_id": str(ticket.assigned_technician_id) if ticket.assigned_technician_id else None},
    )
    spawn(background_tasks)
    return ticket


def _assign_technician(db: Session, ticket: Ticket, technician_id) -> None:
    tech = technician_service.get_technician(db, technician_id)
    if tech.availability in {Availability.OFF_DUTY.value, Availability.LEAVE.value}:
        raise AppError("This technician is not available", 409, "technician_unavailable")
    skills = {row.skill for row in tech.skills}
    if not skill_covers(ticket.ticket_type, skills):
        raise AppError("This technician does not have a skill that covers the ticket", 409, "skill_mismatch")
    service_cities = [
        address.city.strip().lower()
        for address in db.scalars(select(CustomerAddress).where(CustomerAddress.customer_id == ticket.customer_id, CustomerAddress.address_type == "service")).all()
    ]
    if service_cities and tech.service_city.strip().lower() not in service_cities:
        raise AppError("Technician service area does not cover the customer city", 409, "outside_service_area")
    ticket.assigned_technician_id = tech.id
    tech.availability = Availability.ON_JOB.value
    notify(
        db,
        tech.user_id,
        NotificationEvent.TICKET_ASSIGNED,
        f"Job {ticket.code} assigned",
        ticket.subject,
        {"ticket_id": str(ticket.id)},
    )


def _move(db, actor, ticket: Ticket, new_status: TicketStatus, note: str | None) -> Ticket:
    sla_service.flag_if_late(db, ticket)
    previous = ticket.status
    assert_transition(TICKET_TRANSITIONS, previous, new_status, "ticket")
    ticket.status = new_status.value
    if new_status == TicketStatus.RESOLVED:
        ticket.resolved_at = utcnow()
        ticket.resolution_notes = note
        if ticket.sla_deadline and ticket.resolved_at > ticket.sla_deadline:
            ticket.sla_breached = True
            ticket.escalation_status = "breached"
    if new_status == TicketStatus.CLOSED:
        ticket.closed_at = utcnow()
    _touch(db, ticket, actor, previous, ticket.status, note)
    log_action(
        db,
        actor_id=actor.id,
        action="ticket.updated",
        entity="ticket",
        entity_id=ticket.id,
        previous={"status": previous},
        new={"status": ticket.status, "note": note},
    )
    if ticket.assigned_technician_id and new_status in {TicketStatus.RESOLVED, TicketStatus.CLOSED}:
        technician_service.refresh_availability(db, ticket.assigned_technician_id)
    return ticket


def start(db, actor, ticket_id) -> Ticket:
    return _move(db, actor, get_ticket(db, actor, ticket_id), TicketStatus.IN_PROGRESS, "started")


def wait_for_customer(db, actor, ticket_id, note: str | None) -> Ticket:
    return _move(db, actor, get_ticket(db, actor, ticket_id), TicketStatus.WAITING_FOR_CUSTOMER, note)


def resume(db, actor, ticket_id) -> Ticket:
    return _move(db, actor, get_ticket(db, actor, ticket_id), TicketStatus.IN_PROGRESS, "resumed")


def resolve(db, actor, ticket_id, resolution_notes: str) -> Ticket:
    if len(resolution_notes.strip()) < 3:
        raise AppError("Resolution notes are required", 422, "resolution_required")
    return _move(db, actor, get_ticket(db, actor, ticket_id), TicketStatus.RESOLVED, resolution_notes.strip())


def close(db, actor, ticket_id) -> Ticket:
    ticket = get_ticket(db, actor, ticket_id)
    if is_customer(actor) and ticket.customer.user_id != actor.id:
        raise AppError("Ticket not found", 404, "not_found")
    return _move(db, actor, ticket, TicketStatus.CLOSED, "closed")


def escalate(db, actor, ticket_id, note: str | None, agent_id=None) -> Ticket:
    ticket = get_ticket(db, actor, ticket_id)
    if ticket.status in TERMINAL:
        raise AppError("A resolved ticket cannot be escalated", 409, "invalid_transition")
    ticket.escalation_level += 1
    ticket.escalation_status = "escalated"
    ticket.priority = bump_priority(ticket.priority)
    if agent_id:
        assign(db, actor, ticket.id, agent_id, None)
    _touch(db, ticket, actor, ticket.status, ticket.status, note or "escalated")
    log_action(
        db,
        actor_id=actor.id,
        action="ticket.escalated",
        entity="ticket",
        entity_id=ticket.id,
        new={"escalation_level": ticket.escalation_level, "priority": ticket.priority},
    )
    return ticket


def add_comment(db, actor, ticket_id, body: str, is_internal: bool) -> TicketComment:
    ticket = get_ticket(db, actor, ticket_id)
    if is_customer(actor) and is_internal:
        raise AppError("Customers cannot add internal notes", 403, "forbidden")
    if ticket.status == TicketStatus.CLOSED.value:
        raise AppError("A closed ticket cannot be commented on", 409, "invalid_transition")
    comment = TicketComment(ticket_id=ticket.id, author_id=actor.id, body=body.strip(), is_internal=is_internal)
    db.add(comment)
    db.flush()
    log_action(
        db,
        actor_id=actor.id,
        action="ticket.comment_added",
        entity="ticket",
        entity_id=ticket.id,
        new={"is_internal": is_internal},
    )
    return comment


def comments(db, actor, ticket_id):
    ticket = get_ticket(db, actor, ticket_id)
    stmt = select(TicketComment).where(TicketComment.ticket_id == ticket.id)
    if is_customer(actor):
        stmt = stmt.where(TicketComment.is_internal.is_(False))
    return list(db.scalars(stmt.order_by(TicketComment.created_at)).all())


def events(db, actor, ticket_id):
    ticket = get_ticket(db, actor, ticket_id)
    return list(db.scalars(select(TicketEvent).where(TicketEvent.ticket_id == ticket.id).order_by(TicketEvent.created_at)).all())


def list_tickets(db, actor, params, *, status, priority, ticket_type, customer_id):
    stmt = select(Ticket)
    if is_customer(actor):
        own = require_linked_customer(db, actor)
        stmt = stmt.where(Ticket.customer_id == own.id)
    elif Role(actor.role) == Role.FIELD_TECHNICIAN:
        tech = technician_service.for_user(db, actor)
        if tech is None:
            return [], 0
        stmt = stmt.where(Ticket.assigned_technician_id == tech.id)
    elif customer_id:
        stmt = stmt.where(Ticket.customer_id == customer_id)
    if status:
        stmt = stmt.where(Ticket.status == status)
    if priority:
        stmt = stmt.where(Ticket.priority == priority)
    if ticket_type:
        stmt = stmt.where(Ticket.ticket_type == ticket_type)
    if params.q:
        like = f"%{params.q.strip()}%"
        stmt = stmt.where(or_(Ticket.subject.ilike(like), Ticket.code.ilike(like), Ticket.description.ilike(like)))
    stmt = apply_sort(
        stmt,
        params.sort_by,
        params.sort_dir,
        {"created_at": Ticket.created_at, "sla_deadline": Ticket.sla_deadline, "priority": Ticket.priority, "code": Ticket.code},
    )
    return paginate(db, stmt, params.page, params.page_size)
