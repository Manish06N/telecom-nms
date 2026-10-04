import uuid

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.api.deps import PageParams, as_page, require
from app.db.session import get_db
from app.domain.enums import DeviceType, Permission, SimStatus, SimType
from app.schemas.contracts import (
    DeviceCreate,
    DeviceRead,
    MappingRead,
    NumberChange,
    Page,
    SimActivate,
    SimCreate,
    SimMapRequest,
    SimRead,
    SimReplace,
    SimReplacementRead,
    SimStatusChange,
    SubscriptionCreate,
    SubscriptionEventRead,
    SubscriptionRead,
    PlanChange,
    ReasonBody,
    UsageCreate,
    UsageListRead,
    UsageWriteResult,
    UtilizationRead,
)
from app.services import device_service, sim_service, subscription_service, usage_service

sims = APIRouter(prefix="/sims", tags=["SIM cards"])
devices = APIRouter(prefix="/devices", tags=["Devices"])
subscriptions = APIRouter(prefix="/subscriptions", tags=["Subscriptions"])
usage = APIRouter(prefix="/usage", tags=["Usage"])


@sims.post("", response_model=SimRead, status_code=201)
def register_sim(body: SimCreate, user=Depends(require(Permission.SIM_WRITE)), db: Session = Depends(get_db)):
    return sim_service.register_sim(db, user, body)


@sims.get("", response_model=Page[SimRead])
def list_sims(
    params: PageParams = Depends(),
    status: SimStatus | None = None,
    customer_id: uuid.UUID | None = None,
    sim_type: SimType | None = None,
    user=Depends(require(Permission.SIM_READ)),
    db: Session = Depends(get_db),
):
    rows, total = sim_service.list_sims(
        db, user, params, status=status.value if status else None, customer_id=customer_id, sim_type=sim_type.value if sim_type else None
    )
    return as_page(rows, total, params)


@sims.get("/{sim_id}", response_model=SimRead)
def get_sim(sim_id: uuid.UUID, user=Depends(require(Permission.SIM_READ)), db: Session = Depends(get_db)):
    return sim_service.get_sim(db, user, sim_id)


@sims.post("/{sim_id}/activate", response_model=SimRead)
def activate_sim(sim_id: uuid.UUID, body: SimActivate, user=Depends(require(Permission.SIM_WRITE)), db: Session = Depends(get_db)):
    return sim_service.activate_sim(db, user, sim_id, body.customer_id)


@sims.post("/{sim_id}/status", response_model=SimRead)
def change_status(
    sim_id: uuid.UUID,
    body: SimStatusChange,
    background: BackgroundTasks,
    user=Depends(require(Permission.SIM_WRITE)),
    db: Session = Depends(get_db),
):
    return sim_service.change_status(db, user, sim_id, body.status, body.reason, background)


@sims.post("/{sim_id}/replace", response_model=SimRead)
def replace_sim(sim_id: uuid.UUID, body: SimReplace, user=Depends(require(Permission.SIM_WRITE)), db: Session = Depends(get_db)):
    return sim_service.replace_sim(db, user, sim_id, body.new_sim_id, body.reason)


@sims.post("/{sim_id}/number", response_model=SimRead)
def change_number(sim_id: uuid.UUID, body: NumberChange, user=Depends(require(Permission.SIM_WRITE)), db: Session = Depends(get_db)):
    return sim_service.change_msisdn(db, user, sim_id, body.new_msisdn)


@sims.get("/{sim_id}/replacements", response_model=list[SimReplacementRead])
def replacements(sim_id: uuid.UUID, user=Depends(require(Permission.SIM_READ)), db: Session = Depends(get_db)):
    return sim_service.replacement_history(db, user, sim_id)


@devices.post("", response_model=DeviceRead, status_code=201)
def register_device(body: DeviceCreate, user=Depends(require(Permission.DEVICE_WRITE)), db: Session = Depends(get_db)):
    return device_service.register_device(db, user, body)


@devices.get("", response_model=Page[DeviceRead])
def list_devices(
    params: PageParams = Depends(),
    status: str | None = None,
    customer_id: uuid.UUID | None = None,
    device_type: DeviceType | None = None,
    user=Depends(require(Permission.DEVICE_READ)),
    db: Session = Depends(get_db),
):
    rows, total = device_service.list_devices(
        db, user, params, status=status, customer_id=customer_id, device_type=device_type.value if device_type else None
    )
    return as_page(rows, total, params)


@devices.get("/{device_id}", response_model=DeviceRead)
def get_device(device_id: uuid.UUID, user=Depends(require(Permission.DEVICE_READ)), db: Session = Depends(get_db)):
    return device_service.get_device(db, user, device_id)


@devices.post("/{device_id}/map-sim", response_model=MappingRead, status_code=201)
def map_sim(device_id: uuid.UUID, body: SimMapRequest, user=Depends(require(Permission.DEVICE_WRITE)), db: Session = Depends(get_db)):
    return device_service.map_sim(db, user, device_id, body.sim_id)


