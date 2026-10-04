import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, SoftDeleteMixin, TimestampMixin
from app.utils.time import utcnow


class Sim(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "sims"

    iccid: Mapped[str] = mapped_column(String(22), unique=True, index=True)
    msisdn: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    sim_type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="available", index=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("customers.id"), nullable=True, index=True
    )
    activation_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    customer: Mapped["Customer | None"] = relationship()


class SimReplacement(IdMixin, Base):
    __tablename__ = "sim_replacements"

    old_sim_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("sims.id"), index=True)
    new_sim_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("sims.id"), index=True)
    reason: Mapped[str] = mapped_column(Text)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True)
    replaced_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Device(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "devices"

    imei: Mapped[str] = mapped_column(String(15), unique=True, index=True)
    model: Mapped[str] = mapped_column(String(80))
    manufacturer: Mapped[str] = mapped_column(String(80))
    device_type: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(20), default="in_stock", index=True)
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("customers.id"), nullable=True, index=True
    )

    mappings: Mapped[list["DeviceSimMapping"]] = relationship(back_populates="device")


class DeviceSimMapping(IdMixin, Base):
    __tablename__ = "device_sim_mappings"

    device_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("devices.id"), index=True)
    sim_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("sims.id"), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    mapped_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    unmapped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    device: Mapped[Device] = relationship(back_populates="mappings")
    sim: Mapped[Sim] = relationship()
