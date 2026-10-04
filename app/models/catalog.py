from decimal import Decimal

from sqlalchemy import Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, IdMixin, SoftDeleteMixin, TimestampMixin


class ServicePlan(IdMixin, TimestampMixin, SoftDeleteMixin, Base):
    __tablename__ = "service_plans"

    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    billing_type: Mapped[str] = mapped_column(String(20), index=True)
    category: Mapped[str] = mapped_column(String(20), index=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    validity_days: Mapped[int] = mapped_column(Integer)
    # -1 unlimited, 0 not included, otherwise the cap for one billing cycle.
    data_limit_mb: Mapped[int] = mapped_column(Integer, default=0)
    voice_limit_minutes: Mapped[int] = mapped_column(Integer, default=0)
    sms_limit: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
