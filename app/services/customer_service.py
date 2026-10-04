"""Customer profile rules: KYC, a reachable phone, and a service address before activation."""

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from app.core.security import hash_password
from app.domain.enums import AddressType, ContactType, CustomerStatus, CustomerType, KycStatus, Role
from app.domain.errors import AppError
from app.domain.transitions import CUSTOMER_STATUS_TRANSITIONS, KYC_TRANSITIONS, assert_transition
from app.domain.validators import assert_adult, normalize_msisdn
from app.models.customer import Customer, CustomerAddress, CustomerContact, CustomerEvent
from app.models.identity import User
from app.models.subscription import Subscription
from app.repositories.common import apply_sort, next_code, paginate
from app.services.access import assert_customer_visible, is_customer
from app.services.records import log_action
from app.utils.serialize import snapshot

PROFILE_FIELDS = (
    "first_name",
    "last_name",
    "company_name",
    "date_of_birth",
    "customer_type",
    "kyc_status",
    "status",
)


def _base_query():
    return select(Customer).where(Customer.deleted_at.is_(None)).options(
        selectinload(Customer.contacts),
        selectinload(Customer.addresses),
    )


def get_customer(db: Session, actor: User, customer_id) -> Customer:
    customer = db.scalar(_base_query().where(Customer.id == customer_id))
    if customer is None:
        raise AppError("Customer not found", 404, "not_found")
    assert_customer_visible(actor, customer)
    return customer


def _event(db: Session, customer: Customer, actor: User, action: str, note: str | None = None) -> None:
    db.add(CustomerEvent(customer_id=customer.id, action=action, note=note, actor_id=actor.id))


def _add_contact(db: Session, customer: Customer, data) -> CustomerContact:
    value = data.value.strip()
    if data.contact_type in {ContactType.MOBILE, ContactType.ALTERNATE_MOBILE}:
        value = normalize_msisdn(value)
    make_primary = data.is_primary or not any(
        existing.contact_type == data.contact_type.value and existing.is_primary for existing in customer.contacts
    )
    if make_primary:
        for existing in customer.contacts:
            if existing.contact_type == data.contact_type.value and existing.is_primary:
                existing.is_primary = False
    contact = CustomerContact(
        customer_id=customer.id,
        contact_type=data.contact_type.value,
        value=value,
        is_primary=make_primary,
    )
    db.add(contact)
    db.flush()
    return contact


def _add_address(db: Session, customer: Customer, data) -> CustomerAddress:
    make_primary = data.is_primary or not any(
        existing.address_type == data.address_type.value and existing.is_primary for existing in customer.addresses
    )
    if make_primary:
        for existing in customer.addresses:
            if existing.address_type == data.address_type.value and existing.is_primary:
                existing.is_primary = False
    address = CustomerAddress(
        customer_id=customer.id,
        address_type=data.address_type.value,
        line1=data.line1.strip(),
        line2=data.line2,
        city=data.city.strip(),
        state=data.state.strip(),
        postal_code=data.postal_code.strip(),
        country=data.country.strip(),
        is_primary=make_primary,
    )
    db.add(address)
    db.flush()
    return address


def create_customer(db: Session, actor: User, data) -> Customer:
    if is_customer(actor):
        raise AppError("Customers cannot register another customer record", 403, "forbidden")
    if data.customer_type == CustomerType.INDIVIDUAL and (not data.first_name or not data.last_name):
        raise AppError("Individual customers need a first and last name", 422, "invalid_customer")
    if data.customer_type == CustomerType.CORPORATE and not data.company_name:
        raise AppError("Corporate customers need a company name", 422, "invalid_customer")
    if data.date_of_birth and data.customer_type == CustomerType.INDIVIDUAL:
        assert_adult(data.date_of_birth)

    user_id = None
    if data.create_login:
        if not data.email or not data.password:
            raise AppError("Email and password are required to create a login", 422, "invalid_customer")
        full_name = data.company_name or f"{data.first_name} {data.last_name}".strip()
        email = data.email.lower()
        if db.scalar(select(User).where(User.email == email)):
            raise AppError("An account with this email already exists", 409, "email_taken")
        login = User(
            email=email,
            full_name=full_name,
            hashed_password=hash_password(data.password),
            role=Role.CUSTOMER.value,
            is_active=True,
            is_verified=True,
        )
        db.add(login)
        db.flush()
        user_id = login.id

    customer = Customer(
        customer_code=next_code(db, "customer", "CUS"),
        user_id=user_id,
        customer_type=data.customer_type.value,
        first_name=data.first_name,
        last_name=data.last_name,
        company_name=data.company_name,
        date_of_birth=data.date_of_birth,
        kyc_status=KycStatus.PENDING.value,
        status=CustomerStatus.PENDING.value,
        created_by=actor.id,
    )
    db.add(customer)
    db.flush()
    for contact in data.contacts:
        _add_contact(db, customer, contact)
    for address in data.addresses:
        _add_address(db, customer, address)
    _event(db, customer, actor, "customer.created")
    log_action(
        db,
        actor_id=actor.id,
        action="customer.created",
        entity="customer",
        entity_id=customer.id,
        new=snapshot(customer, PROFILE_FIELDS),
    )
    db.refresh(customer)
    return customer