@devices.post("/{device_id}/unmap-sim", response_model=DeviceRead)
def unmap_sim(device_id: uuid.UUID, body: SimMapRequest, user=Depends(require(Permission.DEVICE_WRITE)), db: Session = Depends(get_db)):
    return device_service.unmap_sim(db, user, device_id, body.sim_id)


@subscriptions.post("", response_model=SubscriptionRead, status_code=201)
def create_subscription(body: SubscriptionCreate, user=Depends(require(Permission.SUBSCRIPTION_WRITE)), db: Session = Depends(get_db)):
    return subscription_service.create_subscription(db, user, body)


@subscriptions.get("", response_model=Page[SubscriptionRead])
def list_subscriptions(
    params: PageParams = Depends(),
    status: str | None = None,
    customer_id: uuid.UUID | None = None,
    sim_id: uuid.UUID | None = None,
    plan_id: uuid.UUID | None = None,
    user=Depends(require(Permission.SUBSCRIPTION_READ)),
    db: Session = Depends(get_db),
):
    rows, total = subscription_service.list_subscriptions(
        db, user, params, status=status, customer_id=customer_id, sim_id=sim_id, plan_id=plan_id
    )
    return as_page(rows, total, params)


@subscriptions.get("/{subscription_id}", response_model=SubscriptionRead)
def get_subscription(subscription_id: uuid.UUID, user=Depends(require(Permission.SUBSCRIPTION_READ)), db: Session = Depends(get_db)):
    return subscription_service.get_subscription(db, user, subscription_id)


@subscriptions.get("/{subscription_id}/history", response_model=list[SubscriptionEventRead])
def history(subscription_id: uuid.UUID, user=Depends(require(Permission.SUBSCRIPTION_READ)), db: Session = Depends(get_db)):
    return subscription_service.history(db, user, subscription_id)


@subscriptions.post("/{subscription_id}/upgrade", response_model=SubscriptionRead)
def upgrade(subscription_id: uuid.UUID, body: PlanChange, user=Depends(require(Permission.SUBSCRIPTION_WRITE)), db: Session = Depends(get_db)):
    return subscription_service.upgrade(db, user, subscription_id, body.plan_id)


@subscriptions.post("/{subscription_id}/downgrade", response_model=SubscriptionRead)
def downgrade(subscription_id: uuid.UUID, body: PlanChange, user=Depends(require(Permission.SUBSCRIPTION_WRITE)), db: Session = Depends(get_db)):
    return subscription_service.downgrade(db, user, subscription_id, body.plan_id)


@subscriptions.post("/{subscription_id}/renew", response_model=SubscriptionRead)
def renew(subscription_id: uuid.UUID, user=Depends(require(Permission.SUBSCRIPTION_WRITE)), db: Session = Depends(get_db)):
    return subscription_service.renew(db, user, subscription_id)


@subscriptions.post("/{subscription_id}/suspend", response_model=SubscriptionRead)
def suspend(subscription_id: uuid.UUID, body: ReasonBody, user=Depends(require(Permission.SUBSCRIPTION_WRITE)), db: Session = Depends(get_db)):
    return subscription_service.suspend(db, user, subscription_id, body.reason)


@subscriptions.post("/{subscription_id}/reactivate", response_model=SubscriptionRead)
def reactivate(subscription_id: uuid.UUID, user=Depends(require(Permission.SUBSCRIPTION_WRITE)), db: Session = Depends(get_db)):
    return subscription_service.reactivate(db, user, subscription_id)


@subscriptions.post("/{subscription_id}/cancel", response_model=SubscriptionRead)
def cancel(subscription_id: uuid.UUID, body: ReasonBody, user=Depends(require(Permission.SUBSCRIPTION_WRITE)), db: Session = Depends(get_db)):
    return subscription_service.cancel(db, user, subscription_id, body.reason)


@usage.post("", response_model=UsageWriteResult, status_code=201)
def record_usage(body: UsageCreate, background: BackgroundTasks, user=Depends(require(Permission.USAGE_WRITE)), db: Session = Depends(get_db)):
    return usage_service.record_usage(db, user, body, background)


@usage.get("/customers/{customer_id}", response_model=UsageListRead)
def customer_usage(
    customer_id: uuid.UUID,
    month: str | None = None,
    user=Depends(require(Permission.USAGE_READ)),
    db: Session = Depends(get_db),
):
    return usage_service.customer_usage(db, user, customer_id, month)


@usage.get("/sims/{sim_id}", response_model=UsageListRead)
def sim_usage(sim_id: uuid.UUID, month: str | None = None, user=Depends(require(Permission.USAGE_READ)), db: Session = Depends(get_db)):
    return usage_service.sim_usage(db, user, sim_id, month)


@usage.get("/subscriptions/{subscription_id}/utilization", response_model=UtilizationRead)
def utilization(subscription_id: uuid.UUID, user=Depends(require(Permission.USAGE_READ)), db: Session = Depends(get_db)):
    return usage_service.utilization(db, user, subscription_id)
