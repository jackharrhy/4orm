"""OAuth2 authorization endpoints."""

from __future__ import annotations

import os
import time
import warnings

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse

from authlib.common.urls import add_params_to_uri
from authlib.oauth2 import OAuth2Request as AuthlibOAuth2Request
from authlib.oauth2.rfc6749.errors import OAuth2Error
from authlib.oauth2.rfc6749.requests import BasicOAuth2Payload
from sqlalchemy import select

from app.deps import SITE_URL, current_user, get_engine, templates
from app.oauth2 import create_authorization_server
from app.schema import oauth2_tokens, users

# Allow http:// in development (Authlib rejects non-https by default)
os.environ.setdefault("AUTHLIB_INSECURE_TRANSPORT", "1")

router = APIRouter()

# ---------------------------------------------------------------------------
# Lazy server singleton – created once per engine
# ---------------------------------------------------------------------------

_server_cache: dict[int, object] = {}


def _get_server(request: Request):
    engine = get_engine(request)
    eid = id(engine)
    if eid not in _server_cache:
        _server_cache[eid] = create_authorization_server(engine)
    return _server_cache[eid]


# ---------------------------------------------------------------------------
# GET /oauth/authorize – consent page
# ---------------------------------------------------------------------------


@router.get("/oauth/authorize")
def authorize_get(request: Request):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)

    params = request.query_params
    client_id = params.get("client_id", "")

    server = _get_server(request)
    client = server.query_client(client_id)
    if not client:
        return JSONResponse({"error": "unknown client"}, status_code=400)

    redirect_uri = params.get("redirect_uri", "")
    if not client.check_redirect_uri(redirect_uri):
        return JSONResponse({"error": "invalid redirect_uri"}, status_code=400)

    return templates.TemplateResponse(
        request,
        "oauth2_consent.html",
        {
            "me": me,
            "client_name": client._row["client_name"],
            "response_type": params.get("response_type", ""),
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": params.get("scope", ""),
            "state": params.get("state", ""),
            "code_challenge": params.get("code_challenge", ""),
            "code_challenge_method": params.get("code_challenge_method", ""),
            "nonce": params.get("nonce", ""),
        },
    )


# ---------------------------------------------------------------------------
# POST /oauth/authorize – process consent
# ---------------------------------------------------------------------------


@router.post("/oauth/authorize")
async def authorize_post(request: Request):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()
    confirm = form.get("confirm", "no")
    redirect_uri = form.get("redirect_uri", "")
    state = form.get("state", "")

    if confirm != "yes":
        params = [("error", "access_denied")]
        if state:
            params.append(("state", state))
        uri = add_params_to_uri(redirect_uri, params)
        return RedirectResponse(url=uri, status_code=302)

    # Build the form data dict for Authlib
    form_data = {
        "response_type": form.get("response_type", ""),
        "client_id": form.get("client_id", ""),
        "redirect_uri": redirect_uri,
        "scope": form.get("scope", ""),
        "state": state,
        "code_challenge": form.get("code_challenge", ""),
        "code_challenge_method": form.get("code_challenge_method", ""),
    }
    nonce = form.get("nonce")
    if nonce:
        form_data["nonce"] = nonce

    server = _get_server(request)

    # Build an Authlib OAuth2Request for the authorization endpoint
    # Use the full request URL so Authlib can parse it
    oauth2_req = _make_authlib_request("GET", str(request.url), form_data)
    oauth2_req.user = dict(me)

    try:
        grant = server.get_authorization_grant(oauth2_req)
        redirect_uri_validated = grant.validate_authorization_request()
        status, body, headers = grant.create_authorization_response(
            redirect_uri_validated, grant_user=dict(me)
        )
    except OAuth2Error as error:
        params = [("error", error.error)]
        if error.description:
            params.append(("error_description", error.description))
        if state:
            params.append(("state", state))
        uri = add_params_to_uri(redirect_uri, params)
        return RedirectResponse(url=uri, status_code=302)

    # Extract Location header from the grant response
    location = dict(headers).get("Location", redirect_uri)
    return RedirectResponse(url=location, status_code=302)


# ---------------------------------------------------------------------------
# POST /oauth/token – exchange code for token
# ---------------------------------------------------------------------------


@router.post("/oauth/token")
async def token_endpoint(request: Request):
    form = await request.form()
    form_data = dict(form)

    server = _get_server(request)
    uri = str(request.url)
    headers = dict(request.headers)

    oauth2_req = _make_authlib_request("POST", uri, form_data, headers)

    try:
        grant = server.get_token_grant(oauth2_req)
        grant.validate_token_request()
        status, token, response_headers = grant.create_token_response()
    except OAuth2Error as error:
        return JSONResponse(
            {"error": error.error, "error_description": error.description or ""},
            status_code=error.status_code or 400,
        )

    return JSONResponse(token, status_code=status)


# ---------------------------------------------------------------------------
# GET /oauth/userinfo – protected resource
# ---------------------------------------------------------------------------


@router.get("/oauth/userinfo")
def userinfo(request: Request):
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return JSONResponse({"error": "missing or invalid token"}, status_code=401)

    access_token = auth_header[7:]  # strip "Bearer "

    engine = get_engine(request)
    with engine.begin() as conn:
        token_row = (
            conn.execute(
                select(oauth2_tokens).where(
                    oauth2_tokens.c.access_token == access_token,
                )
            )
            .mappings()
            .first()
        )

        if not token_row:
            return JSONResponse({"error": "invalid token"}, status_code=401)

        if token_row["revoked"]:
            return JSONResponse({"error": "token revoked"}, status_code=401)

        # Check expiry: issued_at + expires_in < now
        if token_row["issued_at"] + token_row["expires_in"] < int(time.time()):
            return JSONResponse({"error": "token expired"}, status_code=401)

        user_row = (
            conn.execute(
                select(users).where(users.c.id == token_row["user_id"])
            )
            .mappings()
            .first()
        )

        if not user_row:
            return JSONResponse({"error": "user not found"}, status_code=401)

    return JSONResponse(
        {
            "sub": str(user_row["id"]),
            "username": user_row["username"],
            "display_name": user_row["display_name"],
        }
    )


# ---------------------------------------------------------------------------
# GET /.well-known/openid-configuration
# ---------------------------------------------------------------------------


@router.get("/.well-known/openid-configuration")
def openid_configuration():
    return JSONResponse(
        {
            "issuer": SITE_URL,
            "authorization_endpoint": f"{SITE_URL}/oauth/authorize",
            "token_endpoint": f"{SITE_URL}/oauth/token",
            "userinfo_endpoint": f"{SITE_URL}/oauth/userinfo",
            "response_types_supported": ["code"],
            "grant_types_supported": ["authorization_code"],
            "subject_types_supported": ["public"],
            "id_token_signing_alg_values_supported": ["none"],
            "scopes_supported": ["openid", "profile"],
            "token_endpoint_auth_methods_supported": [
                "none",
                "client_secret_basic",
                "client_secret_post",
            ],
            "code_challenge_methods_supported": ["S256"],
        }
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_authlib_request(
    method: str, uri: str, form_data: dict, headers: dict | None = None
) -> AuthlibOAuth2Request:
    """Build an Authlib OAuth2Request with both payload and legacy body set."""
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        req = AuthlibOAuth2Request(method, uri, body=form_data, headers=headers)
    req.payload = BasicOAuth2Payload(form_data)
    return req
