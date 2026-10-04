import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, IdMixin, TimestampMixin
from app.utils.time import utcnow


class Subscription(IdMixin, TimestampMixin, Base):
    __tablename__ = "subscriptions"

    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("customers.id"), index=True)
    sim_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("sims.id"), index=True)
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("service_plans.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), index=True)
    start_date: Mapped[datetime] = mapped_column(DateTime)
    end_date: Mapped[datetime] = mapped_column(DateTime, index=True)
    cycle_start: Mapped[datetime] = mapped_column(DateTime)
    cycle_end: Mapped[datetime] = mapped_column(DateTime)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expiry_notified: Mapped[bool] = mapped_column(Boolean, default=False)
    threshold_notified: Mapped[bool] = mapped_column(Boolean, default=False)

    customer: Mapped["Customer"] = relationship()
    sim: Mapped["Sim"] = relationship()
    plan: Mapped["ServicePlan"] = relationship()
    events: Mapped[list["SubscriptionEvent"]] = relationship(back_populates="subscription")


class SubscriptionEvent(IdMixin, Base):
    __tablename__ = "subscription_events"

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("subscriptions.id"), index=True
    )
    event_type: Mapped[str] = mapped_column(String(32))
    from_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("service_plans.id"), nullable=True
    )
    to_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("service_plans.id"), nullable=True
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    subscription: Mapped[Subscription] = relationship(back_populates="events")


class UsageDaily(IdMixin, Base):
    __tablename__ = "usage_daily"
    __table_args__ = (UniqueConstraint("sim_id", "usage_date"),)

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("subscriptions.id"), index=True
    )
    sim_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("sims.id"), index=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("customers.id"), index=True)
    usage_date: Mapped[date] = mapped_column(Date, index=True)
    data_mb: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=0)
    voice_minutes: Mapped[Decimal] = mapped_column(Numeric(12, 3), default=0)
    sms_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