def update_profile(db: Session, actor: User, customer_id, data) -> Customer:
    customer = get_customer(db, actor, customer_id)
    if is_customer(actor) and data.model_dump(exclude_unset=True).keys() & {"company_name"}:
        if customer.customer_type != CustomerType.CORPORATE.value:
            raise AppError("Only a corporate profile has a company name", 400, "invalid_customer")
    previous = snapshot(customer, PROFILE_FIELDS)
    for field in ("first_name", "last_name", "company_name", "date_of_birth"):
        value = getattr(data, field)
        if value is not None:
            setattr(customer, field, value)
    if customer.customer_type == CustomerType.INDIVIDUAL.value and customer.date_of_birth:
        assert_adult(customer.date_of_birth)
    _event(db, customer, actor, "customer.updated")
    log_action(
        db,
        actor_id=actor.id,
        action="customer.updated",
        entity="customer",
        entity_id=customer.id,
        previous=previous,
        new=snapshot(customer, PROFILE_FIELDS),
    )
    return customer


def add_contact(db: Session, actor: User, customer_id, data) -> CustomerContact:
    customer = get_customer(db, actor, customer_id)
    contact = _add_contact(db, customer, data)
    _event(db, customer, actor, "contact.added", contact.value)
    log_action(
        db,
        actor_id=actor.id,
        action="customer.contact_added",
        entity="customer",
        entity_id=customer.id,
        new={"contact_type": contact.contact_type, "value": contact.value, "is_primary": contact.is_primary},
    )
    return contact


def add_address(db: Session, actor: User, customer_id, data) -> CustomerAddress:
    customer = get_customer(db, actor, customer_id)
    address = _add_address(db, customer, data)
    _event(db, customer, actor, "address.added", address.city)
    log_action(
        db,
        actor_id=actor.id,
        action="customer.address_added",
        entity="customer",
        entity_id=customer.id,
        new={"address_type": address.address_type, "city": address.city, "line1": address.line1},
    )
    return address


def update_kyc(db: Session, actor: User, customer_id, new_status: KycStatus, note: str | None) -> Customer:
    customer = get_customer(db, actor, customer_id)
    assert_transition(KYC_TRANSITIONS, customer.kyc_status, new_status, "KYC")
    if is_customer(actor) and new_status != KycStatus.SUBMITTED:
        raise AppError("You can submit KYC, not verify it", 403, "forbidden")
    if new_status in {KycStatus.VERIFIED, KycStatus.REJECTED} and Role(actor.role) not in {
        Role.SUPER_ADMIN,
        Role.OPERATIONS_MANAGER,
    }:
        raise AppError("Only an operations manager can verify or reject KYC", 403, "forbidden")
    if new_status == KycStatus.REJECTED and _open_subscriptions(db, customer.id):
        raise AppError("Cancel active subscriptions before rejecting KYC", 409, "customer_has_subscriptions")
    previous = snapshot(customer, ("kyc_status",))
    customer.kyc_status = new_status.value
    _event(db, customer, actor, "kyc.updated", note or new_status.value)
    log_action(
        db,
        actor_id=actor.id,
        action="customer.kyc_updated",
        entity="customer",
        entity_id=customer.id,
        previous=previous,
        new=snapshot(customer, ("kyc_status",)),
    )
    return customer


