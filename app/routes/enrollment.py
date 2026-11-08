"""Scoped machine endpoints for Jack Auth's member enrollment flow."""

import secrets
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app import enrollment, enrollment_completion
from app.deps import get_engine

router = APIRouter(tags=["auth"])


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$")
    username: str = Field(min_length=1, max_length=255)
    displayName: str = Field(min_length=1, max_length=200)


def service(request):
    try:
        expected = "Bearer " + enrollment.integration_key()
    except (ValueError, OSError):
        raise HTTPException(503, "Enrollment integration is unavailable") from None
    if not secrets.compare_digest(request.headers.get("authorization", ""), expected):
        raise HTTPException(401, "Enrollment service authentication required")


def state(record):
    return {
        "requestId": record["id"],
        "expiresAt": record["expires_at"],
        "subject": record["subject"],
        "completed": record["consumed_at"] is not None,
    }


@router.get("/internal/auth/enrollments/{request_id}")
def get_enrollment(request: Request, request_id: str):
    service(request)
    try:
        with get_engine(request).begin() as conn:
            return state(enrollment.get_pending(conn, request_id))
    except ValueError as error:
        raise HTTPException(410, str(error)) from None


@router.post("/internal/auth/enrollments/{request_id}/claim")
def claim_enrollment(request: Request, request_id: str, body: Claim):
    service(request)
    try:
        with get_engine(request).begin() as conn:
            return state(
                enrollment.claim(
                    conn, request_id, body.subject, body.username, body.displayName
                )
            )
    except ValueError as error:
        raise HTTPException(409, str(error)) from None


class Reservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$")
    attemptId: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class Completion(Reservation):
    grantId: str = Field(min_length=1, max_length=255, pattern=r"^[A-Za-z0-9_-]+$")
    outcome: Literal["created", "preserved"]


@router.get("/internal/auth/enrollments/{request_id}/completion")
def get_completion(request: Request, request_id: str):
    service(request)
    try:
        with get_engine(request).begin() as conn:
            return enrollment_completion.proof(conn, request_id)
    except ValueError as error:
        raise HTTPException(409, str(error)) from None


@router.post(
    "/internal/auth/enrollments/{request_id}/completion/{application_id}/reserve"
)
def reserve_completion(
    request: Request, request_id: str, application_id: str, body: Reservation
):
    service(request)
    try:
        with get_engine(request).begin() as conn:
            return enrollment_completion.reserve(
                conn, request_id, application_id, body.subject, body.attemptId
            )
    except ValueError as error:
        raise HTTPException(409, str(error)) from None


@router.post(
    "/internal/auth/enrollments/{request_id}/completion/{application_id}/finish"
)
def finish_completion(
    request: Request, request_id: str, application_id: str, body: Completion
):
    service(request)
    try:
        with get_engine(request).begin() as conn:
            return enrollment_completion.finish(
                conn,
                request_id,
                application_id,
                body.subject,
                body.attemptId,
                body.grantId,
                body.outcome,
            )
    except ValueError as error:
        raise HTTPException(409, str(error)) from None
