"""A plan is a product. Drafts are not for sale. Deactivating a plan stops new sales only."""

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.domain.enums import PlanCategory, PlanStatus
from app.domain.errors import AppError
from app.domain.transitions import PLAN_TRANSITIONS, assert_transition
from app.models.catalog import ServicePlan
from app.models.identity import User
from app.models.subscription import Subscription
from app.repositories.common import apply_sort, next_code, paginate
from app.services.records import log_action
from app.utils.serialize import snapshot

PLAN_FIELDS = (
    "name",
    "description",
    "billing_type",
    "category",
    "price",
    "validity_days",
    "data_limit_mb",
    "voice_limit_minutes",
    "sms_limit",
    "status",
)


def _check_limits(category: str, data: int, voice: int, sms: int) -> None:
    included = [name for name, value in (("data", data), ("voice", voice), ("sms", sms)) if value != 0]
    if category == PlanCategory.DATA.value and data == 0:
        raise AppError("A data plan needs a data limit. Use -1 for unlimited.", 422, "invalid_plan")
    if category == PlanCategory.VOICE.value and voice == 0:
        raise AppError("A voice plan needs a voice limit. Use -1 for unlimited.", 422, "invalid_plan")
    if category == PlanCategory.SMS.value and sms == 0:
        raise AppError("An SMS plan needs an SMS limit. Use -1 for unlimited.", 422, "invalid_plan")
    if category == PlanCategory.COMBO.value and len(included) < 2:
        raise AppError("A combo plan must include at least two of data, voice, and SMS", 422, "invalid_plan")


def _get(db: Session, plan_id) -> ServicePlan:
    plan = db.get(ServicePlan, plan_id)
    if plan is None or plan.deleted_at is not None:
        raise AppError("Plan not found", 404, "not_found")
    return plan


def create_plan(db: Session, actor: User, data) -> ServicePlan:
    _check_limits(data.category.value, data.data_limit_mb, data.voice_limit_minutes, data.sms_limit)
    prefix = "PRE" if data.billing_type.value == "prepaid" else "POS"
    plan = ServicePlan(
        code=next_code(db, "plan", prefix),
        name=data.name.strip(),
        description=data.description,
        billing_type=data.billing_type.value,
        category=data.category.value,
        price=data.price,
        validity_days=data.validity_days,
        data_limit_mb=data.data_limit_mb,
        voice_limit_minutes=data.voice_limit_minutes,
        sms_limit=data.sms_limit,
        status=PlanStatus.DRAFT.value,
    )
    db.add(plan)
    db.flush()
    log_action(db, actor_id=actor.id, action="plan.created", entity="plan", entity_id=plan.id, new=snapshot(plan, PLAN_FIELDS))
    return plan


def update_plan(db: Session, actor: User, plan_id, data) -> ServicePlan:
    plan = _get(db, plan_id)
    previous = snapshot(plan, PLAN_FIELDS)
    changes = data.model_dump(exclude_unset=True)
    for field, value in changes.items():
        if hasattr(value, "value"):
            value = value.value
        setattr(plan, field, value)
    _check_limits(plan.category, plan.data_limit_mb, plan.voice_limit_minutes, plan.sms_limit)
    log_action(
        db,
        actor_id=actor.id,
        action="plan.updated",
        entity="plan",
        entity_id=plan.id,
        previous=previous,
        new=snapshot(plan, PLAN_FIELDS),
    )
    return plan


def set_plan_active(db: Session, actor: User, plan_id, active: bool) -> ServicePlan:
    plan = _get(db, plan_id)
    target = PlanStatus.ACTIVE if active else PlanStatus.INACTIVE
    assert_transition(PLAN_TRANSITIONS, plan.status, target, "plan")
    if active:
        _check_limits(plan.category, plan.data_limit_mb, plan.voice_limit_minutes, plan.sms_limit)
    previous = snapshot(plan, ("status",))
    plan.status = target.value
    log_action(
        db,
        actor_id=actor.id,
        action="plan.activated" if active else "plan.deactivated",
        entity="plan",
        entity_id=plan.id,
        previous=previous,
        new=snapshot(plan, ("status",)),
    )
    return plan


def archive_plan(db: Session, actor: User, plan_id) -> None:
    plan = _get(db, plan_id)
    if plan.status != PlanStatus.DRAFT.value:
        raise AppError("Only a draft plan can be archived. Deactivate a live plan instead.", 409, "plan_not_draft")
    sold = db.scalar(select(Subscription.id).where(Subscription.plan_id == plan.id))
    if sold is not None:
        raise AppError("This plan was already sold and must be kept for history", 409, "plan_in_use")
    plan.soft_delete()
    log_action(db, actor_id=actor.id, action="plan.archived", entity="plan", entity_id=plan.id, new={"deleted_at": str(plan.deleted_at)})


def get_plan(db: Session, plan_id) -> ServicePlan:
    return _get(db, plan_id)


def list_plans(db: Session, params, *, billing_type, category, status, min_price, max_price):
    stmt = select(ServicePlan).where(ServicePlan.deleted_at.is_(None))
    if billing_type:
        stmt = stmt.where(ServicePlan.billing_type == billing_type)
    if category:
        stmt = stmt.where(ServicePlan.category == category)
    if status:
        stmt = stmt.where(ServicePlan.status == status)
    if min_price is not None:
        stmt = stmt.where(ServicePlan.price >= min_price)
    if max_price is not None:
        stmt = stmt.where(ServicePlan.price <= max_price)
    if params.q:
        like = f"%{params.q.strip()}%"
        stmt = stmt.where(or_(ServicePlan.name.ilike(like), ServicePlan.code.ilike(like)))
    stmt = apply_sort(
        stmt,
        params.sort_by,
        params.sort_dir,
        {
            "created_at": ServicePlan.created_at,
            "name": ServicePlan.name,
            "price": ServicePlan.price,
            "code": ServicePlan.code,
        },
    )
    return paginate(db, stmt, params.page, params.page_size)


def compare_plans(db: Session, plan_ids: list) -> dict:
    if len(set(plan_ids)) != len(plan_ids):
        raise AppError("Plan ids must be unique", 422, "invalid_compare")
    plans = []
    for plan_id in plan_ids:
        plans.append(_get(db, plan_id))
    fields = [
        "price",
        "billing_type",
        "category",
        "validity_days",
        "data_limit_mb",
        "voice_limit_minutes",
        "sms_limit",
        "status",
    ]
    differences = []
    for field in fields:
        values = {str(getattr(plan, field)) for plan in plans}
        if len(values) > 1:
            detail = ", ".join(f"{plan.code}={getattr(plan, field)}" for plan in plans)
            differences.append(f"{field} differs: {detail}")
    return {"plans": plans, "differences": differences}
