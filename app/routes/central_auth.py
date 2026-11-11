"""Sign in through Jack Auth while preserving existing 4orm user IDs."""

import time
from urllib.error import URLError
from urllib.parse import urlencode

from fastapi import APIRouter, BackgroundTasks, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from joserfc.errors import JoseError
from sqlalchemy import select

from app import enrollment, enrollment_completion, oidc
from app.deps import get_engine, templates
from app.queries.users import AccountState, account_state
from app.schema import external_identities, users

router = APIRouter(tags=["auth"])


@router.post("/auth/register")
def register(request: Request, invite_code: str = Form(...)):
    issuer, _, _ = oidc.configuration()
    try:
        enrollment.integration_key()
        with get_engine(request).begin() as conn:
            row = enrollment.reserve(
                conn, invite_code.strip(), request.session.get("central_enrollment")
            )
            signed = enrollment.ticket(row)
    except ValueError as error:
        return templates.TemplateResponse(
            request,
            "register_central.html",
            {"invite": invite_code, "error": str(error)},
            status_code=400,
        )
    request.session["central_enrollment"] = row["id"]
    return RedirectResponse(issuer + "/enroll?" + urlencode({"ticket": signed}), 303)


@router.get("/auth/start")
def start(request: Request):
    try:
        destination = oidc.begin(request.session, request.query_params.get("next"))
    except (ValueError, OSError, URLError):
        raise HTTPException(503, "Central sign-in is unavailable") from None
    return RedirectResponse(destination, 303)


@router.get("/auth/callback")
def callback(request: Request, background_tasks: BackgroundTasks):
    try:
        claims, next_kind = oidc.complete(
            request.session,
            request.query_params.get("state"),
            request.query_params.get("code"),
        )
    except (ValueError, KeyError, JoseError, URLError):
        raise HTTPException(
            400, "Sign-in failed. Start again from the login page."
        ) from None
    completed_request = None
    with get_engine(request).begin() as conn:
        if next_kind == "register" and request.session.get("central_enrollment"):
            try:
                user = enrollment.finish(
                    conn,
                    request.session["central_enrollment"],
                    claims["iss"],
                    claims["sub"],
                )
                completed_request = request.session["central_enrollment"]
            except ValueError as error:
                raise HTTPException(403, str(error)) from None
        else:
            user = (
                conn.execute(
                    select(users)
                    .join(
                        external_identities, external_identities.c.user_id == users.c.id
                    )
                    .where(
                        external_identities.c.issuer == claims["iss"],
                        external_identities.c.subject == claims["sub"],
                    )
                )
                .mappings()
                .first()
            )
    if not user or account_state(user) == AccountState.DISABLED:
        raise HTTPException(
            403, "This identity is not linked to an active 4orm account."
        )
    if completed_request:
        background_tasks.add_task(
            enrollment_completion.deliver, get_engine(request), completed_request
        )
    redirect = None
    request.session.clear()
    request.session.update(
        user_id=user["id"],
        oidc_issuer=claims["iss"],
        oidc_expires_at=min(claims["exp"], int(time.time()) + 3600),
    )
    if next_kind == "register" and account_state(user) == AccountState.AWAITING_TRUST:
        redirect = "/trust-agreement"
    return RedirectResponse(redirect or f"/u/{user['username']}", 303)
