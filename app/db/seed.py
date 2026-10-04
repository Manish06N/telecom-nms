"""Reference data created once: an administrator and the default SLA rules."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_password
from app.domain.enums import Role
from app.models.identity import User
from app.models.operations import SlaPolicy


DEFAULT_POLICIES = [
    ("Critical tickets", None, "critical", None, 60),
    ("High tickets", None, "high", None, 240),
    ("Medium tickets", None, "medium", None, 1440),
    ("Low tickets", None, "low", None, 4320),
    ("Critical network", "network_issue", "critical", None, 45),
    ("Critical corporate", None, "critical", "corporate", 30),
]


def seed_sla_policies(db: Session) -> None:
    existing = db.scalar(select(func.count()).select_from(SlaPolicy)) or 0
    if existing:
        return
    for name, ticket_type, priority, customer_type, minutes in DEFAULT_POLICIES:
        db.add(
            SlaPolicy(
                name=name,
                ticket_type=ticket_type,
                priority=priority,
                customer_type=customer_type,
                resolution_minutes=minutes,
                is_active=True,
            )
        )
    db.flush()


def seed_admin(db: Session) -> None:
    email = settings.admin_email.lower()
    if db.scalar(select(User).where(User.email == email)):
        return
    db.add(
        User(
            email=email,
            full_name=settings.admin_name,
            hashed_password=hash_password(settings.admin_password),
            role=Role.SUPER_ADMIN.value,
            is_active=True,
            is_verified=True,
        )
    )
    db.flush()


def seed(db: Session) -> None:
    seed_admin(db)
    seed_sla_policies(db)
