"""Field technicians. A job is a ticket assigned to them."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.security import hash_password
from app.domain.enums import Availability, Role, TicketStatus
from app.domain.errors import AppError
from app.models.identity import User
from app.models.operations import Technician, TechnicianSkill, Ticket
from app.repositories.common import next_code, paginate
from app.services.records import log_action

PENDING = {
    TicketStatus.ASSIGNED.value,
    TicketStatus.IN_PROGRESS.value,
    TicketStatus.WAITING_FOR_CUSTOMER.value,
}
DONE = {TicketStatus.RESOLVED.value, TicketStatus.CLOSED.value}


def _query():
    return select(Technician).options(selectinload(Technician.skills), selectinload(Technician.user))


def get_technician(db: Session, technician_id) -> Technician:
    row = db.scalar(_query().where(Technician.id == technician_id))
    if row is None:
        raise AppError("Technician not found", 404, "not_found")
    return row


def for_user(db: Session, user: User) -> Technician | None:
    return db.scalar(_query().where(Technician.user_id == user.id))


def register(db: Session, actor: User, data) -> Technician:
    email = data.email.lower()
    if db.scalar(select(User).where(User.email == email)):
        raise AppError("An account with this email already exists", 409, "email_taken")
    user = User(
        email=email,
        full_name=data.full_name.strip(),
        phone=data.phone,
        hashed_password=hash_password(data.password),
        role=Role.FIELD_TECHNICIAN.value,
        is_active=True,
        is_verified=True,
    )
    db.add(user)
    db.flush()
    tech = Technician(
        user_id=user.id,
        employee_code=next_code(db, "technician", "TECH"),
        availability=Availability.AVAILABLE.value,
        latitude=data.latitude,
        longitude=data.longitude,
        service_city=data.service_city.strip(),
    )
    db.add(tech)
    db.flush()
    _replace_skills(db, tech, data.skills)
    log_action(
        db,
        actor_id=actor.id,
        action="technician.registered",
        entity="technician",
        entity_id=tech.id,
        new={"employee_code": tech.employee_code, "service_city": tech.service_city, "skills": [s.value for s in data.skills]},
    )
    return get_technician(db, tech.id)


def set_skills(db: Session, actor: User, technician_id, skills) -> Technician:
    tech = get_technician(db, technician_id)
    _replace_skills(db, tech, skills)
    log_action(
        db,
        actor_id=actor.id,
        action="technician.skills_updated",
        entity="technician",
        entity_id=tech.id,
        new={"skills": [skill.value for skill in skills]},
    )
    return get_technician(db, tech.id)


def _replace_skills(db: Session, tech: Technician, skills) -> None:
    if not skills:
        raise AppError("A technician needs at least one skill", 422, "skills_required")
    db.query(TechnicianSkill).filter(TechnicianSkill.technician_id == tech.id).delete()
    for skill in skills:
        db.add(TechnicianSkill(technician_id=tech.id, skill=skill.value))
    db.flush()


def set_availability(db: Session, actor: User, technician_id, availability: Availability, latitude, longitude) -> Technician:
    tech = get_technician(db, technician_id)
    if availability == Availability.AVAILABLE and _pending_count(db, tech.id):
        raise AppError("This technician still has pending jobs", 409, "jobs_pending")
    tech.availability = availability.value
    if latitude is not None:
        tech.latitude = latitude
    if longitude is not None:
        tech.longitude = longitude
    log_action(
        db,
        actor_id=actor.id,
        action="technician.availability_changed",
        entity="technician",
        entity_id=tech.id,
        new={"availability": tech.availability},
    )
    return tech


def list_technicians(db: Session, params, *, availability, service_city, skill):
    stmt = _query()
    if availability:
        stmt = stmt.where(Technician.availability == availability)
    if service_city:
        stmt = stmt.where(Technician.service_city.ilike(service_city.strip()))
    if skill:
        stmt = stmt.where(Technician.id.in_(select(TechnicianSkill.technician_id).where(TechnicianSkill.skill == skill)))
    if params.q:
        like = f"%{params.q.strip()}%"
        stmt = stmt.join(User, User.id == Technician.user_id).where(
            (Technician.employee_code.ilike(like)) | (User.full_name.ilike(like))
        )
    stmt = stmt.order_by(Technician.created_at.desc())
    return paginate(db, stmt, params.page, params.page_size)


def jobs(db: Session, technician_id, which: str):
    get_technician(db, technician_id)
    statuses = PENDING if which == "pending" else DONE
    rows = db.scalars(
        select(Ticket).where(Ticket.assigned_technician_id == technician_id, Ticket.status.in_(statuses)).order_by(Ticket.created_at.desc())
    ).all()
    return list(rows)


def workload(db: Session, technician_id) -> dict:
    tech = get_technician(db, technician_id)
    pending = _pending_count(db, tech.id)
    completed = db.scalar(
        select(func.count()).select_from(Ticket).where(Ticket.assigned_technician_id == tech.id, Ticket.status.in_(DONE))
    ) or 0
    return {
        "technician_id": tech.id,
        "employee_code": tech.employee_code,
        "availability": tech.availability,
        "pending_jobs": pending,
        "completed_jobs": completed,
    }


def workload_board(db: Session) -> list[dict]:
    techs = db.scalars(select(Technician)).all()
    return [workload(db, tech.id) for tech in techs]


def _pending_count(db: Session, technician_id) -> int:
    return (
        db.scalar(
            select(func.count()).select_from(Ticket).where(
                Ticket.assigned_technician_id == technician_id,
                Ticket.status.in_(PENDING),
            )
        )
        or 0
    )


def refresh_availability(db: Session, technician_id) -> None:
    tech = db.get(Technician, technician_id)
    if tech is None:
        return
    if tech.availability == Availability.ON_JOB.value and _pending_count(db, technician_id) == 0:
        tech.availability = Availability.AVAILABLE.value
