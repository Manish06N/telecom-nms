"""Which role may attempt which action.

Row-level rules (a customer sees only their own record) live in services.
A role grant is not ownership.
"""

from app.domain.enums import Permission, Role

_ALL = set(Permission)

_OPS = {
    Permission.CUSTOMER_READ,
    Permission.CUSTOMER_WRITE,
    Permission.PLAN_READ,
    Permission.PLAN_WRITE,
    Permission.SIM_READ,
    Permission.SIM_WRITE,
    Permission.DEVICE_READ,
    Permission.DEVICE_WRITE,
    Permission.SUBSCRIPTION_READ,
    Permission.SUBSCRIPTION_WRITE,
    Permission.USAGE_READ,
    Permission.USAGE_WRITE,
    Permission.TOWER_READ,
    Permission.TOWER_WRITE,
    Permission.OUTAGE_READ,
    Permission.OUTAGE_WRITE,
    Permission.TICKET_READ,
    Permission.TICKET_WRITE,
    Permission.TICKET_ASSIGN,
    Permission.SLA_READ,
    Permission.SLA_WRITE,
    Permission.TECHNICIAN_READ,
    Permission.TECHNICIAN_WRITE,
    Permission.SERVICE_REQUEST_WRITE,
    Permission.SERVICE_REQUEST_PROCESS,
    Permission.DASHBOARD_READ,
    Permission.REPORT_READ,
    Permission.AUDIT_READ,
    Permission.NOTIFICATION_READ,
    Permission.SCHEDULE_RUN,
}

_SUPPORT = {
    Permission.CUSTOMER_READ,
    Permission.CUSTOMER_WRITE,
    Permission.PLAN_READ,
    Permission.SIM_READ,
    Permission.DEVICE_READ,
    Permission.SUBSCRIPTION_READ,
    Permission.USAGE_READ,
    Permission.TICKET_READ,
    Permission.TICKET_WRITE,
    Permission.TICKET_ASSIGN,
    Permission.SLA_READ,
    Permission.TECHNICIAN_READ,
    Permission.SERVICE_REQUEST_WRITE,
    Permission.SERVICE_REQUEST_PROCESS,
    Permission.DASHBOARD_READ,
    Permission.NOTIFICATION_READ,
}

_ENGINEER = {
    Permission.SIM_READ,
    Permission.DEVICE_READ,
    Permission.SUBSCRIPTION_READ,
    Permission.USAGE_READ,
    Permission.TOWER_READ,
    Permission.TOWER_WRITE,
    Permission.OUTAGE_READ,
    Permission.OUTAGE_WRITE,
    Permission.DASHBOARD_READ,
    Permission.NOTIFICATION_READ,
    Permission.TECHNICIAN_READ,
}

_TECHNICIAN = {
    Permission.SIM_READ,
    Permission.DEVICE_READ,
    Permission.TOWER_READ,
    Permission.TICKET_READ,
    Permission.TICKET_WRITE,
    Permission.NOTIFICATION_READ,
}

_CUSTOMER = {
    Permission.PLAN_READ,
    Permission.CUSTOMER_READ,
    Permission.CUSTOMER_WRITE,
    Permission.SIM_READ,
    Permission.DEVICE_READ,
    Permission.SUBSCRIPTION_READ,
    Permission.USAGE_READ,
    Permission.OUTAGE_READ,
    Permission.TICKET_READ,
    Permission.TICKET_WRITE,
    Permission.SERVICE_REQUEST_WRITE,
    Permission.NOTIFICATION_READ,
}

ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.SUPER_ADMIN: _ALL,
    Role.OPERATIONS_MANAGER: _OPS,
    Role.SUPPORT_AGENT: _SUPPORT,
    Role.NETWORK_ENGINEER: _ENGINEER,
    Role.FIELD_TECHNICIAN: _TECHNICIAN,
    Role.CUSTOMER: _CUSTOMER,
}


def permissions_for(role: Role | str) -> set[Permission]:
    return ROLE_PERMISSIONS[Role(role)]


def role_has(role: Role | str, permission: Permission) -> bool:
    return permission in permissions_for(role)
