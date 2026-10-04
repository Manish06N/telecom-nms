"""SIM lifecycle. A SIM's commercial plan is the subscription, not a column copied onto the card."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import CustomerStatus, NotificationEvent, SimStatus
from app.domain.errors import AppError
from app.domain.transitions import SIM_TRANSITIONS, assert_transition
from app.domain.validators import normalize_msisdn, validate_iccid
from app.models.customer import Customer
from app.models.identity import User
from app.models.inventory import DeviceSimMapping, Sim, SimReplacement
from app.models.subscription import Subscription
from app.repositories.common import apply_sort, paginate
from app.services.access import assert_customer_visible, is_customer, linked_customer
from app.services.records import log_action, notify
from app.utils.serialize import snapshot
from app.utils.time import utcnow

SIM_FIELDS = ("iccid", "msisdn", "sim_type", "status", "customer_id")


def _get(db: Session, sim_id) -> Sim:
    sim = db.get(Sim, sim_id)
    if sim is None or sim.deleted_at is not None:
        raise AppError("SIM not found", 404, "not_found")
    return sim


def get_sim(db: Session, actor: User, sim_id) -> Sim:
    sim = _get(db, sim_id)
    if is_customer(actor):
        own = linked_customer(db, actor)
        if own is None or sim.customer_id != own.id:
            raise AppError("SIM not found", 404, "not_found")
    return sim


def register_sim(db: Session, actor: User, data) -> Sim:
    iccid = validate_iccid(data.iccid)
    msisdn = normalize_msisdn(data.msisdn)
    if db.scalar(select(Sim).where(Sim.iccid == iccid, Sim.deleted_at.is_(None))):
        raise AppError("This ICCID is already registered", 409, "duplicate_iccid")
    if db.scalar(select(Sim).where(Sim.msisdn == msisdn, Sim.deleted_at.is_(None))):
        raise AppError("This mobile number is already registered", 409, "duplicate_msisdn")
    sim = Sim(iccid=iccid, msisdn=msisdn, sim_type=data.sim_type.value, status=SimStatus.AVAILABLE.value)
    db.add(sim)
    db.flush()
    log_action(db, actor_id=actor.id, action="sim.registered", entity="sim", entity_id=sim.id, new=snapshot(sim, SIM_FIELDS))
    return sim


def _require_active_customer(db: Session, customer_id) -> Customer:
    customer = db.get(Customer, customer_id)
    if customer is None or customer.deleted_at is not None:
        raise AppError("Customer not found", 404, "not_found")
    if customer.status != CustomerStatus.ACTIVE.value:
        raise AppError("The customer must be active before a SIM can be assigned", 409, "customer_inactive")
    return customer


def activate_sim(db: Session, actor: User, sim_id, customer_id) -> Sim:
    sim = _get(db, sim_id)
    customer = _require_active_customer(db, customer_id)
    assert_customer_visible(actor, customer)
    assert_transition(SIM_TRANSITIONS, sim.status, SimStatus.ACTIVE, "SIM")
    previous = snapshot(sim, SIM_FIELDS)
    sim.customer_id = customer.id
    sim.status = SimStatus.ACTIVE.value
    sim.activation_date = utcnow()
    log_action(
        db,
        actor_id=actor.id,
        action="sim.activated",
        entity="sim",
        entity_id=sim.id,
        previous=previous,
        new=snapshot(sim, SIM_FIELDS),
    )
    return sim


def change_status(db: Session, actor: User, sim_id, new_status: SimStatus, reason: str | None, background_tasks=None) -> Sim:
    sim = get_sim(db, actor, sim_id)
    if new_status == SimStatus.ACTIVE and sim.status == SimStatus.SUSPENDED.value:
        if sim.customer_id is None:
            raise AppError("Suspended SIM has no customer", 409, "sim_unassigned")
        _require_active_customer(db, sim.customer_id)
    assert_transition(SIM_TRANSITIONS, sim.status, new_status, "SIM")
    if new_status == SimStatus.ACTIVE and sim.status == SimStatus.AVAILABLE.value:
        raise AppError("Use the activate endpoint to assign an available SIM to a customer", 409, "use_activate")
    previous = snapshot(sim, ("status",))
    sim.status = new_status.value
    log_action(
        db,
        actor_id=actor.id,
        action="sim.status_changed",
        entity="sim",
        entity_id=sim.id,
        previous=previous,
        new={"status": sim.status, "reason": reason},
    )
    if new_status == SimStatus.SUSPENDED and sim.customer_id is not None:
        customer = db.get(Customer, sim.customer_id)
        if customer and customer.user_id:
            notify(
                db,
                customer.user_id,
                NotificationEvent.SIM_SUSPENDED,
                "SIM suspended",
                f"Mobile number {sim.msisdn} has been suspended.",
                {"sim_id": str(sim.id), "reason": reason},
            )
            from app.services.records import spawn

            spawn(background_tasks)
    return sim


def change_msisdn(db: Session, actor: User, sim_id, new_msisdn: str) -> Sim:
    sim = _get(db, sim_id)
    if sim.status in {SimStatus.DEACTIVATED.value, SimStatus.BLOCKED.value}:
        raise AppError("This SIM cannot change number", 409, "invalid_transition")
    number = normalize_msisdn(new_msisdn)
    taken = db.scalar(select(Sim).where(Sim.msisdn == number, Sim.id != sim.id, Sim.deleted_at.is_(None)))
    if taken is not None:
        raise AppError("That mobile number is already in use", 409, "duplicate_msisdn")
    previous = snapshot(sim, ("msisdn",))
    sim.msisdn = number
    log_action(
        db,
        actor_id=actor.id,
        action="sim.number_changed",
        entity="sim",
        entity_id=sim.id,
        previous=previous,
        new=snapshot(sim, ("msisdn",)),
    )
    return sim


def replace_sim(db: Session, actor: User, old_sim_id, new_sim_id, reason: str) -> Sim:
    old = _get(db, old_sim_id)
    new = _get(db, new_sim_id)
    if old.customer_id is None:
        raise AppError("The old SIM is not assigned to a customer", 409, "sim_unassigned")
    if new.status != SimStatus.AVAILABLE.value:
        raise AppError("The replacement SIM must be available", 409, "sim_not_available")
    if old.status == SimStatus.DEACTIVATED.value:
        raise AppError("A deactivated SIM was already replaced", 409, "invalid_transition")
    previous = snapshot(old, SIM_FIELDS)
    new.customer_id = old.customer_id
    new.status = SimStatus.ACTIVE.value
    new.activation_date = utcnow()
    old.status = SimStatus.DEACTIVATED.value

    open_sub = db.scalar(
        select(Subscription).where(
            Subscription.sim_id == old.id,
            Subscription.status.in_(["pending", "active", "suspended"]),
        )
    )
    if open_sub is not None:
        open_sub.sim_id = new.id
        from app.models.subscription import SubscriptionEvent
        from app.domain.enums import SubscriptionEventType

        db.add(
            SubscriptionEvent(
                subscription_id=open_sub.id,
                event_type=SubscriptionEventType.SIM_CHANGED.value,
                note=reason,
                actor_id=actor.id,
            )
        )

    mapping = db.scalar(
        select(DeviceSimMapping).where(DeviceSimMapping.sim_id == old.id, DeviceSimMapping.is_active.is_(True))
    )
    if mapping is not None:
        mapping.is_active = False
        mapping.unmapped_at = utcnow()
        db.add(DeviceSimMapping(device_id=mapping.device_id, sim_id=new.id, is_active=True))

    db.add(SimReplacement(old_sim_id=old.id, new_sim_id=new.id, reason=reason, actor_id=actor.id))
    log_action(
        db,
        actor_id=actor.id,
        action="sim.replaced",
        entity="sim",
        entity_id=old.id,
        previous=previous,
        new={"replacement_sim_id": str(new.id), "reason": reason},
    )
    db.flush()
    return new


def list_sims(db: Session, actor: User, params, *, status, customer_id, sim_type):
    stmt = select(Sim).where(Sim.deleted_at.is_(None))
    if is_customer(actor):
        own = linked_customer(db, actor)
        if own is None:
            return [], 0
        stmt = stmt.where(Sim.customer_id == own.id)
    elif customer_id:
        stmt = stmt.where(Sim.customer_id == customer_id)
    if status:
        stmt = stmt.where(Sim.status == status)
    if sim_type:
        stmt = stmt.where(Sim.sim_type == sim_type)
    if params.q:
        like = f"%{params.q.strip()}%"
        stmt = stmt.where((Sim.msisdn.ilike(like)) | (Sim.iccid.ilike(like)))
    stmt = apply_sort(
        stmt,
        params.sort_by,
        params.sort_dir,
        {"created_at": Sim.created_at, "msisdn": Sim.msisdn, "status": Sim.status},
    )
    return paginate(db, stmt, params.page, params.page_size)


def replacement_history(db: Session, actor: User, sim_id):
    sim = get_sim(db, actor, sim_id)
    rows = db.scalars(
        select(SimReplacement)
        .where((SimReplacement.old_sim_id == sim.id) | (SimReplacement.new_sim_id == sim.id))
        .order_by(SimReplacement.replaced_at.desc())
    ).all()
    return list(rows)
