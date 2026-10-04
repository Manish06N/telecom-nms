import uuid

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.api.deps import PageParams, as_page, require
from app.db.session import get_db
from app.domain.enums import Availability, Permission, Priority, ServiceRequestType, Skill, TicketStatus, TicketType
from app.models.operations import Technician
from app.schemas.contracts import (
    AssignBody,
    AvailabilityUpdate,
    CommentCreate,
    CommentRead,
    NoteBody,
    Page,
    ResolveBody,
    ServiceRequestCreate,
    ServiceRequestEventRead,
    ServiceRequestRead,
    SkillUpdate,
    SlaPolicyCreate,
    SlaPolicyRead,
    SlaWatch,
    TechnicianCreate,
    TechnicianRead,
    TicketCreate,
    TicketEventRead,
    TicketRead,
    WorkloadRead,
)
from app.services import service_request_service, sla_service, technician_service, ticket_service

technicians = APIRouter(prefix="/technicians", tags=["Technicians"])
tickets = APIRouter(prefix="/tickets", tags=["Tickets"])
sla = APIRouter(prefix="/sla", tags=["SLA"])
requests = APIRouter(prefix="/service-requests", tags=["Service requests"])


def present_technician(tech: Technician) -> dict:
    return {
        "id": tech.id,
        "employee_code": tech.employee_code,
        "full_name": tech.user.full_name,
        "email": tech.user.email,
        "availability": tech.availability,
        "service_city": tech.service_city,
        "latitude": tech.latitude,
        "longitude": tech.longitude,
        "skills": [row.skill for row in tech.skills],
    }


@technicians.post("", response_model=TechnicianRead, status_code=201)
def register(body: TechnicianCreate, user=Depends(require(Permission.TECHNICIAN_WRITE)), db: Session = Depends(get_db)):
    return present_technician(technician_service.register(db, user, body))


@technicians.get("", response_model=Page[TechnicianRead])
def list_technicians(
    params: PageParams = Depends(),
    availability: Availability | None = None,
    service_city: str | None = None,
    skill: Skill | None = None,
    user=Depends(require(Permission.TECHNICIAN_READ)),
    db: Session = Depends(get_db),
):
    rows, total = technician_service.list_technicians(
        db,
        params,
        availability=availability.value if availability else None,
        service_city=service_city,
        skill=skill.value if skill else None,
    )
    return as_page([present_technician(row) for row in rows], total, params)


@technicians.get("/workload", response_model=list[WorkloadRead])
def board(user=Depends(require(Permission.TECHNICIAN_READ)), db: Session = Depends(get_db)):
    return technician_service.workload_board(db)


@technicians.put("/{technician_id}/skills", response_model=TechnicianRead)
def skills(technician_id: uuid.UUID, body: SkillUpdate, user=Depends(require(Permission.TECHNICIAN_WRITE)), db: Session = Depends(get_db)):
    return present_technician(technician_service.set_skills(db, user, technician_id, body.skills))


@technicians.post("/{technician_id}/availability", response_model=TechnicianRead)
def availability(
    technician_id: uuid.UUID,
    body: AvailabilityUpdate,
    user=Depends(require(Permission.TECHNICIAN_WRITE)),
    db: Session = Depends(get_db),
):
    tech = technician_service.set_availability(db, user, technician_id, body.availability, body.latitude, body.longitude)
    return present_technician(tech)


@technicians.get("/{technician_id}/workload", response_model=WorkloadRead)
def workload(technician_id: uuid.UUID, user=Depends(require(Permission.TECHNICIAN_READ)), db: Session = Depends(get_db)):
    return technician_service.workload(db, technician_id)


@technicians.get("/{technician_id}/jobs", response_model=list[TicketRead])
def jobs(
    technician_id: uuid.UUID,
    which: str = "pending",
    user=Depends(require(Permission.TECHNICIAN_READ)),
    db: Session = Depends(get_db),
):
    if which not in {"pending", "completed"}:
        which = "pending"
    return technician_service.jobs(db, technician_id, which)


@tickets.post("", response_model=TicketRead, status_code=201)
def create_ticket(body: TicketCreate, user=Depends(require(Permission.TICKET_WRITE)), db: Session = Depends(get_db)):
    return ticket_service.create_ticket(db, user, body)


