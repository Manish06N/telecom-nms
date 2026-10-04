"""A technician can take a ticket only when one of their skills covers it."""

from app.domain.enums import Skill, TicketType

TICKET_SKILLS: dict[str, set[str]] = {
    TicketType.NETWORK_ISSUE: {Skill.NETWORK, Skill.FIBER, Skill.TOWER},
    TicketType.SIM_ISSUE: {Skill.SIM},
    TicketType.DATA_ISSUE: {Skill.NETWORK},
    TicketType.VOICE_ISSUE: {Skill.NETWORK},
    TicketType.DEVICE_ISSUE: {Skill.DEVICE},
    TicketType.ACCOUNT_ISSUE: {Skill.CUSTOMER_PREMISE},
    TicketType.SERVICE_REQUEST: {Skill.SIM, Skill.DEVICE, Skill.CUSTOMER_PREMISE},
}


def skill_covers(ticket_type: str, skills: set[str]) -> bool:
    needed = {_value(item) for item in TICKET_SKILLS.get(ticket_type, set())}
    owned = {_value(item) for item in skills}
    return bool(needed & owned)


def _value(item: str) -> str:
    return item.value if hasattr(item, "value") else str(item)
