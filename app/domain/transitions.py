"""Allowed status changes.

If a change is not in the map, it is refused. Callers cannot invent a shortcut
by writing the column directly.
"""

from app.domain.enums import (
    CustomerStatus,
    DeviceStatus,
    KycStatus,
    OutageStatus,
    PlanStatus,
    ServiceRequestStatus,
    SimStatus,
    SubscriptionStatus,
    TicketStatus,
)
from app.domain.errors import AppError

SIM_TRANSITIONS: dict[str, set[str]] = {
    SimStatus.AVAILABLE: {SimStatus.ACTIVE},
    SimStatus.ACTIVE: {
        SimStatus.SUSPENDED,
        SimStatus.LOST,
        SimStatus.BLOCKED,
        SimStatus.DEACTIVATED,
    },
    SimStatus.SUSPENDED: {SimStatus.ACTIVE, SimStatus.DEACTIVATED},
    SimStatus.LOST: {SimStatus.BLOCKED, SimStatus.DEACTIVATED},
    SimStatus.BLOCKED: {SimStatus.DEACTIVATED},
    SimStatus.DEACTIVATED: set(),
}

TICKET_TRANSITIONS: dict[str, set[str]] = {
    TicketStatus.OPEN: {TicketStatus.ASSIGNED},
    TicketStatus.ASSIGNED: {TicketStatus.IN_PROGRESS, TicketStatus.WAITING_FOR_CUSTOMER},
    TicketStatus.IN_PROGRESS: {TicketStatus.WAITING_FOR_CUSTOMER, TicketStatus.RESOLVED},
    TicketStatus.WAITING_FOR_CUSTOMER: {TicketStatus.IN_PROGRESS},
    TicketStatus.RESOLVED: {TicketStatus.CLOSED},
    TicketStatus.CLOSED: set(),
}

SUBSCRIPTION_TRANSITIONS: dict[str, set[str]] = {
    SubscriptionStatus.PENDING: {SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELLED},
    SubscriptionStatus.ACTIVE: {
        SubscriptionStatus.SUSPENDED,
        SubscriptionStatus.CANCELLED,
        SubscriptionStatus.EXPIRED,
    },
    SubscriptionStatus.SUSPENDED: {SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELLED},
    SubscriptionStatus.CANCELLED: set(),
    SubscriptionStatus.EXPIRED: {SubscriptionStatus.ACTIVE},
}

PLAN_TRANSITIONS: dict[str, set[str]] = {
    PlanStatus.DRAFT: {PlanStatus.ACTIVE},
    PlanStatus.ACTIVE: {PlanStatus.INACTIVE},
    PlanStatus.INACTIVE: {PlanStatus.ACTIVE},
}

CUSTOMER_STATUS_TRANSITIONS: dict[str, set[str]] = {
    CustomerStatus.PENDING: {CustomerStatus.ACTIVE},
    CustomerStatus.ACTIVE: {CustomerStatus.INACTIVE},
    CustomerStatus.INACTIVE: {CustomerStatus.ACTIVE},
}

KYC_TRANSITIONS: dict[str, set[str]] = {
    KycStatus.PENDING: {KycStatus.SUBMITTED},
    KycStatus.SUBMITTED: {KycStatus.VERIFIED, KycStatus.REJECTED},
    KycStatus.REJECTED: {KycStatus.SUBMITTED},
    KycStatus.VERIFIED: {KycStatus.REJECTED},
}

OUTAGE_TRANSITIONS: dict[str, set[str]] = {
    OutageStatus.OPEN: {OutageStatus.INVESTIGATING, OutageStatus.RESOLVED},
    OutageStatus.INVESTIGATING: {OutageStatus.RESOLVED},
    OutageStatus.RESOLVED: set(),
}

SERVICE_REQUEST_TRANSITIONS: dict[str, set[str]] = {
    ServiceRequestStatus.SUBMITTED: {
        ServiceRequestStatus.UNDER_REVIEW,
        ServiceRequestStatus.REJECTED,
        ServiceRequestStatus.CANCELLED,
    },
    ServiceRequestStatus.UNDER_REVIEW: {
        ServiceRequestStatus.APPROVED,
        ServiceRequestStatus.REJECTED,
        ServiceRequestStatus.CANCELLED,
    },
    ServiceRequestStatus.APPROVED: {ServiceRequestStatus.IN_PROGRESS},
    ServiceRequestStatus.IN_PROGRESS: {ServiceRequestStatus.COMPLETED},
    ServiceRequestStatus.COMPLETED: set(),
    ServiceRequestStatus.REJECTED: set(),
    ServiceRequestStatus.CANCELLED: set(),
}

DEVICE_TRANSITIONS: dict[str, set[str]] = {
    DeviceStatus.IN_STOCK: {DeviceStatus.ACTIVE, DeviceStatus.RETIRED},
    DeviceStatus.ACTIVE: {DeviceStatus.INACTIVE, DeviceStatus.LOST, DeviceStatus.BLOCKED, DeviceStatus.RETIRED},
    DeviceStatus.INACTIVE: {DeviceStatus.ACTIVE, DeviceStatus.RETIRED},
    DeviceStatus.LOST: {DeviceStatus.BLOCKED, DeviceStatus.RETIRED},
    DeviceStatus.BLOCKED: {DeviceStatus.RETIRED},
    DeviceStatus.RETIRED: set(),
}

PRIORITY_LADDER = ["low", "medium", "high", "critical"]


def assert_transition(machine: dict[str, set[str]], current: str, new: str, label: str) -> None:
    current_key = _as_value(current)
    new_key = _as_value(new)
    allowed = {_as_value(item) for item in machine.get(current_key, set())}
    if new_key not in allowed:
        raise AppError(
            f"Cannot change {label} from '{current_key}' to '{new_key}'",
            409,
            "invalid_transition",
        )


def bump_priority(current: str) -> str:
    value = _as_value(current)
    index = PRIORITY_LADDER.index(value)
    if index == len(PRIORITY_LADDER) - 1:
        return value
    return PRIORITY_LADDER[index + 1]


def _as_value(item: str) -> str:
    return item.value if hasattr(item, "value") else str(item)
