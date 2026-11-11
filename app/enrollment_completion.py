"""Committed profile proofs and durable Auth-owned companion grant receipts."""

import time
from enum import StrEnum
from urllib.error import HTTPError, URLError

from sqlalchemy import and_, select, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from app import enrollment, oidc
from app.schema import (
    auth_enrollments,
    enrollment_completions,
    enrollment_grants,
    external_identities,
    users,
)

ISSUER = "https://auth.jackharrhy.dev"


class GrantState(StrEnum):
    RESERVED = "reserved"
    DONE = "done"


def grant_state(record) -> GrantState:
    return GrantState.DONE if record["outcome"] else GrantState.RESERVED


class DeliveryState(StrEnum):
    PENDING = "pending"
    RETRYABLE = "retryable"
    BLOCKED = "blocked"
    DELIVERED = "delivered"


def delivery_state(record) -> DeliveryState:
    if record["delivered_at"] is not None:
        return DeliveryState.DELIVERED
    if record["last_status"] == 409:
        return DeliveryState.BLOCKED
    return (
        DeliveryState.RETRYABLE
        if record["last_status"] is not None
        else DeliveryState.PENDING
    )


def retryable_deliveries():
    return and_(
        enrollment_completions.c.delivered_at.is_(None),
        enrollment_completions.c.last_status.is_distinct_from(409),
    )


def proof(conn, request_id):
    record = (
        conn.execute(
            select(auth_enrollments, users.c.is_disabled)
            .join(users, users.c.id == auth_enrollments.c.user_id)
            .join(external_identities, external_identities.c.user_id == users.c.id)
            .where(
                auth_enrollments.c.id == request_id,
                auth_enrollments.c.consumed_at.is_not(None),
                external_identities.c.issuer == ISSUER,
                external_identities.c.subject == auth_enrollments.c.subject,
            )
        )
        .mappings()
        .first()
    )
    if not record:
        raise ValueError("Enrollment has no committed identity")
    event = conn.execute(
        select(enrollment_completions.c.issuer).where(
            enrollment_completions.c.request_id == request_id
        )
    ).scalar_one_or_none()
    return {
        "requestId": request_id,
        "subject": record["subject"],
        "issuer": ISSUER,
        "userId": record["user_id"],
        "completed": True,
        "createdProfile": event == ISSUER,
        "enabled": not record["is_disabled"],
    }


def eligible(conn, request_id, subject, application_id):
    record = proof(conn, request_id)
    if (
        not record["createdProfile"]
        or not record["enabled"]
        or record["subject"] != subject
        or application_id not in {"maps", "burger"}
    ):
        raise ValueError("Enrollment is not eligible for this completion")


def receipt(conn, request_id, application_id, subject):
    row = (
        conn.execute(
            select(enrollment_grants).where(
                enrollment_grants.c.request_id == request_id,
                enrollment_grants.c.application_id == application_id,
            )
        )
        .mappings()
        .one()
    )
    return {
        "requestId": request_id,
        "subject": subject,
        "applicationId": application_id,
        "attemptId": row["attempt_id"],
        "state": grant_state(row),
    }


def reserve(conn, request_id, application_id, subject, attempt_id):
    eligible(conn, request_id, subject, application_id)
    conn.execute(
        sqlite_insert(enrollment_grants)
        .values(
            request_id=request_id,
            application_id=application_id,
            attempt_id=attempt_id,
        )
        .on_conflict_do_nothing(index_elements=["request_id", "application_id"])
    )
    return receipt(conn, request_id, application_id, subject)


def finish(conn, request_id, application_id, subject, attempt_id, grant_id, outcome):
    eligible(conn, request_id, subject, application_id)
    row = (
        conn.execute(
            select(enrollment_grants).where(
                enrollment_grants.c.request_id == request_id,
                enrollment_grants.c.application_id == application_id,
            )
        )
        .mappings()
        .first()
    )
    if not row or row["attempt_id"] != attempt_id:
        raise ValueError("Completion does not own the original reservation")
    if grant_state(row) == GrantState.DONE:
        if row["grant_id"] != grant_id or row["outcome"] != outcome:
            raise ValueError("Completion receipt is already terminal")
    else:
        conn.execute(
            update(enrollment_grants)
            .where(
                enrollment_grants.c.request_id == request_id,
                enrollment_grants.c.application_id == application_id,
                enrollment_grants.c.outcome.is_(None),
            )
            .values(grant_id=grant_id, outcome=outcome)
        )
        stored = (
            conn.execute(
                select(enrollment_grants).where(
                    enrollment_grants.c.request_id == request_id,
                    enrollment_grants.c.application_id == application_id,
                )
            )
            .mappings()
            .one()
        )
        if stored["grant_id"] != grant_id or stored["outcome"] != outcome:
            raise ValueError("Completion receipt is already terminal")
    return receipt(conn, request_id, application_id, subject)


def deliver(engine, request_id):
    """One bounded attempt; committed profile survives any broker failure."""
    with engine.begin() as conn:
        event = (
            conn.execute(
                select(enrollment_completions).where(
                    enrollment_completions.c.request_id == request_id,
                )
            )
            .mappings()
            .first()
        )
        if not event or delivery_state(event) in {
            DeliveryState.DELIVERED,
            DeliveryState.BLOCKED,
        }:
            return None
        record = proof(conn, request_id)
        if not record["enabled"]:
            return None
    try:
        response = oidc.provider_json(
            ISSUER + "/enroll/complete",
            json_body={"requestId": request_id, "subject": record["subject"]},
            headers={"Authorization": "Bearer " + enrollment.integration_key()},
        )
        status = (
            200 if response == {"requestId": request_id, "completed": True} else 502
        )
    except HTTPError as error:
        status = error.code
    except ValueError, OSError, URLError:
        status = 502
    with engine.begin() as conn:
        if status == 200:
            finished = set(
                conn.execute(
                    select(enrollment_grants.c.application_id).where(
                        enrollment_grants.c.request_id == request_id,
                        enrollment_grants.c.outcome.is_not(None),
                    )
                ).scalars()
            )
            if finished != {"maps", "burger"}:
                status = 502
        conn.execute(
            update(enrollment_completions)
            .where(
                enrollment_completions.c.request_id == request_id,
                enrollment_completions.c.delivered_at.is_(None),
            )
            .values(
                last_status=status,
                delivered_at=int(time.time()) if status == 200 else None,
            )
        )
    return status