def _open_subscriptions(db: Session, customer_id) -> int:
    from sqlalchemy import func

    return (
        db.scalar(
            select(func.count())
            .select_from(Subscription)
            .where(
                Subscription.customer_id == customer_id,
                Subscription.status.in_(["pending", "active", "suspended"]),
            )
        )
        or 0
    )


def _ready_for_activation(customer: Customer) -> None:
    if customer.kyc_status != KycStatus.VERIFIED.value:
        raise AppError("KYC must be verified before the customer can be activated", 400, "kyc_required")
    mobiles = [c for c in customer.contacts if c.contact_type == ContactType.MOBILE.value and c.is_primary]
    if not mobiles:
        raise AppError("A primary mobile number is required", 400, "contact_required")
    service = [a for a in customer.addresses if a.address_type == AddressType.SERVICE.value]
    if not service:
        raise AppError("A service address is required", 400, "address_required")
    if customer.customer_type == CustomerType.INDIVIDUAL.value:
        if customer.date_of_birth is None:
            raise AppError("Date of birth is required for an individual customer", 400, "dob_required")
        assert_adult(customer.date_of_birth)


def set_customer_status(db: Session, actor: User, customer_id, active: bool) -> Customer:
    if is_customer(actor):
        raise AppError("Customers cannot change account status", 403, "forbidden")
    customer = get_customer(db, actor, customer_id)
    target = CustomerStatus.ACTIVE if active else CustomerStatus.INACTIVE
    assert_transition(CUSTOMER_STATUS_TRANSITIONS, customer.status, target, "customer status")
    if active:
        _ready_for_activation(customer)
    elif _open_subscriptions(db, customer.id):
        raise AppError("Cancel active subscriptions before deactivating the customer", 409, "customer_has_subscriptions")
    previous = snapshot(customer, ("status",))
    customer.status = target.value
    _event(db, customer, actor, "customer.activated" if active else "customer.deactivated")
    log_action(
        db,
        actor_id=actor.id,
        action="customer.activated" if active else "customer.deactivated",
        entity="customer",
        entity_id=customer.id,
        previous=previous,
        new=snapshot(customer, ("status",)),
    )
    return customer


def list_customers(db: Session, actor: User, params, *, status, kyc_status, customer_type, city):
    stmt = _base_query()
    if is_customer(actor):
        stmt = stmt.where(Customer.user_id == actor.id)
    if status:
        stmt = stmt.where(Customer.status == status)
    if kyc_status:
        stmt = stmt.where(Customer.kyc_status == kyc_status)
    if customer_type:
        stmt = stmt.where(Customer.customer_type == customer_type)
    if city:
        stmt = stmt.where(
            Customer.id.in_(
                select(CustomerAddress.customer_id).where(CustomerAddress.city.ilike(city.strip()))
            )
        )
    if params.q:
        like = f"%{params.q.strip()}%"
        stmt = stmt.where(
            or_(
                Customer.customer_code.ilike(like),
                Customer.first_name.ilike(like),
                Customer.last_name.ilike(like),
                Customer.company_name.ilike(like),
                Customer.id.in_(select(CustomerContact.customer_id).where(CustomerContact.value.ilike(like))),
            )
        )
    stmt = apply_sort(
        stmt,
        params.sort_by,
        params.sort_dir,
        {
            "created_at": Customer.created_at,
            "customer_code": Customer.customer_code,
            "first_name": Customer.first_name,
            "status": Customer.status,
        },
    )
    return paginate(db, stmt, params.page, params.page_size)


def history(db: Session, actor: User, customer_id):
    customer = get_customer(db, actor, customer_id)
    rows = db.scalars(
        select(CustomerEvent).where(CustomerEvent.customer_id == customer.id).order_by(CustomerEvent.created_at.desc())
    ).all()
    return list(rows)


def soft_delete(db: Session, actor: User, customer_id) -> None:
    customer = get_customer(db, actor, customer_id)
    if customer.status == CustomerStatus.ACTIVE.value:
        raise AppError("Deactivate the customer before archiving", 409, "customer_active")
    if _open_subscriptions(db, customer.id):
        raise AppError("Cancel subscriptions before archiving the customer", 409, "customer_has_subscriptions")
    previous = snapshot(customer, ("status",))
    customer.soft_delete()
    log_action(
        db,
        actor_id=actor.id,
        action="customer.archived",
        entity="customer",
        entity_id=customer.id,
        previous=previous,
        new={"deleted_at": customer.deleted_at.isoformat()},
    )
