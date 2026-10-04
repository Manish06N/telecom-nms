"""A service request is a workflow. The effect runs only when the request is completed, in the same transaction."""

import uuid

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.enums import DeviceStatus, Role, ServiceRequestStatus, ServiceRequestType, SimStatus
from app.domain.errors import AppError
from app.domain.transitions import DEVICE_TRANSITIONS, SERVICE_REQUEST_TRANSITIONS, assert_transition
from app.models.identity import User
from app.models.operations import ServiceRequest, ServiceRequestEvent
from app.repositories.common import apply_sort, next_code, paginate
from app.services import device_service, sim_service, subscription_service
from app.services.access import is_customer, require_linked_customer
from app.services.records import log_action

CUSTOMER_CANCEL = {ServiceRequestStatus.SUBMITTED.value, ServiceRequestStatus.UNDER_REVIEW.value}


class SimReplacementPayload(BaseModel):
    new_sim_id: uuid.UUID
    reason: str = Field(min_length=3, max_length=300)


class NumberChangePayload(BaseModel):
    new_msisdn: str = Field(min_length=8, max_length=20)


class PlanChangePayload(BaseModel):
    new_plan_id: uuid.UUID


class DeviceReplacementPayload(BaseModel):
    new_device_id: uuid.UUID
    reason: str = Field(min_length=3, max_length=300)


class SubscriptionActionPayload(BaseModel):
    reason: str | None = None


PAYLOADS = {
    ServiceRequestType.SIM_REPLACEMENT.value: SimReplacementPayload,
    ServiceRequestType.NUMBER_CHANGE.value: NumberChangePayload,
    ServiceRequestType.PLAN_CHANGE.value: PlanChangePayload,
    ServiceRequestType.DEVICE_REPLACEMENT.value: DeviceReplacementPayload,
    ServiceRequestType.SERVICE_ACTIVATION.value: SubscriptionActionPayload,
    ServiceRequestType.SERVICE_SUSPENSION.value: SubscriptionActionPayload,
    ServiceRequestType.SERVICE_TERMINATION.value: SubscriptionActionPayload,
}


def _parse(request_type: str, payload: dict):
    model = PAYLOADS[request_type]
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise AppError("Service request payload does not match the request type", 422, "invalid_payload") from exc


def _owned_customer(db, actor, customer_id):
    from app.services.customer_service import get_customer

    if is_customer(actor):
        own = require_linked_customer(db, actor)
        if customer_id and customer_id != own.id:
            raise AppError("Customer not found", 404, "not_found")
        return own
    if customer_id is None:
        raise AppError("customer_id is required", 422, "invalid_request")
    return get_customer(db, actor, customer_id)


def create_request(db: Session, actor: User, data) -> ServiceRequest:
    if Role(actor.role) == Role.FIELD_TECHNICIAN:
        raise AppError("Technicians do not open service requests", 403, "forbidden")
    customer = _owned_customer(db, actor, data.customer_id)
    parsed = _parse(data.request_type.value, data.payload)
    _assert_refs(db, customer.id, data, parsed)
    row = ServiceRequest(
        code=next_code(db, "service_request", "SR"),
        customer_id=customer.id,
        request_type=data.request_type.value,
        status=ServiceRequestStatus.SUBMITTED.value,
        sim_id=data.sim_id,
        subscription_id=data.subscription_id,
        device_id=data.device_id,
        payload=parsed.model_dump(mode="json"),
        note=data.note,
        created_by=actor.id,
    )
    db.add(row)
    db.flush()
    _event(db, row, actor, None, row.status, "submitted")
    log_action(
        db,
        actor_id=actor.id,
        action="service_request.created",
        entity="service_request",
        entity_id=row.id,
        new={"code": row.code, "request_type": row.request_type},
    )
    return row


def _assert_refs(db, customer_id, data, parsed) -> None:
    request_type = data.request_type.value
    if request_type in {ServiceRequestType.SIM_REPLACEMENT.value, ServiceRequestType.NUMBER_CHANGE.value}:
        sim = sim_service._get(db, data.sim_id) if data.sim_id else None
        if sim is None or sim.customer_id != customer_id:
            raise AppError("A SIM belonging to this customer is required", 422, "invalid_request")
    if request_type == ServiceRequestType.SIM_REPLACEMENT.value:
        new_sim = sim_service._get(db, parsed.new_sim_id)
        if new_sim.status != SimStatus.AVAILABLE.value:
            raise AppError("Replacement SIM must be available", 409, "sim_not_available")
    if request_type in {
        ServiceRequestType.PLAN_CHANGE.value,
        ServiceRequestType.SERVICE_ACTIVATION.value,
        ServiceRequestType.SERVICE_SUSPENSION.value,
        ServiceRequestType.SERVICE_TERMINATION.value,
    }:
        if data.subscription_id is None:
            raise AppError("subscription_id is required", 422, "invalid_request")
        sub = subscription_service._get(db, data.subscription_id)
        if sub.customer_id != customer_id:
            raise AppError("Subscription does not belong to this customer", 409, "invalid_request")
    if request_type == ServiceRequestType.DEVICE_REPLACEMENT.value:
        if data.device_id is None:
            raise AppError("device_id is required", 422, "invalid_request")
        old = device_service._get(db, data.device_id)
        new = device_service._get(db, parsed.new_device_id)
        if old.customer_id != customer_id:
            raise AppError("Device does not belong to this customer", 409, "invalid_request")
        if new.status != DeviceStatus.IN_STOCK.value:
            raise AppError("Replacement device must be in stock", 409, "device_unavailable")


def _event(db, row, actor, from_status, to_status, note):
    db.add(
        ServiceRequestEvent(
            request_id=row.id,
            from_status=from_status,
            to_status=to_status,
            note=note,
            actor_id=actor.id,
        )
    )


