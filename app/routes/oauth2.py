"""OAuth2 authorization endpoints."""

from __future__ import annotations

import base64
import json
import os
import warnings
from collections.abc import Iterable
from urllib.parse import urlparse, urlunparse

from authlib.common.urls import add_params_to_uri
from authlib.oauth2 import OAuth2Request as AuthlibOAuth2Request
from authlib.oauth2.rfc6749.errors import InvalidRequestError, OAuth2Error
from authlib.oauth2.rfc6749.requests import BasicOAuth2Payload
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import insert

from app.auth import get_access_token_context
from app.deps import SITE_URL, current_user, get_engine, templates
from app.oauth2 import create_authorization_server
from app.oauth_policy import ARTBIN_MCP_RESOURCE, OAUTH_SCOPE_NAMES
from app.oauth_registration import OAuthRegistrationError, register_dynamic_client
from app.schema import oauth2_audit_events


def _configure_authlib_transport(site_url: str) -> None:
    """Allow HTTP OAuth only for local development URLs."""
    parsed = urlparse(site_url)
    if parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}:
        os.environ.setdefault("AUTHLIB_INSECURE_TRANSPORT", "1")


_configure_authlib_transport(SITE_URL)

router = APIRouter()

# ---------------------------------------------------------------------------
# Lazy server singleton - created once per engine
# ---------------------------------------------------------------------------

_server_cache: dict[int, object] = {}


def _get_server(request: Request):
    engine = get_engine(request)
    eid = id(engine)
    if eid not in _server_cache:
        _server_cache[eid] = create_authorization_server(engine)
    return _server_cache[eid]


# ---------------------------------------------------------------------------
# GET /oauth/authorize - consent page
# ---------------------------------------------------------------------------


@router.get("/oauth/authorize")
def authorize_get(request: Request):
    duplicate_error = _reject_duplicate_parameters(request.query_params.multi_items())
    if duplicate_error:
        return duplicate_error
    params = dict(request.query_params)
    try:
        _grant, oauth2_request, _redirect_uri = _validated_authorization_request(
            request, params
        )
    except OAuth2Error as error:
        return _authorization_error_response(error, params.get("state", ""))

    me = current_user(request)
    if not me:
        # Stash the per-request OAuth params in the session, keep the URL short
        client_id = params.get("client_id", "")
        request.session["oauth_params"] = params
        return RedirectResponse(
            url=f"/login?next=oauth&client_id={client_id}", status_code=303
        )

    return templates.TemplateResponse(
        request,
        "oauth2_consent.html",
        {
            "me": me,
            "client_name": oauth2_request.client._row["client_name"],
            "response_type": params.get("response_type", ""),
            "client_id": oauth2_request.client.get_client_id(),
            "redirect_uri": _redirect_uri,
            "scope": oauth2_request.scope or "",
            "state": params.get("state", ""),
            "code_challenge": params.get("code_challenge", ""),
            "code_challenge_method": params.get("code_challenge_method", ""),
            "nonce": params.get("nonce", ""),
            "resource": getattr(oauth2_request, "resource", ""),
        },
    )


# ---------------------------------------------------------------------------
# POST /oauth/authorize - process consent
# ---------------------------------------------------------------------------


@router.post("/oauth/authorize")
async def authorize_post(request: Request):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()
    duplicate_error = _reject_duplicate_parameters(form.multi_items())
    if duplicate_error:
        return duplicate_error
    confirm = form.get("confirm", "no")
    state = form.get("state", "")
    form_data = {
        "response_type": form.get("response_type", ""),
        "client_id": form.get("client_id", ""),
        "redirect_uri": form.get("redirect_uri", ""),
        "scope": form.get("scope", ""),
        "state": state,
        "code_challenge": form.get("code_challenge", ""),
        "code_challenge_method": form.get("code_challenge_method", ""),
        "resource": form.get("resource", ""),
    }
    nonce = form.get("nonce")
    if nonce:
        form_data["nonce"] = nonce

    try:
        grant, oauth2_req, redirect_uri = _validated_authorization_request(
            request, form_data
        )
        oauth2_req.user = dict(me)
    except OAuth2Error as error:
        return _authorization_error_response(error, state)

    if confirm != "yes":
        params = [("error", "access_denied")]
        if state:
            params.append(("state", state))
        return RedirectResponse(
            url=add_params_to_uri(redirect_uri, params), status_code=302
        )

    try:
        _status, _body, headers = grant.create_authorization_response(
            redirect_uri, grant_user=dict(me)
        )
    except OAuth2Error as error:
        return _authorization_error_response(error, state, redirect_uri)

    # Extract Location header from the grant response
    location = dict(headers).get("Location", redirect_uri)
    return RedirectResponse(url=location, status_code=302)


