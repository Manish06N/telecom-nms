"""Words the business uses. Stored in the database as plain strings."""

from enum import Enum


class Role(str, Enum):
    SUPER_ADMIN = "super_admin"
    OPERATIONS_MANAGER = "operations_manager"
    SUPPORT_AGENT = "support_agent"
    NETWORK_ENGINEER = "network_engineer"
    FIELD_TECHNICIAN = "field_technician"
    CUSTOMER = "customer"


class CustomerType(str, Enum):
    INDIVIDUAL = "individual"
    CORPORATE = "corporate"


class CustomerStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    INACTIVE = "inactive"


class KycStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    VERIFIED = "verified"
    REJECTED = "rejected"


class ContactType(str, Enum):
    MOBILE = "mobile"
    EMAIL = "email"
    ALTERNATE_MOBILE = "alternate_mobile"


class AddressType(str, Enum):
    SERVICE = "service"
    BILLING = "billing"
    KYC = "kyc"


class BillingType(str, Enum):
    PREPAID = "prepaid"
    POSTPAID = "postpaid"


class PlanCategory(str, Enum):
    DATA = "data"
    VOICE = "voice"
    SMS = "sms"
    COMBO = "combo"


class PlanStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    INACTIVE = "inactive"


class SimType(str, Enum):
    PHYSICAL = "physical"
    ESIM = "esim"


class SimStatus(str, Enum):
    AVAILABLE = "available"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    LOST = "lost"
    BLOCKED = "blocked"
    DEACTIVATED = "deactivated"


class DeviceType(str, Enum):
    HANDSET = "handset"
    ROUTER = "router"
    DONGLE = "dongle"
    IOT = "iot"
    CPE = "cpe"


class DeviceStatus(str, Enum):
    IN_STOCK = "in_stock"
    ACTIVE = "active"
    INACTIVE = "inactive"
    LOST = "lost"
    BLOCKED = "blocked"
    RETIRED = "retired"


class SubscriptionStatus(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class SubscriptionEventType(str, Enum):
    CREATED = "created"
    UPGRADED = "upgraded"
    DOWNGRADED = "downgraded"
    RENEWED = "renewed"
    SUSPENDED = "suspended"
    REACTIVATED = "reactivated"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    SIM_CHANGED = "sim_changed"


class TowerType(str, Enum):
    MACRO = "macro"
    MICRO = "micro"
    SMALL_CELL = "small_cell"
    ROOFTOP = "rooftop"


class TowerStatus(str, Enum):
    ACTIVE = "active"
    MAINTENANCE = "maintenance"
    OFFLINE = "offline"
    DECOMMISSIONED = "decommissioned"


class EquipmentType(str, Enum):
    ROUTER = "router"
    SWITCH = "switch"
    BASE_STATION = "base_station"
    NETWORK_DEVICE = "network_device"


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class NetworkLinkStatus(str, Enum):
    UP = "up"
    DOWN = "down"
    DEGRADED = "degraded"


class OutageType(str, Enum):
    POWER_FAILURE = "power_failure"
    FIBER_CUT = "fiber_cut"
    EQUIPMENT_FAILURE = "equipment_failure"
    PLANNED_MAINTENANCE = "planned_maintenance"
    CONGESTION = "congestion"


class OutageStatus(str, Enum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    RESOLVED = "resolved"


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Skill(str, Enum):
    NETWORK = "network"
    FIBER = "fiber"
    TOWER = "tower"
    SIM = "sim"
    DEVICE = "device"
    CUSTOMER_PREMISE = "customer_premise"


class Availability(str, Enum):
    AVAILABLE = "available"
    ON_JOB = "on_job"
    OFF_DUTY = "off_duty"
    LEAVE = "leave"


class TicketType(str, Enum):
    NETWORK_ISSUE = "network_issue"
    SIM_ISSUE = "sim_issue"
    DATA_ISSUE = "data_issue"
    VOICE_ISSUE = "voice_issue"
    DEVICE_ISSUE = "device_issue"
    ACCOUNT_ISSUE = "account_issue"
    SERVICE_REQUEST = "service_request"


class TicketStatus(str, Enum):
    OPEN = "open"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    WAITING_FOR_CUSTOMER = "waiting_for_customer"
    RESOLVED = "resolved"
    CLOSED = "closed"


class EscalationStatus(str, Enum):
    NONE = "none"
    ESCALATED = "escalated"
    BREACHED = "breached"


class ServiceRequestType(str, Enum):
    SIM_REPLACEMENT = "sim_replacement"
    NUMBER_CHANGE = "number_change"
    PLAN_CHANGE = "plan_change"
    DEVICE_REPLACEMENT = "device_replacement"
    SERVICE_ACTIVATION = "service_activation"
    SERVICE_SUSPENSION = "service_suspension"
    SERVICE_TERMINATION = "service_termination"


class ServiceRequestStatus(str, Enum):
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class NotificationEvent(str, Enum):
    TICKET_ASSIGNED = "ticket_assigned"
    SLA_BREACH = "sla_breach"
    NETWORK_OUTAGE = "network_outage"
    SERVICE_RESTORED = "service_restored"
    PLAN_EXPIRY = "plan_expiry"
    USAGE_THRESHOLD = "usage_threshold"
    SIM_SUSPENDED = "sim_suspended"
    MAINTENANCE_DUE = "maintenance_due"


class Permission(str, Enum):
    USER_MANAGE = "user:manage"
    CUSTOMER_READ = "customer:read"
    CUSTOMER_WRITE = "customer:write"
    PLAN_READ = "plan:read"
    PLAN_WRITE = "plan:write"
    SIM_READ = "sim:read"
    SIM_WRITE = "sim:write"
    DEVICE_READ = "device:read"
    DEVICE_WRITE = "device:write"
    SUBSCRIPTION_READ = "subscription:read"
    SUBSCRIPTION_WRITE = "subscription:write"
    USAGE_READ = "usage:read"
    USAGE_WRITE = "usage:write"
    TOWER_READ = "tower:read"
    TOWER_WRITE = "tower:write"
    OUTAGE_READ = "outage:read"
    OUTAGE_WRITE = "outage:write"
    TICKET_READ = "ticket:read"
    TICKET_WRITE = "ticket:write"
    TICKET_ASSIGN = "ticket:assign"
    SLA_READ = "sla:read"
    SLA_WRITE = "sla:write"
    TECHNICIAN_READ = "technician:read"
    TECHNICIAN_WRITE = "technician:write"
    SERVICE_REQUEST_WRITE = "service_request:write"
    SERVICE_REQUEST_PROCESS = "service_request:process"
    DASHBOARD_READ = "dashboard:read"
    REPORT_READ = "report:read"
    AUDIT_READ = "audit:read"
    NOTIFICATION_READ = "notification:read"
    SCHEDULE_RUN = "schedule:run"
