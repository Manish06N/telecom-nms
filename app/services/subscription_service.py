"""The subscription is the contract: which customer, which SIM, which plan, and which cycle."""

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.domain.enums import (
    CustomerStatus,
    PlanStatus,
    SimStatus,
    SubscriptionEventType,
    SubscriptionStatus,
)
from app.domain.errors import AppError
from app.domain.transitions import SUBSCRIPTION_TRANSITIONS, assert_transition
from app.models.catalog import ServicePlan
from app.models.customer import Customer
from app.models.identity import User
from app.models.inventory import Sim
from app.models.subscription import Subscription, SubscriptionEvent
from app.repositories.common import apply_sort, next_code, paginate
from app.services.access import assert_customer_visible, is_customer, linked_customer
from app.services.records import log_action
from app.utils.serialize import snapshot
from app.utils.time import utcnow

SUB_FIELDS = ("status", "plan_id", "sim_id", "cycle_start", "cycle_end", "end_date")
OPEN_STATUSES = ("pending", "active", "suspended")


def _query():
    return select(Subscription).options(
        selectinload(Subscription.plan),
        selectinload(Subscription.sim),
        selectinload(Subscription.customer),
    )


def _get(db: Session, subscription_id) -> Subscription:
    row = db.scalar(_query().where(Subscription.id == subscription_id))
    if row is None:
        raise AppError("Subscription not found", 404, "not_found")
    return row


def get_subscription(db: Session, actor: User, subscription_id) -> Subscription:
    row = _get(db, subscription_id)
    assert_customer_visible(actor, row.customer)
    return row


def _event(db, sub: Subscription, actor: User, event_type: str, note: str | None, from_plan=None, to_plan=None):
    db.add(
        SubscriptionEvent(
            subscription_id=sub.id,
            event_type=event_type,
            from_plan_id=from_plan,
            to_plan_id=to_plan,
            note=note,
            actor_id=actor.id if actor else None,
        )
    )


def _active_plan(db: Session, plan_id) -> ServicePlan:
    plan = db.get(ServicePlan, plan_id)
    if plan is None or plan.deleted_at is not None:
        raise AppError("Plan not found", 404, "not_found")
    if plan.status != PlanStatus.ACTIVE.value:
        raise AppError("Only an active plan can be sold", 409, "plan_inactive")
    return plan


def create_subscription(db: Session, actor: User, data) -> Subscription:
    customer = db.get(Customer, data.customer_id)
    if customer is None or customer.deleted_at is not None:
        raise AppError("Customer not found", 404, "not_found")
    assert_customer_visible(actor, customer)
    if customer.status != CustomerStatus.ACTIVE.value:
        raise AppError("Customer must be active", 409, "customer_inactive")
    sim = db.get(Sim, data.sim_id)
    if sim is None or sim.deleted_at is not None:
        raise AppError("SIM not found", 404, "not_found")
    if sim.status != SimStatus.ACTIVE.value or sim.customer_id != customer.id:
        raise AppError("SIM must be active and belong to this customer", 409, "invalid_sim")
    plan = _active_plan(db, data.plan_id)
    occupying = db.scalar(
        select(Subscription).where(Subscription.sim_id == sim.id, Subscription.status.in_(OPEN_STATUSES))
    )
    if occupying is not None:
        raise AppError("This SIM already has an open subscription", 409, "sim_already_subscribed")
    start = data.start_date or utcnow()
    if start.tzinfo is not None:
        start = start.replace(tzinfo=None)
    end = start + timedelta(days=plan.validity_days)
    status = SubscriptionStatus.PENDING if start > utcnow() else SubscriptionStatus.ACTIVE
    sub = Subscription(
        code=next_code(db, "subscription", "SUB"),
        customer_id=customer.id,
        sim_id=sim.id,
        plan_id=plan.id,
        status=status.value,
        start_date=start,
        end_date=end,
        cycle_start=start,
        cycle_end=end,
    )
    db.add(sub)
    db.flush()
    _event(db, sub, actor, SubscriptionEventType.CREATED.value, None, to_plan=plan.id)
    log_action(
        db,
        actor_id=actor.id,
        action="subscription.created",
        entity="subscription",
        entity_id=sub.id,
        new=snapshot(sub, SUB_FIELDS),
    )
    return sub


