"""Request and response shapes. Pydantic rejects a bad payload before a service runs."""

import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Generic, TypeVar

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, field_validator

from app.domain.enums import (
    AddressType,
    Availability,
    BillingType,
    ContactType,
    CustomerType,
    DeviceType,
    EquipmentType,
    HealthStatus,
    KycStatus,
    NetworkLinkStatus,
    OutageStatus,
    OutageType,
    PlanCategory,
    Priority,
    Role,
    ServiceRequestType,
    Severity,
    SimStatus,
    SimType,
    Skill,
    TicketStatus,
    TicketType,
    TowerStatus,
    TowerType,
)

T = TypeVar("T")


def check_password(value: str) -> str:
    if len(value) < 8 or not any(char.isalpha() for char in value) or not any(char.isdigit() for char in value):
        raise ValueError("Password must be at least 8 characters and include a letter and a digit")
    if len(value.encode()) > 72:
        raise ValueError("Password must be at most 72 bytes")
    return value


def normalize_email(value: str) -> str:
    """Classroom and lab hostnames such as telecom.local are allowed.

    Pydantic's EmailAddress rejects the reserved .local suffix. A telecom lab still needs it.
    """
    value = value.strip().lower()
    if not re.fullmatch(r"[a-z0-9._%+\-]+@[a-z0-9.\-]+\.[a-z]{2,}", value):
        raise ValueError("Enter a valid email address")
    return value


EmailAddress = Annotated[str, AfterValidator(normalize_email)]


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    page_size: int


class Message(BaseModel):
    message: str
    reset_token: str | None = None


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RegisterRequest(BaseModel):
    email: EmailAddress
    full_name: str = Field(min_length=2, max_length=120)
    password: str
    phone: str | None = None

    @field_validator("password")
    @classmethod
    def _password(cls, value: str) -> str:
        return check_password(value)


class LoginRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"examples": [{"email": "admin@telecom.local", "password": "Admin@12345"}]})
    email: EmailAddress
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class ResetRequest(BaseModel):
    email: EmailAddress


class ResetConfirm(BaseModel):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def _password(cls, value: str) -> str:
        return check_password(value)


class StaffCreate(BaseModel):
    email: EmailAddress
    full_name: str = Field(min_length=2, max_length=120)
    password: str
    role: Role
    phone: str | None = None

    @field_validator("password")
    @classmethod
    def _password(cls, value: str) -> str:
        return check_password(value)


class UserRead(ORMModel):
    id: uuid.UUID
    email: EmailAddress
    full_name: str
    phone: str | None
    role: str
    is_active: bool
    is_verified: bool
    last_login_at: datetime | None
    created_at: datetime


class RegisterResponse(BaseModel):
    user: UserRead
    tokens: TokenPair


class ContactIn(BaseModel):
    contact_type: ContactType
    value: str = Field(min_length=3, max_length=255)
    is_primary: bool = False


class AddressIn(BaseModel):
    address_type: AddressType
    line1: str = Field(min_length=3, max_length=200)
    line2: str | None = None
    city: str = Field(min_length=2, max_length=80)
    state: str = Field(min_length=2, max_length=80)
    postal_code: str = Field(min_length=3, max_length=20)
    country: str = "India"
    is_primary: bool = False


