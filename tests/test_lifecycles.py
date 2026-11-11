from datetime import UTC, datetime

import pytest

from app import enrollment, enrollment_completion, oidc
from app.queries.users import InviteState, invite_state


@pytest.mark.parametrize(
    ("changes", "expected"),
    [
        ({}, "anonymous"),
        ({"user_id": 1}, "invalid"),
        (
            {"user_id": 1, "oidc_issuer": "issuer", "oidc_expires_at": float("nan")},
            "invalid",
        ),
        (
            {"user_id": 1, "oidc_issuer": "issuer", "oidc_expires_at": float("inf")},
            "invalid",
        ),
        ({"user_id": 1, "oidc_issuer": "issuer", "oidc_expires_at": 10}, "expired"),
        ({"user_id": 1, "oidc_issuer": "issuer", "oidc_expires_at": "bad"}, "invalid"),
        (
            {"user_id": 1, "oidc_issuer": "issuer", "oidc_expires_at": 11},
            "authenticated",
        ),
    ],
)
def test_session_states_fail_closed_at_expiration(changes, expected):
    assert oidc.session_state(changes, "issuer", now=10) == expected


def test_completed_enrollment_and_delivery_are_terminal_after_expiry_or_conflict():
    row = {"subject": None, "consumed_at": None, "expires_at": 20}
    assert enrollment.enrollment_state(row, now=10) == "reserved"
    assert enrollment.enrollment_state(row | {"subject": "linked"}, now=10) == "claimed"
    assert enrollment.enrollment_state(row, now=20) == "expired"
    assert enrollment.enrollment_state(row | {"consumed_at": 15}, now=30) == "completed"
    assert (
        enrollment_completion.delivery_state(
            {"last_status": None, "delivered_at": None}
        )
        == "pending"
    )
    assert (
        enrollment_completion.delivery_state({"last_status": 502, "delivered_at": None})
        == "retryable"
    )
    assert (
        enrollment_completion.delivery_state({"last_status": 409, "delivered_at": None})
        == "blocked"
    )
    assert (
        enrollment_completion.delivery_state({"last_status": 409, "delivered_at": 15})
        == "delivered"
    )


def test_invite_expiration_and_disable_override_remaining_capacity():
    row = {
        "disabled": False,
        "expires_at": datetime(2026, 1, 1),
        "uses_count": 0,
        "max_uses": 2,
    }
    now = datetime(2026, 1, 1, tzinfo=UTC)
    assert invite_state(row, now=now) == InviteState.EXPIRED
    assert invite_state(row | {"disabled": True}, now=now) == InviteState.DISABLED