def _switch_plan(db, actor, sub: Subscription, new_plan: ServicePlan, event_type: str) -> Subscription:
    if sub.status != SubscriptionStatus.ACTIVE.value:
        raise AppError("Plan changes are allowed only on an active subscription", 409, "invalid_transition")
    if new_plan.id == sub.plan_id:
        raise AppError("The subscription is already on this plan", 409, "same_plan")
    if new_plan.billing_type != sub.plan.billing_type:
        raise AppError("Cannot switch between prepaid and postpaid on the same subscription", 409, "billing_type_mismatch")
    previous = snapshot(sub, ("plan_id",))
    old_plan_id = sub.plan_id
    sub.plan = new_plan
    sub.threshold_notified = False
    _event(db, sub, actor, event_type, None, from_plan=old_plan_id, to_plan=new_plan.id)
    action = "subscription.upgraded" if event_type == SubscriptionEventType.UPGRADED.value else "subscription.downgraded"
    log_action(
        db,
        actor_id=actor.id,
        action=action,
        entity="subscription",
        entity_id=sub.id,
        previous=previous,
        new=snapshot(sub, ("plan_id",)),
    )
    db.flush()
    return _get(db, sub.id)


def upgrade(db: Session, actor: User, subscription_id, plan_id) -> Subscription:
    sub = get_subscription(db, actor, subscription_id)
    new_plan = _active_plan(db, plan_id)
    if new_plan.price <= sub.plan.price:
        raise AppError("An upgrade must move to a higher priced plan", 409, "not_an_upgrade")
    return _switch_plan(db, actor, sub, new_plan, SubscriptionEventType.UPGRADED.value)


def downgrade(db: Session, actor: User, subscription_id, plan_id) -> Subscription:
    sub = get_subscription(db, actor, subscription_id)
    new_plan = _active_plan(db, plan_id)
    if new_plan.price >= sub.plan.price:
        raise AppError("A downgrade must move to a lower priced plan", 409, "not_a_downgrade")
    return _switch_plan(db, actor, sub, new_plan, SubscriptionEventType.DOWNGRADED.value)


def apply_plan_change(db: Session, actor: User, subscription_id, plan_id) -> Subscription:
    """Used by service requests: the price decides upgrade versus downgrade."""
    sub = get_subscription(db, actor, subscription_id)
    new_plan = _active_plan(db, plan_id)
    if new_plan.price > sub.plan.price:
        return _switch_plan(db, actor, sub, new_plan, SubscriptionEventType.UPGRADED.value)
    if new_plan.price < sub.plan.price:
        return _switch_plan(db, actor, sub, new_plan, SubscriptionEventType.DOWNGRADED.value)
    raise AppError("The new plan has the same price", 409, "same_plan")


def renew(db: Session, actor: User, subscription_id) -> Subscription:
    sub = get_subscription(db, actor, subscription_id)
    if sub.status not in {SubscriptionStatus.ACTIVE.value, SubscriptionStatus.EXPIRED.value}:
        raise AppError("Only an active or expired subscription can be renewed", 409, "invalid_transition")
    if sub.status == SubscriptionStatus.EXPIRED.value:
        assert_transition(SUBSCRIPTION_TRANSITIONS, sub.status, SubscriptionStatus.ACTIVE, "subscription")
        sub.status = SubscriptionStatus.ACTIVE.value
        sub.cycle_start = utcnow()
    else:
        sub.cycle_start = sub.cycle_end
    sub.cycle_end = sub.cycle_start + timedelta(days=sub.plan.validity_days)
    sub.end_date = sub.cycle_end
    sub.expiry_notified = False
    sub.threshold_notified = False
    _event(db, sub, actor, SubscriptionEventType.RENEWED.value, None, to_plan=sub.plan_id)
    log_action(
        db,
        actor_id=actor.id,
        action="subscription.renewed",
        entity="subscription",
        entity_id=sub.id,
        new=snapshot(sub, SUB_FIELDS),
    )
    return sub


