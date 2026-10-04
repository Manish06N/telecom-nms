from datetime import datetime, timedelta

from app.domain.enums import SimStatus, TicketStatus
from app.domain.quotas import authorize_usage, remaining_quota, usage_percent
from app.domain.skills import skill_covers
from app.domain.sla import PolicyView, choose_policy
from app.domain.transitions import SIM_TRANSITIONS, TICKET_TRANSITIONS, assert_transition
from app.domain.uptime import downtime_minutes, uptime_percent
from app.domain.validators import luhn_valid, normalize_msisdn, validate_imei
from app.domain.errors import AppError
import pytest
from decimal import Decimal


def test_luhn_and_imei():
    assert luhn_valid("490154203237518")
    assert validate_imei("490154203237518") == "490154203237518"
    with pytest.raises(AppError):
        validate_imei("490154203237519")


def test_indian_mobile_is_normalized():
    assert normalize_msisdn("9876543210") == "+919876543210"


def test_sim_cannot_skip_states():
    with pytest.raises(AppError) as caught:
        assert_transition(SIM_TRANSITIONS, SimStatus.AVAILABLE, SimStatus.SUSPENDED, "SIM")
    assert caught.value.code == "invalid_transition"


def test_ticket_must_be_in_progress_before_resolve():
    with pytest.raises(AppError):
        assert_transition(TICKET_TRANSITIONS, TicketStatus.OPEN, TicketStatus.RESOLVED, "ticket")


def test_prepaid_stops_and_postpaid_continues():
    with pytest.raises(AppError) as caught:
        authorize_usage(limit=100, already_used=Decimal("90"), requested=Decimal("20"), billing_type="prepaid", unit="data")
    assert caught.value.code == "quota_exceeded"
    assert authorize_usage(limit=100, already_used=Decimal("90"), requested=Decimal("20"), billing_type="postpaid", unit="data") == "over_limit"
    assert usage_percent(100, Decimal("50")) == Decimal("50.00")
    assert remaining_quota(100, Decimal("30")) == Decimal("70")
    assert remaining_quota(-1, Decimal("30")) is None


def test_most_specific_sla_wins():
    policies = [
        PolicyView(None, "critical", None, 60, "generic"),
        PolicyView("network_issue", "critical", None, 45, "network"),
        PolicyView(None, "critical", "corporate", 30, "corporate"),
    ]
    chosen = choose_policy(policies, "network_issue", "critical", "corporate")
    assert chosen.name == "network"
    corporate_voice = choose_policy(policies, "voice_issue", "critical", "corporate")
    assert corporate_voice.name == "corporate"


def test_overlapping_outages_are_not_double_counted():
    start = datetime(2026, 9, 1, 0, 0)
    end = datetime(2026, 9, 1, 2, 0)
    windows = [
        (datetime(2026, 9, 1, 0, 0), datetime(2026, 9, 1, 1, 0)),
        (datetime(2026, 9, 1, 0, 30), datetime(2026, 9, 1, 1, 30)),
    ]
    assert downtime_minutes(windows, start, end) == 90
    assert uptime_percent(30, start, start + timedelta(hours=1)) == 50.0


def test_skill_match():
    assert skill_covers("sim_issue", {"sim"})
    assert not skill_covers("sim_issue", {"fiber"})
