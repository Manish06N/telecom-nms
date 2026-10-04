import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin
from app.utils.time import utcnow


class Technician(IdMixin, TimestampMixin, Base):
    __tablename__ = "technicians"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), unique=True)
    employee_code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    availability: Mapped[str] = mapped_column(String(20), default="available", index=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    service_city: Mapped[str] = mapped_column(String(80), index=True)

    user: Mapped["User"] = relationship()
    skills: Mapped[list["TechnicianSkill"]] = relationship(back_populates="technician", cascade="all, delete-orphan")


class TechnicianSkill(Base):
    __tablename__ = "technician_skills"
    __table_args__ = (UniqueConstraint("technician_id", "skill"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    technician_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("technicians.id"), index=True)
    skill: Mapped[str] = mapped_column(String(40))

    technician: Mapped[Technician] = relationship(back_populates="skills")


class Ticket(IdMixin, TimestampMixin, Base):
    __tablename__ = "tickets"

    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("customers.id"), index=True)
    ticket_type: Mapped[str] = mapped_column(String(40), index=True)
    subject: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="open", index=True)
    priority: Mapped[str] = mapped_column(String(20), index=True)
    assigned_agent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True, index=True
    )
    assigned_technician_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("technicians.id"), nullable=True, index=True
    )
    escalation_level: Mapped[int] = mapped_column(Integer, default=0)
    escalation_status: Mapped[str] = mapped_column(String(20), default="none")
    resolution_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    sla_policy_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("sla_policies.id"), nullable=True
    )
    sla_started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    sla_deadline: Mapped[datetime | None] = mapped_column(DateTime, index=True, nullable=True)
    sla_breached: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True)

    customer: Mapped["Customer"] = relationship()
    comments: Mapped[list["TicketComment"]] = relationship(back_populates="ticket")
    events: Mapped[list["TicketEvent"]] = relationship(back_populates="ticket")


class TicketComment(IdMixin, Base):
    __tablename__ = "ticket_comments"

    ticket_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("tickets.id"), index=True)
    author_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    is_internal: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    ticket: Mapped[Ticket] = relationship(back_populates="comments")


class TicketEvent(IdMixin, Base):
    __tablename__ = "ticket_events"

    ticket_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("tickets.id"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    ticket: Mapped[Ticket] = relationship(back_populates="events")


class SlaPolicy(IdMixin, TimestampMixin, Base):
    __tablename__ = "sla_policies"

    name: Mapped[str] = mapped_column(String(120))
    ticket_type: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    priority: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    customer_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    resolution_minutes: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class ServiceRequest(IdMixin, TimestampMixin, Base):
    __tablename__ = "service_requests"

    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("customers.id"), index=True)
    request_type: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(32), default="submitted", index=True)
    sim_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("sims.id"), nullable=True)
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("subscriptions.id"), nullable=True
    )
    device_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("devices.id"), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True)

    customer: Mapped["Customer"] = relationship()
    events: Mapped[list["ServiceRequestEvent"]] = relationship(back_populates="request")


class ServiceRequestEvent(IdMixin, Base):
    __tablename__ = "service_request_events"

    request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("service_requests.id"), index=True
    )
    from_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_status: Mapped[str] = mapped_column(String(32))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    request: Mapped[ServiceRequest] = relationship(back_populates="events")


class Notification(IdMixin, Base):
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    title: Mapped[str] = mapped_column(String(160))
    message: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
