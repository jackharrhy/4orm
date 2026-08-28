"""Administrator-facing OAuth credential lifecycle routes."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.deps import get_engine, require_admin, templates
from app.oauth_client_admin import (
    OAuthClientAdminError,
    finish_rotation,
    generate_secret,
    revoke_tokens,
    rotate_secret,
    toggle_client,
)

router = APIRouter(prefix="/admin/oauth/clients", tags=["admin"])


def _run(request: Request, operation, client_id: str):
    me = require_admin(request)
    try:
        with get_engine(request).begin() as conn:
            return operation(conn, client_id, me["id"])
    except OAuthClientAdminError as error:
        raise HTTPException(error.status_code, error.detail) from error


def _secret_response(request: Request, secret: str, client_id: str) -> HTMLResponse:
    response = templates.TemplateResponse(
        request,
        "fragments/oauth_client_secret.html",
        {"client_id": client_id, "client_secret": secret},
    )
    response.headers.update({"Cache-Control": "no-store", "Pragma": "no-cache"})
    return response


@router.post("/{client_id}/secret/generate")
def admin_generate_oauth_secret(request: Request, client_id: str):
    return _secret_response(
        request, _run(request, generate_secret, client_id), client_id
    )


@router.post("/{client_id}/secret/rotate")
def admin_rotate_oauth_secret(request: Request, client_id: str):
    return _secret_response(request, _run(request, rotate_secret, client_id), client_id)


@router.post("/{client_id}/secret/finish-rotation")
def admin_finish_oauth_secret_rotation(request: Request, client_id: str):
    _run(request, finish_rotation, client_id)
    return RedirectResponse("/admin#oauth-clients", status_code=303)


@router.post("/{client_id}/revoke-tokens")
def admin_revoke_oauth_tokens(request: Request, client_id: str):
    _run(request, revoke_tokens, client_id)
    return RedirectResponse("/admin#oauth-clients", status_code=303)


@router.post("/{client_id}/toggle-enabled")
def admin_toggle_oauth_client(request: Request, client_id: str):
    _run(request, toggle_client, client_id)
    return RedirectResponse("/admin#oauth-clients", status_code=303)
