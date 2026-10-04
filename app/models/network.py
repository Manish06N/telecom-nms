import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Table, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, SoftDeleteMixin, TimestampMixin
from app.utils.time import utcnow


class Tower(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "towers"

    tower_code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    tower_type: Mapped[str] = mapped_column(String(20))
    latitude: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    address: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(80), index=True)
    state: Mapped[str] = mapped_column(String(80))
    coverage_radius_km: Mapped[Decimal] = mapped_column(Numeric(6, 2))
    capacity: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)


class Equipment(IdMixin, TimestampMixin, Base):
    __tablename__ = "equipment"

    tower_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("towers.id"), index=True)
    equipment_type: Mapped[str] = mapped_column(String(32), index=True)
    serial_number: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    model: Mapped[str] = mapped_column(String(80))
    manufacturer: Mapped[str] = mapped_column(String(80))
    health: Mapped[str] = mapped_column(String(20), default="unknown")
    installation_date: Mapped[date] = mapped_column(Date)
    next_maintenance_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    cpu_usage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    memory_usage: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    network_status: Mapped[str] = mapped_column(String(20), default="up", index=True)
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    down_since: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    downtime_minutes: Mapped[int] = mapped_column(Integer, default=0)
    maintenance_notified: Mapped[bool] = mapped_column(Boolean, default=False)

    tower: Mapped[Tower] = relationship()


class Outage(IdMixin, TimestampMixin, Base):
    __tablename__ = "outages"

    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(160))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    outage_type: Mapped[str] = mapped_column(String(40), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    start_time: Mapped[datetime] = mapped_column(DateTime)
    expected_resolution: Mapped[datetime] = mapped_column(DateTime)
    actual_resolution: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True)

    towers: Mapped[list[Tower]] = relationship(secondary="outage_towers")
    affected: Mapped[list["OutageCustomer"]] = relationship(back_populates="outage")


outage_towers = Table(
    "outage_towers",
    Base.metadata,
    Column("outage_id", Uuid(as_uuid=True), ForeignKey("outages.id"), primary_key=True),
    Column("tower_id", Uuid(as_uuid=True), ForeignKey("towers.id"), primary_key=True),
)


class OutageCustomer(Base):
    """Snapshot taken when the outage is opened. Later tower edits do not rewrite history."""

    __tablename__ = "outage_customers"

    outage_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("outages.id"), primary_key=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("customers.id"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    outage: Mapped[Outage] = relationship(back_populates="affected")
    customer: Mapped["Customer"] = relationship()
