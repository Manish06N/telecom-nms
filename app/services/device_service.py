"""One SIM sits in one device. A handset may hold two active SIMs."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.enums import DeviceStatus, SimStatus
from app.domain.errors import AppError
from app.domain.transitions import DEVICE_TRANSITIONS, assert_transition
from app.domain.validators import validate_imei
from app.models.identity import User
from app.models.inventory import Device, DeviceSimMapping, Sim
from app.repositories.common import apply_sort, paginate
from app.services.access import is_customer, linked_customer
from app.services.records import log_action
from app.utils.serialize import snapshot
from app.utils.time import utcnow

DEVICE_FIELDS = ("imei", "model", "manufacturer", "device_type", "status", "customer_id")
MAX_ACTIVE_SIMS = 2


def _get(db: Session, device_id) -> Device:
    device = db.get(Device, device_id)
    if device is None or device.deleted_at is not None:
        raise AppError("Device not found", 404, "not_found")
    return device


def get_device(db: Session, actor: User, device_id) -> Device:
    device = _get(db, device_id)
    if is_customer(actor):
        own = linked_customer(db, actor)
        if own is None or device.customer_id != own.id:
            raise AppError("Device not found", 404, "not_found")
    return device


def register_device(db: Session, actor: User, data) -> Device:
    imei = validate_imei(data.imei)
    if db.scalar(select(Device).where(Device.imei == imei, Device.deleted_at.is_(None))):
        raise AppError("A device with this IMEI is already registered", 409, "duplicate_imei")
    device = Device(
        imei=imei,
        model=data.model.strip(),
        manufacturer=data.manufacturer.strip(),
        device_type=data.device_type.value,
        status=DeviceStatus.IN_STOCK.value,
        customer_id=data.customer_id,
    )
    if data.customer_id is not None:
        from app.models.customer import Customer

        customer = db.get(Customer, data.customer_id)
        if customer is None or customer.deleted_at is not None:
            raise AppError("Customer not found", 404, "not_found")
    db.add(device)
    db.flush()
    log_action(
        db,
        actor_id=actor.id,
        action="device.registered",
        entity="device",
        entity_id=device.id,
        new=snapshot(device, DEVICE_FIELDS),
    )
    return device


def map_sim(db: Session, actor: User, device_id, sim_id) -> DeviceSimMapping:
    device = _get(db, device_id)
    sim = db.get(Sim, sim_id)
    if sim is None or sim.deleted_at is not None:
        raise AppError("SIM not found", 404, "not_found")
    if device.status in {DeviceStatus.LOST.value, DeviceStatus.BLOCKED.value, DeviceStatus.RETIRED.value}:
        raise AppError("This device cannot accept a SIM", 409, "device_unavailable")
    if sim.status != SimStatus.ACTIVE.value:
        raise AppError("Only an active SIM can be installed in a device", 409, "invalid_sim_assignment")
    if sim.customer_id is None:
        raise AppError("Assign the SIM to a customer before installing it", 409, "invalid_sim_assignment")
    if device.customer_id and device.customer_id != sim.customer_id:
        raise AppError("SIM and device belong to different customers", 409, "invalid_sim_assignment")
    already = db.scalar(
        select(DeviceSimMapping).where(DeviceSimMapping.sim_id == sim.id, DeviceSimMapping.is_active.is_(True))
    )
    if already is not None:
        raise AppError("This SIM is already installed in a device", 409, "sim_already_mapped")
    active_count = db.scalar(
        select(func.count())
        .select_from(DeviceSimMapping)
        .where(DeviceSimMapping.device_id == device.id, DeviceSimMapping.is_active.is_(True))
    ) or 0
    if active_count >= MAX_ACTIVE_SIMS:
        raise AppError("This device already has two active SIMs", 409, "mapping_limit")
    if device.customer_id is None:
        device.customer_id = sim.customer_id
    if device.status in {DeviceStatus.IN_STOCK.value, DeviceStatus.INACTIVE.value}:
        assert_transition(DEVICE_TRANSITIONS, device.status, DeviceStatus.ACTIVE, "device")
        device.status = DeviceStatus.ACTIVE.value
    mapping = DeviceSimMapping(device_id=device.id, sim_id=sim.id, is_active=True)
    db.add(mapping)
    db.flush()
    log_action(
        db,
        actor_id=actor.id,
        action="device.sim_mapped",
        entity="device",
        entity_id=device.id,
        new={"sim_id": str(sim.id), "imei": device.imei},
    )
    return mapping


def unmap_sim(db: Session, actor: User, device_id, sim_id) -> Device:
    device = _get(db, device_id)
    mapping = db.scalar(
        select(DeviceSimMapping).where(
            DeviceSimMapping.device_id == device.id,
            DeviceSimMapping.sim_id == sim_id,
            DeviceSimMapping.is_active.is_(True),
        )
    )
    if mapping is None:
        raise AppError("That SIM is not installed in this device", 404, "mapping_not_found")
    mapping.is_active = False
    mapping.unmapped_at = utcnow()
    db.flush()
    remaining = db.scalar(
        select(func.count())
        .select_from(DeviceSimMapping)
        .where(DeviceSimMapping.device_id == device.id, DeviceSimMapping.is_active.is_(True))
    ) or 0
    if remaining == 0 and device.status == DeviceStatus.ACTIVE.value:
        device.status = DeviceStatus.INACTIVE.value
    log_action(
        db,
        actor_id=actor.id,
        action="device.sim_unmapped",
        entity="device",
        entity_id=device.id,
        new={"sim_id": str(sim_id)},
    )
    return device


def list_devices(db: Session, actor: User, params, *, status, customer_id, device_type):
    stmt = select(Device).where(Device.deleted_at.is_(None))
    if is_customer(actor):
        own = linked_customer(db, actor)
        if own is None:
            return [], 0
        stmt = stmt.where(Device.customer_id == own.id)
    elif customer_id:
        stmt = stmt.where(Device.customer_id == customer_id)
    if status:
        stmt = stmt.where(Device.status == status)
    if device_type:
        stmt = stmt.where(Device.device_type == device_type)
    if params.q:
        like = f"%{params.q.strip()}%"
        stmt = stmt.where((Device.imei.ilike(like)) | (Device.model.ilike(like)) | (Device.manufacturer.ilike(like)))
    stmt = apply_sort(
        stmt,
        params.sort_by,
        params.sort_dir,
        {"created_at": Device.created_at, "imei": Device.imei, "model": Device.model},
    )
    return paginate(db, stmt, params.page, params.page_size)


def active_mappings(db: Session, device_id):
    return list(
        db.scalars(
            select(DeviceSimMapping).where(DeviceSimMapping.device_id == device_id, DeviceSimMapping.is_active.is_(True))
        ).all()
    )