@tickets.get("", response_model=Page[TicketRead])
def list_tickets(
    params: PageParams = Depends(),
    status: TicketStatus | None = None,
    priority: Priority | None = None,
    ticket_type: TicketType | None = None,
    customer_id: uuid.UUID | None = None,
    user=Depends(require(Permission.TICKET_READ)),
    db: Session = Depends(get_db),
):
    rows, total = ticket_service.list_tickets(
        db,
        user,
        params,
        status=status.value if status else None,
        priority=priority.value if priority else None,
        ticket_type=ticket_type.value if ticket_type else None,
        customer_id=customer_id,
    )
    return as_page(rows, total, params)


@tickets.get("/{ticket_id}", response_model=TicketRead)
def get_ticket(ticket_id: uuid.UUID, user=Depends(require(Permission.TICKET_READ)), db: Session = Depends(get_db)):
    return ticket_service.get_ticket(db, user, ticket_id)


@tickets.post("/{ticket_id}/assign", response_model=TicketRead)
def assign(
    ticket_id: uuid.UUID,
    body: AssignBody,
    background: BackgroundTasks,
    user=Depends(require(Permission.TICKET_ASSIGN)),
    db: Session = Depends(get_db),
):
    return ticket_service.assign(db, user, ticket_id, body.agent_id, body.technician_id, background)


@tickets.post("/{ticket_id}/start", response_model=TicketRead)
def start(ticket_id: uuid.UUID, user=Depends(require(Permission.TICKET_WRITE)), db: Session = Depends(get_db)):
    return ticket_service.start(db, user, ticket_id)


@tickets.post("/{ticket_id}/wait", response_model=TicketRead)
def wait(ticket_id: uuid.UUID, body: NoteBody, user=Depends(require(Permission.TICKET_WRITE)), db: Session = Depends(get_db)):
    return ticket_service.wait_for_customer(db, user, ticket_id, body.note)


@tickets.post("/{ticket_id}/resume", response_model=TicketRead)
def resume(ticket_id: uuid.UUID, user=Depends(require(Permission.TICKET_WRITE)), db: Session = Depends(get_db)):
    return ticket_service.resume(db, user, ticket_id)


@tickets.post("/{ticket_id}/resolve", response_model=TicketRead)
def resolve(ticket_id: uuid.UUID, body: ResolveBody, user=Depends(require(Permission.TICKET_WRITE)), db: Session = Depends(get_db)):
    return ticket_service.resolve(db, user, ticket_id, body.resolution_notes)


@tickets.post("/{ticket_id}/close", response_model=TicketRead)
def close(ticket_id: uuid.UUID, user=Depends(require(Permission.TICKET_WRITE)), db: Session = Depends(get_db)):
    return ticket_service.close(db, user, ticket_id)


@tickets.post("/{ticket_id}/escalate", response_model=TicketRead)
def escalate(
    ticket_id: uuid.UUID,
    body: NoteBody,
    agent_id: uuid.UUID | None = None,
    user=Depends(require(Permission.TICKET_ASSIGN)),
    db: Session = Depends(get_db),
):
    return ticket_service.escalate(db, user, ticket_id, body.note, agent_id)


@tickets.post("/{ticket_id}/comments", response_model=CommentRead, status_code=201)
def comment(ticket_id: uuid.UUID, body: CommentCreate, user=Depends(require(Permission.TICKET_WRITE)), db: Session = Depends(get_db)):
    return ticket_service.add_comment(db, user, ticket_id, body.body, body.is_internal)


@tickets.get("/{ticket_id}/comments", response_model=list[CommentRead])
def list_comments(ticket_id: uuid.UUID, user=Depends(require(Permission.TICKET_READ)), db: Session = Depends(get_db)):
    return ticket_service.comments(db, user, ticket_id)


@tickets.get("/{ticket_id}/history", response_model=list[TicketEventRead])
def history(ticket_id: uuid.UUID, user=Depends(require(Permission.TICKET_READ)), db: Session = Depends(get_db)):
    return ticket_service.events(db, user, ticket_id)