def _get(db, request_id, actor) -> ServiceRequest:
    row = db.get(ServiceRequest, request_id)
    if row is None:
        raise AppError("Service request not found", 404, "not_found")
    if is_customer(actor):
        own = require_linked_customer(db, actor)
        if row.customer_id != own.id:
            raise AppError("Service request not found", 404, "not_found")
    return row


def _move(db, actor, request_id, new_status: ServiceRequestStatus, note: str | None) -> ServiceRequest:
    row = _get(db, request_id, actor)
    if is_customer(actor) and new_status != ServiceRequestStatus.CANCELLED:
        raise AppError("You can cancel a request, not process it", 403, "forbidden")
    if is_customer(actor) and row.status not in CUSTOMER_CANCEL:
        raise AppError("This request can no longer be cancelled", 409, "invalid_transition")
    previous = row.status
    assert_transition(SERVICE_REQUEST_TRANSITIONS, previous, new_status, "service request")
    if new_status == ServiceRequestStatus.COMPLETED:
        _apply(db, actor, row)
    row.status = new_status.value
    _event(db, row, actor, previous, row.status, note)
    log_action(
        db,
        actor_id=actor.id,
        action="service_request.updated",
        entity="service_request",
        entity_id=row.id,
        previous={"status": previous},
        new={"status": row.status, "note": note},
    )
    return row


def _apply(db, actor, row: ServiceRequest) -> None:
    payload = row.payload or {}
    kind = row.request_type
    if kind == ServiceRequestType.SIM_REPLACEMENT.value:
        sim_service.replace_sim(db, actor, row.sim_id, uuid.UUID(payload["new_sim_id"]), payload["reason"])
    elif kind == ServiceRequestType.NUMBER_CHANGE.value:
        sim_service.change_msisdn(db, actor, row.sim_id, payload["new_msisdn"])
    elif kind == ServiceRequestType.PLAN_CHANGE.value:
        subscription_service.apply_plan_change(db, actor, row.subscription_id, uuid.UUID(payload["new_plan_id"]))
    elif kind == ServiceRequestType.DEVICE_REPLACEMENT.value:
        _replace_device(db, actor, row.device_id, uuid.UUID(payload["new_device_id"]))
    elif kind == ServiceRequestType.SERVICE_ACTIVATION.value:
        subscription_service.reactivate(db, actor, row.subscription_id)
    elif kind == ServiceRequestType.SERVICE_SUSPENSION.value:
        subscription_service.suspend(db, actor, row.subscription_id, payload.get("reason"))
    elif kind == ServiceRequestType.SERVICE_TERMINATION.value:
        subscription_service.cancel(db, actor, row.subscription_id, payload.get("reason") or "service termination")
        sub = subscription_service._get(db, row.subscription_id)
        sim_service.change_status(db, actor, sub.sim_id, SimStatus.DEACTIVATED, "service termination")
    else:
        raise AppError("Unknown service request type", 400, "invalid_request")


def _replace_device(db, actor, old_id, new_id) -> None:
    old = device_service._get(db, old_id)
    new = device_service._get(db, new_id)
    mappings = list(device_service.active_mappings(db, old.id))
    for mapping in mappings:
        device_service.unmap_sim(db, actor, old.id, mapping.sim_id)
        device_service.map_sim(db, actor, new.id, mapping.sim_id)
    new.customer_id = old.customer_id
    if old.status != DeviceStatus.RETIRED.value:
        assert_transition(DEVICE_TRANSITIONS, old.status, DeviceStatus.RETIRED, "device")
        old.status = DeviceStatus.RETIRED.value
    db.flush()


def review(db, actor, request_id, note=None):
    return _move(db, actor, request_id, ServiceRequestStatus.UNDER_REVIEW, note)


def approve(db, actor, request_id, note=None):
    return _move(db, actor, request_id, ServiceRequestStatus.APPROVED, note)


def start(db, actor, request_id):
    return _move(db, actor, request_id, ServiceRequestStatus.IN_PROGRESS, "started")


def complete(db, actor, request_id, note=None):
    return _move(db, actor, request_id, ServiceRequestStatus.COMPLETED, note or "completed")


def reject(db, actor, request_id, note: str):
    return _move(db, actor, request_id, ServiceRequestStatus.REJECTED, note)


def cancel(db, actor, request_id, note: str | None = None):
    return _move(db, actor, request_id, ServiceRequestStatus.CANCELLED, note or "cancelled")


def history(db, actor, request_id):
    row = _get(db, request_id, actor)
    return list(
        db.scalars(
            select(ServiceRequestEvent).where(ServiceRequestEvent.request_id == row.id).order_by(ServiceRequestEvent.created_at)
        ).all()
    )


def list_requests(db, actor, params, *, status, request_type, customer_id):
    stmt = select(ServiceRequest)
    if is_customer(actor):
        own = require_linked_customer(db, actor)
        stmt = stmt.where(ServiceRequest.customer_id == own.id)
    elif customer_id:
        stmt = stmt.where(ServiceRequest.customer_id == customer_id)
    if status:
        stmt = stmt.where(ServiceRequest.status == status)
    if request_type:
        stmt = stmt.where(ServiceRequest.request_type == request_type)
    if params.q:
        like = f"%{params.q.strip()}%"
        stmt = stmt.where(ServiceRequest.code.ilike(like))
    stmt = apply_sort(
        stmt,
        params.sort_by,
        params.sort_dir,
        {"created_at": ServiceRequest.created_at, "code": ServiceRequest.code, "status": ServiceRequest.status},
    )
    return paginate(db, stmt, params.page, params.page_size)


def get_request(db, actor, request_id) -> ServiceRequest:
    return _get(db, request_id, actor)
