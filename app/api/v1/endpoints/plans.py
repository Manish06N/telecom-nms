import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import PageParams, as_page, require
from app.db.session import get_db
from app.domain.enums import BillingType, Permission, PlanCategory, PlanStatus
from app.schemas.contracts import Page, PlanCompareRequest, PlanCompareResult, PlanCreate, PlanRead, PlanUpdate
from app.services import plan_service

router = APIRouter(prefix="/plans", tags=["Service plans"])


@router.post("", response_model=PlanRead, status_code=201)
def create_plan(body: PlanCreate, user=Depends(require(Permission.PLAN_WRITE)), db: Session = Depends(get_db)):
    return plan_service.create_plan(db, user, body)


@router.get("", response_model=Page[PlanRead])
def list_plans(
    params: PageParams = Depends(),
    billing_type: BillingType | None = None,
    category: PlanCategory | None = None,
    status: PlanStatus | None = None,
    min_price: Decimal | None = None,
    max_price: Decimal | None = None,
    user=Depends(require(Permission.PLAN_READ)),
    db: Session = Depends(get_db),
):
    rows, total = plan_service.list_plans(
        db,
        params,
        billing_type=billing_type.value if billing_type else None,
        category=category.value if category else None,
        status=status.value if status else None,
        min_price=min_price,
        max_price=max_price,
    )
    return as_page(rows, total, params)


@router.post("/compare", response_model=PlanCompareResult)
def compare(body: PlanCompareRequest, user=Depends(require(Permission.PLAN_READ)), db: Session = Depends(get_db)):
    return plan_service.compare_plans(db, body.plan_ids)


@router.get("/{plan_id}", response_model=PlanRead)
def get_plan(plan_id: uuid.UUID, user=Depends(require(Permission.PLAN_READ)), db: Session = Depends(get_db)):
    return plan_service.get_plan(db, plan_id)


@router.patch("/{plan_id}", response_model=PlanRead)
def update_plan(plan_id: uuid.UUID, body: PlanUpdate, user=Depends(require(Permission.PLAN_WRITE)), db: Session = Depends(get_db)):
    return plan_service.update_plan(db, user, plan_id, body)


@router.post("/{plan_id}/activate", response_model=PlanRead)
def activate(plan_id: uuid.UUID, user=Depends(require(Permission.PLAN_WRITE)), db: Session = Depends(get_db)):
    return plan_service.set_plan_active(db, user, plan_id, True)


@router.post("/{plan_id}/deactivate", response_model=PlanRead)
def deactivate(plan_id: uuid.UUID, user=Depends(require(Permission.PLAN_WRITE)), db: Session = Depends(get_db)):
    return plan_service.set_plan_active(db, user, plan_id, False)


@router.delete("/{plan_id}", status_code=204)
def archive(plan_id: uuid.UUID, user=Depends(require(Permission.PLAN_WRITE)), db: Session = Depends(get_db)):
    plan_service.archive_plan(db, user, plan_id)