@sla.get("/policies", response_model=list[SlaPolicyRead])
def list_policies(user=Depends(require(Permission.SLA_READ)), db: Session = Depends(get_db)):
    return sla_service.policies(db)


@sla.post("/policies", response_model=SlaPolicyRead, status_code=201)
def create_policy(body: SlaPolicyCreate, user=Depends(require(Permission.SLA_WRITE)), db: Session = Depends(get_db)):
    return sla_service.create_policy(db, user, body)


@sla.get("/watch", response_model=SlaWatch)
def watch(
    background: BackgroundTasks,
    within_minutes: int = 60,
    user=Depends(require(Permission.SLA_READ)),
    db: Session = Depends(get_db),
):
    return sla_service.watch(db, within_minutes, background)


@requests.post("", response_model=ServiceRequestRead, status_code=201)
def create_request(body: ServiceRequestCreate, user=Depends(require(Permission.SERVICE_REQUEST_WRITE)), db: Session = Depends(get_db)):
    return service_request_service.create_request(db, user, body)


@requests.get("", response_model=Page[ServiceRequestRead])
def list_requests(
    params: PageParams = Depends(),
    status: str | None = None,
    request_type: ServiceRequestType | None = None,
    customer_id: uuid.UUID | None = None,
    user=Depends(require(Permission.SERVICE_REQUEST_WRITE)),
    db: Session = Depends(get_db),
):
    rows, total = service_request_service.list_requests(
        db, user, params, status=status, request_type=request_type.value if request_type else None, customer_id=customer_id
    )
    return as_page(rows, total, params)


@requests.get("/{request_id}", response_model=ServiceRequestRead)
def get_request(request_id: uuid.UUID, user=Depends(require(Permission.SERVICE_REQUEST_WRITE)), db: Session = Depends(get_db)):
    return service_request_service.get_request(db, user, request_id)


@requests.get("/{request_id}/history", response_model=list[ServiceRequestEventRead])
def request_history(request_id: uuid.UUID, user=Depends(require(Permission.SERVICE_REQUEST_WRITE)), db: Session = Depends(get_db)):
    return service_request_service.history(db, user, request_id)


@requests.post("/{request_id}/review", response_model=ServiceRequestRead)
def review(request_id: uuid.UUID, body: NoteBody, user=Depends(require(Permission.SERVICE_REQUEST_PROCESS)), db: Session = Depends(get_db)):
    return service_request_service.review(db, user, request_id, body.note)


@requests.post("/{request_id}/approve", response_model=ServiceRequestRead)
def approve(request_id: uuid.UUID, body: NoteBody, user=Depends(require(Permission.SERVICE_REQUEST_PROCESS)), db: Session = Depends(get_db)):
    return service_request_service.approve(db, user, request_id, body.note)


@requests.post("/{request_id}/start", response_model=ServiceRequestRead)
def start_request(request_id: uuid.UUID, user=Depends(require(Permission.SERVICE_REQUEST_PROCESS)), db: Session = Depends(get_db)):
    return service_request_service.start(db, user, request_id)


@requests.post("/{request_id}/complete", response_model=ServiceRequestRead)
def complete(request_id: uuid.UUID, body: NoteBody, user=Depends(require(Permission.SERVICE_REQUEST_PROCESS)), db: Session = Depends(get_db)):
    return service_request_service.complete(db, user, request_id, body.note)


@requests.post("/{request_id}/reject", response_model=ServiceRequestRead)
def reject(request_id: uuid.UUID, body: NoteBody, user=Depends(require(Permission.SERVICE_REQUEST_PROCESS)), db: Session = Depends(get_db)):
    if not body.note:
        from app.domain.errors import AppError

        raise AppError("A rejection needs a note", 422, "note_required")
    return service_request_service.reject(db, user, request_id, body.note)


@requests.post("/{request_id}/cancel", response_model=ServiceRequestRead)
def cancel(request_id: uuid.UUID, body: NoteBody, user=Depends(require(Permission.SERVICE_REQUEST_WRITE)), db: Session = Depends(get_db)):
    return service_request_service.cancel(db, user, request_id, body.note)