def suspend(db: Session, actor: User, subscription_id, reason: str | None) -> Subscription:
    sub = get_subscription(db, actor, subscription_id)
    assert_transition(SUBSCRIPTION_TRANSITIONS, sub.status, SubscriptionStatus.SUSPENDED, "subscription")
    sub.status = SubscriptionStatus.SUSPENDED.value
    sub.suspended_at = utcnow()
    _event(db, sub, actor, SubscriptionEventType.SUSPENDED.value, reason)
    log_action(
        db,
        actor_id=actor.id,
        action="subscription.suspended",
        entity="subscription",
        entity_id=sub.id,
        new={"status": sub.status, "reason": reason},
    )
    return sub


def reactivate(db: Session, actor: User, subscription_id) -> Subscription:
    sub = get_subscription(db, actor, subscription_id)
    assert_transition(SUBSCRIPTION_TRANSITIONS, sub.status, SubscriptionStatus.ACTIVE, "subscription")
    if sub.status == SubscriptionStatus.SUSPENDED.value and sub.cycle_end < utcnow():
        raise AppError("This cycle has ended. Renew the subscription instead of reactivating it.", 409, "cycle_ended")
    if sub.status == SubscriptionStatus.PENDING.value and sub.start_date > utcnow():
        raise AppError("This subscription has not reached its start date", 409, "not_started")
    sub.status = SubscriptionStatus.ACTIVE.value
    sub.suspended_at = None
    _event(db, sub, actor, SubscriptionEventType.REACTIVATED.value, None)
    log_action(
        db,
        actor_id=actor.id,
        action="subscription.reactivated",
        entity="subscription",
        entity_id=sub.id,
        new=snapshot(sub, ("status",)),
    )
    return sub


def cancel(db: Session, actor: User, subscription_id, reason: str | None) -> Subscription:
    sub = get_subscription(db, actor, subscription_id)
    assert_transition(SUBSCRIPTION_TRANSITIONS, sub.status, SubscriptionStatus.CANCELLED, "subscription")
    sub.status = SubscriptionStatus.CANCELLED.value
    sub.cancelled_at = utcnow()
    _event(db, sub, actor, SubscriptionEventType.CANCELLED.value, reason)
    log_action(
        db,
        actor_id=actor.id,
        action="subscription.cancelled",
        entity="subscription",
        entity_id=sub.id,
        new={"status": sub.status, "reason": reason},
    )
    return sub


def history(db: Session, actor: User, subscription_id):
    sub = get_subscription(db, actor, subscription_id)
    rows = db.scalars(
        select(SubscriptionEvent)
        .where(SubscriptionEvent.subscription_id == sub.id)
        .order_by(SubscriptionEvent.created_at.desc())
    ).all()
    return list(rows)


def list_subscriptions(db: Session, actor: User, params, *, status, customer_id, sim_id, plan_id):
    stmt = _query()
    if is_customer(actor):
        own = linked_customer(db, actor)
        if own is None:
            return [], 0
        stmt = stmt.where(Subscription.customer_id == own.id)
    elif customer_id:
        stmt = stmt.where(Subscription.customer_id == customer_id)
    if status:
        stmt = stmt.where(Subscription.status == status)
    if sim_id:
        stmt = stmt.where(Subscription.sim_id == sim_id)
    if plan_id:
        stmt = stmt.where(Subscription.plan_id == plan_id)
    if params.q:
        like = f"%{params.q.strip()}%"
        stmt = stmt.where(Subscription.code.ilike(like))
    stmt = apply_sort(
        stmt,
        params.sort_by,
        params.sort_dir,
        {"created_at": Subscription.created_at, "code": Subscription.code, "end_date": Subscription.end_date},
    )
    return paginate(db, stmt, params.page, params.page_size)
