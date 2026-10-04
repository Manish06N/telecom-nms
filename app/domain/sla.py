"""Pick the most specific SLA policy that still matches the ticket."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PolicyView:
    ticket_type: str | None
    priority: str | None
    customer_type: str | None
    resolution_minutes: int
    name: str = ""


def specificity(policy: PolicyView, ticket_type: str, priority: str, customer_type: str) -> int | None:
    """None means the policy does not apply. Higher score wins."""
    score = 0
    if policy.ticket_type:
        if policy.ticket_type != ticket_type:
            return None
        score += 4
    if policy.priority:
        if policy.priority != priority:
            return None
        score += 2
    if policy.customer_type:
        if policy.customer_type != customer_type:
            return None
        score += 1
    return score


def choose_policy(policies: list[PolicyView], ticket_type: str, priority: str, customer_type: str) -> PolicyView:
    ranked: list[tuple[int, int, PolicyView]] = []
    for policy in policies:
        score = specificity(policy, ticket_type, priority, customer_type)
        if score is None:
            continue
        ranked.append((score, -policy.resolution_minutes, policy))
    if not ranked:
        raise LookupError("No SLA policy matches this ticket")
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    return ranked[0][2]