# ---------------------------------------------------------------------------
# POST /oauth/register - RFC 7591 public client registration
# ---------------------------------------------------------------------------


@router.post("/oauth/register")
async def dynamic_client_registration(request: Request):
    content_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if content_type != "application/json":
        return _registration_error_response(
            OAuthRegistrationError(
                "invalid_client_metadata", "Registration requires application/json."
            )
        )

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > 32_768:
                return _registration_error_response(
                    OAuthRegistrationError(
                        "invalid_client_metadata", "The registration body is too large."
                    )
                )
        except ValueError:
            return _registration_error_response(
                OAuthRegistrationError(
                    "invalid_client_metadata", "Content-Length must be an integer."
                )
            )

    body = await request.body()
    if len(body) > 32_768:
        return _registration_error_response(
            OAuthRegistrationError(
                "invalid_client_metadata", "The registration body is too large."
            )
        )
    try:
        metadata = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _registration_error_response(
            OAuthRegistrationError(
                "invalid_client_metadata", "The registration body is not valid JSON."
            )
        )

    try:
        with get_engine(request).begin() as conn:
            registration = register_dynamic_client(conn, metadata)
    except OAuthRegistrationError as error:
        return _registration_error_response(error)

    return JSONResponse(
        registration,
        status_code=201,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


# ---------------------------------------------------------------------------
# POST /oauth/token - exchange code for token
# ---------------------------------------------------------------------------


@router.post("/oauth/token")
async def token_endpoint(request: Request):
    form = await request.form()
    duplicate_error = _reject_duplicate_parameters(form.multi_items())
    if duplicate_error:
        return duplicate_error
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
        _audit_oauth_request(
            request,
            "token_request_failed",
            _request_client_id(request, form_data),
            False,
            error.error,
        )
        return JSONResponse(
            {"error": error.error, "error_description": error.description or ""},
            status_code=error.status_code or 400,
            headers=dict(error.get_headers()),
        )

    headers = dict(response_headers)
    headers.setdefault("Cache-Control", "no-store")
    headers.setdefault("Pragma", "no-cache")
    return JSONResponse(token, status_code=status, headers=headers)


@router.post("/oauth/introspect")
async def introspection_endpoint(request: Request):
    form = await request.form()
    duplicate_error = _reject_duplicate_parameters(form.multi_items())
    if duplicate_error:
        return duplicate_error
    form_data = dict(form)
    server = _get_server(request)
    oauth2_req = _make_authlib_request(
        "POST", str(request.url), form_data, dict(request.headers)
    )
    status, body, response_headers = server.create_endpoint_response(
        "introspection", oauth2_req
    )
    if status >= 400:
        _audit_oauth_request(
            request,
            "introspection_failed",
            _request_client_id(request, form_data),
            False,
            body.get("error", "invalid_request"),
        )
        return JSONResponse(body, status_code=status, headers=dict(response_headers))

    _audit_oauth_request(
        request,
        "token_introspected",
        oauth2_req.client.get_client_id(),
        True,
        "active" if body.get("active") else "inactive",
    )
    return JSONResponse(body, status_code=status, headers=dict(response_headers))


# ---------------------------------------------------------------------------
# GET /oauth/userinfo - protected resource
# ---------------------------------------------------------------------------


@router.get("/oauth/userinfo")
def userinfo(request: Request):
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return _bearer_error("", 401)

    access_token = auth_header[7:]  # strip "Bearer "

    engine = get_engine(request)
    with engine.begin() as conn:
        context = get_access_token_context(conn, access_token)
        if not context:
            return _bearer_error("invalid_token", 401)
        token_row, user_row = context
        if "openid" not in token_row["scope"].split():
            return _bearer_error("insufficient_scope", 403, "openid")

    return JSONResponse(
        {
            "sub": str(user_row["id"]),
            "username": user_row["username"],
            "display_name": user_row["display_name"],
            "is_admin": bool(user_row["is_admin"]),
        }
    )


# ---------------------------------------------------------------------------
# Authorization server metadata (RFC 8414)
# ---------------------------------------------------------------------------


@router.get("/.well-known/oauth-authorization-server")
@router.get("/.well-known/openid-configuration")
def authorization_server_metadata():
    return JSONResponse(
        {
            "issuer": SITE_URL,
            "authorization_endpoint": f"{SITE_URL}/oauth/authorize",
            "token_endpoint": f"{SITE_URL}/oauth/token",
            "registration_endpoint": f"{SITE_URL}/oauth/register",
            "introspection_endpoint": f"{SITE_URL}/oauth/introspect",
            "userinfo_endpoint": f"{SITE_URL}/oauth/userinfo",
            "response_types_supported": ["code"],
            "grant_types_supported": [
                "authorization_code",
                "refresh_token",
                "client_credentials",
            ],
            "scopes_supported": list(OAUTH_SCOPE_NAMES),
            "protected_resources": [ARTBIN_MCP_RESOURCE],
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
    uri = _public_oauth_uri(uri)
    headers = dict(headers or {})
    if "authorization" in headers and "Authorization" not in headers:
        headers["Authorization"] = headers["authorization"]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        req = AuthlibOAuth2Request(method, uri, body=form_data, headers=headers)
    req.payload = BasicOAuth2Payload(form_data)
    return req


def _validated_authorization_request(request: Request, form_data: dict):
    """Build and fully validate one authorization request through Authlib."""
    server = _get_server(request)
    oauth2_request = _make_authlib_request("GET", str(request.url), form_data)
    grant = server.get_authorization_grant(oauth2_request)
    redirect_uri = grant.validate_authorization_request()
    code_challenge = form_data.get("code_challenge")
    if not code_challenge:
        raise InvalidRequestError(
            "Missing 'code_challenge'",
            state=form_data.get("state"),
            redirect_uri=redirect_uri,
        )
    if form_data.get("code_challenge_method") != "S256":
        raise InvalidRequestError(
            "Unsupported 'code_challenge_method'",
            state=form_data.get("state"),
            redirect_uri=redirect_uri,
        )
    return grant, oauth2_request, redirect_uri


def _authorization_error_response(
    error: OAuth2Error, state: str, redirect_uri: str | None = None
):
    """Return an OAuth error without ever redirecting to an unvalidated URI."""
    safe_redirect_uri = error.redirect_uri or redirect_uri
    params = list(error.get_body())
    if state and not any(name == "state" for name, _value in params):
        params.append(("state", state))
    if safe_redirect_uri:
        return RedirectResponse(
            url=add_params_to_uri(safe_redirect_uri, params), status_code=302
        )
    return JSONResponse(
        dict(params),
        status_code=error.status_code or 400,
        headers=dict(error.get_headers()),
    )


def _bearer_error(error: str, status_code: int, scope: str = "") -> JSONResponse:
    """Build an RFC 6750 bearer challenge and matching JSON error body."""
    challenge = 'Bearer realm="4orm"'
    body = {}
    if error:
        challenge += f', error="{error}"'
        body["error"] = error
    if scope:
        challenge += f', scope="{scope}"'
    return JSONResponse(
        body,
        status_code=status_code,
        headers={"WWW-Authenticate": challenge},
    )


def _registration_error_response(error: OAuthRegistrationError) -> JSONResponse:
    return JSONResponse(
        {"error": error.error, "error_description": error.description},
        status_code=400,
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


def _reject_duplicate_parameters(
    items: Iterable[tuple[str, object]],
) -> JSONResponse | None:
    """Reject repeated OAuth parameters before mapping conversion hides them."""
    seen = set()
    for name, _value in items:
        if name in seen:
            return JSONResponse(
                {
                    "error": "invalid_request",
                    "error_description": f"Duplicate '{name}' parameter.",
                },
                status_code=400,
            )
        seen.add(name)
    return None


def _public_oauth_uri(uri: str) -> str:
    public = urlparse(SITE_URL)
    internal = urlparse(uri)
    return urlunparse(
        internal._replace(
            scheme=public.scheme,
            netloc=public.netloc,
        )
    )


def _request_client_id(request: Request, form_data: dict) -> str:
    authorization = request.headers.get("authorization", "")
    if authorization.lower().startswith("basic "):
        try:
            decoded = base64.b64decode(authorization[6:], validate=True).decode()
            return decoded.split(":", 1)[0][:48]
        except (ValueError, UnicodeDecodeError):
            return ""
    return str(form_data.get("client_id", ""))[:48]


def _audit_oauth_request(
    request: Request,
    event_type: str,
    client_id: str,
    success: bool,
    detail: str,
) -> None:
    source_ip = request.client.host if request.client else ""
    with get_engine(request).begin() as conn:
        conn.execute(
            insert(oauth2_audit_events).values(
                event_type=event_type,
                client_id=client_id or None,
                success=success,
                detail=detail[:200],
                source_ip=source_ip[:64],
            )
        )