class CustomerCreate(BaseModel):
    customer_type: CustomerType
    first_name: str | None = None
    last_name: str | None = None
    company_name: str | None = None
    date_of_birth: date | None = None
    contacts: list[ContactIn] = []
    addresses: list[AddressIn] = []
    create_login: bool = False
    email: EmailAddress | None = None
    password: str | None = None

    @field_validator("password")
    @classmethod
    def _password(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return check_password(value)


class CustomerUpdate(BaseModel):
    first_name: str | None = None
    last_name: str | None = None
    company_name: str | None = None
    date_of_birth: date | None = None


class KycUpdate(BaseModel):
    status: KycStatus
    note: str | None = Field(default=None, max_length=300)


class ContactRead(ORMModel):
    id: uuid.UUID
    contact_type: str
    value: str
    is_primary: bool


class AddressRead(ORMModel):
    id: uuid.UUID
    address_type: str
    line1: str
    line2: str | None
    city: str
    state: str
    postal_code: str
    country: str
    is_primary: bool


class CustomerRead(ORMModel):
    id: uuid.UUID
    customer_code: str
    user_id: uuid.UUID | None
    customer_type: str
    first_name: str | None
    last_name: str | None
    company_name: str | None
    date_of_birth: date | None
    kyc_status: str
    status: str
    created_at: datetime
    contacts: list[ContactRead] = []
    addresses: list[AddressRead] = []


class CustomerEventRead(ORMModel):
    id: uuid.UUID
    action: str
    note: str | None
    actor_id: uuid.UUID | None
    created_at: datetime


class PlanCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    description: str | None = None
    billing_type: BillingType
    category: PlanCategory
    price: Decimal = Field(ge=0)
    validity_days: int = Field(ge=1, le=3660)
    data_limit_mb: int = Field(default=0, ge=-1)
    voice_limit_minutes: int = Field(default=0, ge=-1)
    sms_limit: int = Field(default=0, ge=-1)


class PlanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = None
    price: Decimal | None = Field(default=None, ge=0)
    validity_days: int | None = Field(default=None, ge=1, le=3660)
    data_limit_mb: int | None = Field(default=None, ge=-1)
    voice_limit_minutes: int | None = Field(default=None, ge=-1)
    sms_limit: int | None = Field(default=None, ge=-1)


class PlanRead(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None
    billing_type: str
    category: str
    price: Decimal
    currency: str
    validity_days: int
    data_limit_mb: int
    voice_limit_minutes: int
    sms_limit: int
    status: str
    created_at: datetime


class PlanCompareRequest(BaseModel):
    plan_ids: list[uuid.UUID] = Field(min_length=2, max_length=4)


class PlanCompareResult(BaseModel):
    plans: list[PlanRead]
    differences: list[str]


class SimCreate(BaseModel):
    iccid: str
    msisdn: str
    sim_type: SimType


class SimRead(ORMModel):
    id: uuid.UUID
    iccid: str
    msisdn: str
    sim_type: str
    status: str
    customer_id: uuid.UUID | None
    activation_date: datetime | None
    created_at: datetime


class SimActivate(BaseModel):
    customer_id: uuid.UUID


class SimStatusChange(BaseModel):
    status: SimStatus
    reason: str | None = None


class SimReplace(BaseModel):
    new_sim_id: uuid.UUID
    reason: str = Field(min_length=3, max_length=300)


class NumberChange(BaseModel):
    new_msisdn: str


class SimReplacementRead(ORMModel):
    id: uuid.UUID
    old_sim_id: uuid.UUID
    new_sim_id: uuid.UUID
    reason: str
    replaced_at: datetime


class DeviceCreate(BaseModel):
    imei: str
    model: str = Field(min_length=1, max_length=80)
    manufacturer: str = Field(min_length=1, max_length=80)
    device_type: DeviceType
    customer_id: uuid.UUID | None = None


class DeviceRead(ORMModel):
    id: uuid.UUID
    imei: str
    model: str
    manufacturer: str
    device_type: str
    status: str
    customer_id: uuid.UUID | None
    created_at: datetime


class SimMapRequest(BaseModel):
    sim_id: uuid.UUID


class MappingRead(ORMModel):
    id: uuid.UUID
    device_id: uuid.UUID
    sim_id: uuid.UUID
    is_active: bool
    mapped_at: datetime


class SubscriptionCreate(BaseModel):
    customer_id: uuid.UUID
    sim_id: uuid.UUID
    plan_id: uuid.UUID
    start_date: datetime | None = None


class PlanBrief(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    price: Decimal
    billing_type: str


class SimBrief(ORMModel):
    id: uuid.UUID
    msisdn: str
    status: str


class SubscriptionRead(ORMModel):
    id: uuid.UUID
    code: str
    status: str
    start_date: datetime
    end_date: datetime
    cycle_start: datetime
    cycle_end: datetime
    customer_id: uuid.UUID
    sim_id: uuid.UUID
    plan_id: uuid.UUID
    plan: PlanBrief
    sim: SimBrief


class PlanChange(BaseModel):
    plan_id: uuid.UUID


class ReasonBody(BaseModel):
    reason: str | None = Field(default=None, max_length=300)


class SubscriptionEventRead(ORMModel):
    id: uuid.UUID
    event_type: str
    from_plan_id: uuid.UUID | None
    to_plan_id: uuid.UUID | None
    note: str | None
    actor_id: uuid.UUID | None
    created_at: datetime


class UsageCreate(BaseModel):
    sim_id: uuid.UUID
    usage_date: date
    data_mb: Decimal = Field(default=Decimal("0"), ge=0)
    voice_minutes: Decimal = Field(default=Decimal("0"), ge=0)
    sms_count: int = Field(default=0, ge=0)


class QuotaBucket(BaseModel):
    limit: int
    used: Decimal
    remaining: Decimal | None
    percent: Decimal | None
    unlimited: bool
    included: bool


class UtilizationRead(BaseModel):
    subscription_id: uuid.UUID
    plan_code: str
    cycle_start: datetime
    cycle_end: datetime
    data: QuotaBucket
    voice: QuotaBucket
    sms: QuotaBucket


class UsageWriteResult(UtilizationRead):
    over_limit: bool
    usage_date: date


class UsageDailyRead(ORMModel):
    id: uuid.UUID
    usage_date: date
    data_mb: Decimal
    voice_minutes: Decimal
    sms_count: int
    sim_id: uuid.UUID
    subscription_id: uuid.UUID


class UsageListRead(BaseModel):
    customer_id: uuid.UUID | None = None
    sim_id: uuid.UUID | None = None
    items: list[UsageDailyRead]
    totals: dict


class TowerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    tower_type: TowerType
    latitude: Decimal
    longitude: Decimal
    address: str
    city: str
    state: str
    coverage_radius_km: Decimal = Field(gt=0, le=100)
    capacity: int = Field(gt=0, le=100000)


class TowerUpdate(BaseModel):
    name: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    coverage_radius_km: Decimal | None = Field(default=None, gt=0, le=100)
    capacity: int | None = Field(default=None, gt=0, le=100000)


class TowerRead(ORMModel):
    id: uuid.UUID
    tower_code: str
    name: str
    tower_type: str
    latitude: Decimal
    longitude: Decimal
    address: str
    city: str
    state: str
    coverage_radius_km: Decimal
    capacity: int
    status: str
    created_at: datetime


class TowerLink(BaseModel):
    tower_id: uuid.UUID
    is_primary: bool = True


class TowerStatusBody(BaseModel):
    status: TowerStatus


class EquipmentCreate(BaseModel):
    tower_id: uuid.UUID
    equipment_type: EquipmentType
    serial_number: str = Field(min_length=3, max_length=64)
    model: str
    manufacturer: str
    health: HealthStatus = HealthStatus.UNKNOWN
    installation_date: date
    next_maintenance_date: date | None = None


class EquipmentRead(ORMModel):
    id: uuid.UUID
    tower_id: uuid.UUID
    equipment_type: str
    serial_number: str
    model: str
    manufacturer: str
    health: str
    installation_date: date
    next_maintenance_date: date | None
    cpu_usage: Decimal | None
    memory_usage: Decimal | None
    network_status: str
    last_heartbeat: datetime | None
    downtime_minutes: int


class Heartbeat(BaseModel):
    cpu_usage: Decimal = Field(ge=0, le=100)
    memory_usage: Decimal = Field(ge=0, le=100)
    network_status: NetworkLinkStatus
    health: HealthStatus | None = None


class OutageCreate(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    description: str | None = None
    outage_type: OutageType
    severity: Severity
    tower_ids: list[uuid.UUID] = Field(min_length=1)
    start_time: datetime
    expected_resolution: datetime


class TowerBrief(BaseModel):
    id: uuid.UUID
    tower_code: str
    name: str
    city: str
    status: str


class OutageRead(BaseModel):
    id: uuid.UUID
    code: str
    title: str
    description: str | None
    outage_type: str
    severity: str
    status: str
    start_time: datetime
    expected_resolution: datetime
    actual_resolution: datetime | None
    towers: list[TowerBrief]
    affected_customer_ids: list[uuid.UUID]


class OutageStatusBody(BaseModel):
    status: OutageStatus


class ResolveOutage(BaseModel):
    actual_resolution: datetime


class TechnicianCreate(BaseModel):
    email: EmailAddress
    full_name: str
    password: str
    phone: str | None = None
    service_city: str
    skills: list[Skill] = Field(min_length=1)
    latitude: float | None = None
    longitude: float | None = None

    @field_validator("password")
    @classmethod
    def _password(cls, value: str) -> str:
        return check_password(value)


class TechnicianRead(BaseModel):
    id: uuid.UUID
    employee_code: str
    full_name: str
    email: EmailAddress
    availability: str
    service_city: str
    latitude: float | None
    longitude: float | None
    skills: list[str]


class SkillUpdate(BaseModel):
    skills: list[Skill] = Field(min_length=1)


class AvailabilityUpdate(BaseModel):
    availability: Availability
    latitude: float | None = None
    longitude: float | None = None


class WorkloadRead(BaseModel):
    technician_id: uuid.UUID
    employee_code: str
    availability: str
    pending_jobs: int
    completed_jobs: int


class TicketCreate(BaseModel):
    customer_id: uuid.UUID | None = None
    ticket_type: TicketType
    subject: str = Field(min_length=3, max_length=160)
    description: str = Field(min_length=3)
    priority: Priority | None = None


class TicketRead(ORMModel):
    id: uuid.UUID
    code: str
    customer_id: uuid.UUID
    ticket_type: str
    subject: str
    description: str
    status: str
    priority: str
    assigned_agent_id: uuid.UUID | None
    assigned_technician_id: uuid.UUID | None
    escalation_level: int
    escalation_status: str
    resolution_notes: str | None
    sla_deadline: datetime | None
    sla_breached: bool
    resolved_at: datetime | None
    closed_at: datetime | None
    created_at: datetime


class AssignBody(BaseModel):
    agent_id: uuid.UUID | None = None
    technician_id: uuid.UUID | None = None


class NoteBody(BaseModel):
    note: str | None = Field(default=None, max_length=1000)


class ResolveBody(BaseModel):
    resolution_notes: str = Field(min_length=3)


class CommentCreate(BaseModel):
    body: str = Field(min_length=1)
    is_internal: bool = False


class CommentRead(ORMModel):
    id: uuid.UUID
    author_id: uuid.UUID
    body: str
    is_internal: bool
    created_at: datetime


class TicketEventRead(ORMModel):
    id: uuid.UUID
    from_status: str | None
    to_status: str | None
    note: str | None
    actor_id: uuid.UUID | None
    created_at: datetime


class SlaPolicyCreate(BaseModel):
    name: str
    ticket_type: TicketType | None = None
    priority: Priority | None = None
    customer_type: CustomerType | None = None
    resolution_minutes: int = Field(ge=5, le=43200)


class SlaPolicyRead(ORMModel):
    id: uuid.UUID
    name: str
    ticket_type: str | None
    priority: str | None
    customer_type: str | None
    resolution_minutes: int
    is_active: bool


class SlaWatch(BaseModel):
    breached: list[TicketRead]
    soon: list[TicketRead]


class ServiceRequestCreate(BaseModel):
    customer_id: uuid.UUID | None = None
    request_type: ServiceRequestType
    sim_id: uuid.UUID | None = None
    subscription_id: uuid.UUID | None = None
    device_id: uuid.UUID | None = None
    payload: dict = {}
    note: str | None = None


class ServiceRequestRead(ORMModel):
    id: uuid.UUID
    code: str
    customer_id: uuid.UUID
    request_type: str
    status: str
    sim_id: uuid.UUID | None
    subscription_id: uuid.UUID | None
    device_id: uuid.UUID | None
    payload: dict
    note: str | None
    created_at: datetime


class ServiceRequestEventRead(ORMModel):
    id: uuid.UUID
    from_status: str | None
    to_status: str
    note: str | None
    actor_id: uuid.UUID | None
    created_at: datetime


class NotificationRead(ORMModel):
    id: uuid.UUID
    event_type: str
    title: str
    message: str
    payload: dict | None
    read_at: datetime | None
    created_at: datetime


class AuditRead(ORMModel):
    id: uuid.UUID
    user_id: uuid.UUID | None
    action: str
    entity: str
    entity_id: str
    created_at: datetime
    previous_value: dict | None
    new_value: dict | None
    ip_address: str | None
