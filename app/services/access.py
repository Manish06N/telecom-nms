"""Who is asking, and which customer row they are allowed to touch."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import Role
from app.domain.errors import AppError
from app.models.customer import Customer
from app.models.identity import User


def is_customer(user: User) -> bool:
    return Role(user.role) == Role.CUSTOMER


def linked_customer(db: Session, user: User) -> Customer | None:
    return db.scalar(select(Customer).where(Customer.user_id == user.id, Customer.deleted_at.is_(None)))


def require_linked_customer(db: Session, user: User) -> Customer:
    row = linked_customer(db, user)
    if row is None:
        raise AppError("No customer profile is linked to this login", 403, "no_customer_profile")
    return row


def assert_customer_visible(actor: User, customer: Customer) -> None:
    if is_customer(actor) and customer.user_id != actor.id:
        raise AppError("Customer not found", 404, "not_found")
