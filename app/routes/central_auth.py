"""Sign in through Jack Auth while preserving existing 4orm user IDs."""

import time
from urllib.error import URLError

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from joserfc.errors import JoseError
from sqlalchemy import select

from app import oidc
from app.deps import get_engine
from app.routes.auth import _pop_oauth_redirect
from app.schema import external_identities, users

router = APIRouter(tags=["auth"])


@router.get("/auth/start")
def start(request: Request):
    if not oidc.enabled():
        raise HTTPException(404)
    return RedirectResponse(
        oidc.begin(request.session, request.query_params.get("next")), 303
    )


@router.get("/auth/callback")
def callback(request: Request):
    if not oidc.enabled():
        raise HTTPException(404)
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
    with get_engine(request).begin() as conn:
        user = (
            conn.execute(
                select(users)
                .join(external_identities, external_identities.c.user_id == users.c.id)
                .where(
                    external_identities.c.issuer == claims["iss"],
                    external_identities.c.subject == claims["sub"],
                )
            )
            .mappings()
            .first()
        )
    if not user or user["is_disabled"]:
        raise HTTPException(
            403, "This identity is not linked to an active 4orm account."
        )
    redirect = _pop_oauth_redirect(request) if next_kind == "oauth" else None
    request.session.clear()
    request.session.update(
        user_id=user["id"],
        oidc_issuer=claims["iss"],
        oidc_expires_at=min(claims["exp"], int(time.time()) + 3600),
    )
    return RedirectResponse(redirect or f"/u/{user['username']}", 303)
