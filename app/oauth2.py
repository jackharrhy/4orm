"""OAuth2 authorization server built on Authlib + SQLAlchemy Core."""

from __future__ import annotations

import secrets
import time
from datetime import UTC, datetime, timedelta

from authlib.oauth2 import AuthorizationServer
from authlib.oauth2.rfc6749 import grants, list_to_scope, scope_to_list
from authlib.oauth2.rfc7636 import CodeChallenge
from sqlalchemy import delete, insert, select

from app.schema import (
    oauth2_authorization_codes,
    oauth2_clients,
    oauth2_tokens,
    users,
)

# ---------------------------------------------------------------------------
# Wrapper classes – adapt SQLAlchemy Core row dicts to Authlib interfaces
# ---------------------------------------------------------------------------


class OAuth2ClientWrapper:
    """Wraps a SQLAlchemy row mapping to satisfy Authlib's client interface."""

    def __init__(self, row: dict):
        self._row = dict(row)

    @property
    def client_id(self):
        return self._row["client_id"]

    @property
    def client_secret(self):
        return self._row["client_secret"]

    def get_client_id(self):
        return self._row["client_id"]

    def get_default_redirect_uri(self):
        uris = self._row["redirect_uris"]
        if uris:
            return uris.split("\n")[0]
        return ""

    def get_allowed_scope(self, scope):
        if not scope:
            return ""
        allowed = set(scope_to_list(self._row["scope"]))
        return list_to_scope([s for s in scope.split() if s in allowed])

    def check_redirect_uri(self, redirect_uri):
        uris = self._row["redirect_uris"].split("\n")
        return redirect_uri in uris

    def check_client_secret(self, client_secret):
        return secrets.compare_digest(self._row["client_secret"], client_secret)

    def check_endpoint_auth_method(self, method, endpoint):
        if endpoint == "token":
            return self._row["token_endpoint_auth_method"] == method
        return True

    def check_response_type(self, response_type):
        return response_type in self._row["response_types"].split()

    def check_grant_type(self, grant_type):
        return grant_type in self._row["grant_types"].split()


class OAuth2AuthCodeWrapper:
    """Wraps a SQLAlchemy row mapping for the authorization code interface."""

    def __init__(self, row: dict):
        self._row = dict(row)

    def get_redirect_uri(self):
        return self._row["redirect_uri"]

    def get_scope(self):
        return self._row["scope"]

    @property
    def code_challenge(self):
        return self._row.get("code_challenge")

    @property
    def code_challenge_method(self):
        return self._row.get("code_challenge_method")

    @property
    def user_id(self):
        return self._row["user_id"]

    def is_expired(self):
        expires_at = self._row["expires_at"]
        if isinstance(expires_at, datetime):
            # SQLite may return naive datetimes; treat as UTC
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            return expires_at < datetime.now(UTC)
        return True


# ---------------------------------------------------------------------------
# Authorization Code Grant implementation
# ---------------------------------------------------------------------------

CODE_LIFETIME = timedelta(minutes=5)


class AuthorizationCodeGrant(grants.AuthorizationCodeGrant):
    TOKEN_ENDPOINT_AUTH_METHODS = ["client_secret_basic", "client_secret_post", "none"]

    def save_authorization_code(self, code, request):
        client = request.client
        payload = request.payload
        with self.server.engine.begin() as conn:
            conn.execute(
                insert(oauth2_authorization_codes).values(
                    code=code,
                    client_id=client.get_client_id(),
                    user_id=request.user["id"],
                    redirect_uri=payload.redirect_uri or "",
                    scope=request.scope or "",
                    nonce=payload.data.get("nonce"),
                    code_challenge=payload.data.get("code_challenge"),
                    code_challenge_method=payload.data.get("code_challenge_method"),
                    expires_at=datetime.now(UTC) + CODE_LIFETIME,
                )
            )

    def query_authorization_code(self, code, client):
        with self.server.engine.begin() as conn:
            row = (
                conn.execute(
                    select(oauth2_authorization_codes).where(
                        oauth2_authorization_codes.c.code == code,
                        oauth2_authorization_codes.c.client_id
                        == client.get_client_id(),
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        wrapped = OAuth2AuthCodeWrapper(row)
        if wrapped.is_expired():
            return None
        return wrapped

    def authenticate_user(self, authorization_code):
        with self.server.engine.begin() as conn:
            row = (
                conn.execute(
                    select(users).where(
                        users.c.id == authorization_code.user_id,
                    )
                )
                .mappings()
                .first()
            )
        return dict(row) if row else None

    def delete_authorization_code(self, authorization_code):
        with self.server.engine.begin() as conn:
            conn.execute(
                delete(oauth2_authorization_codes).where(
                    oauth2_authorization_codes.c.code == authorization_code._row["code"]
                )
            )


# ---------------------------------------------------------------------------
# Server subclass + factory
# ---------------------------------------------------------------------------


class OAuth2Server(AuthorizationServer):
    """Thin subclass that holds a reference to the SQLAlchemy engine."""

    def __init__(self, engine, **kwargs):
        super().__init__(**kwargs)
        self.engine = engine

    # These are required by the base class but unused in our server-side flow
    # (we call the grant methods directly, not via framework integration).

    def create_oauth2_request(self, request):
        raise NotImplementedError("Use framework-specific integration")

    def create_json_request(self, request):
        raise NotImplementedError("Use framework-specific integration")

    def handle_response(self, status, body, headers):
        raise NotImplementedError("Use framework-specific integration")

    def send_signal(self, name, *args, **kwargs):
        pass  # no-op; we don't use signals


def _generate_bearer_token(
    grant_type,
    client,
    user=None,
    scope=None,
    expires_in=None,
    include_refresh_token=False,
):
    token = {
        "token_type": "Bearer",
        "access_token": secrets.token_urlsafe(32),
        "scope": scope or "",
        "expires_in": expires_in or 3600,
    }
    if include_refresh_token:
        token["refresh_token"] = secrets.token_urlsafe(32)
    return token


def create_authorization_server(engine) -> OAuth2Server:
    """Factory: create and configure an OAuth2 authorization server."""
    server = OAuth2Server(engine)

    # --- query_client: look up by client_id ---
    def _query_client(client_id):
        with engine.begin() as conn:
            row = (
                conn.execute(
                    select(oauth2_clients).where(
                        oauth2_clients.c.client_id == client_id
                    )
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return OAuth2ClientWrapper(row)

    server.query_client = _query_client

    # --- save_token: persist issued tokens ---
    def _save_token(token, request):
        with engine.begin() as conn:
            conn.execute(
                insert(oauth2_tokens).values(
                    client_id=request.client.get_client_id(),
                    user_id=request.user["id"],
                    token_type=token["token_type"],
                    access_token=token["access_token"],
                    refresh_token=token.get("refresh_token"),
                    scope=token.get("scope", ""),
                    issued_at=int(time.time()),
                    expires_in=token.get("expires_in", 3600),
                )
            )

    server.save_token = _save_token

    # --- token generator ---
    server.register_token_generator("default", _generate_bearer_token)

    # --- register the authorization code grant with PKCE ---
    server.register_grant(AuthorizationCodeGrant, [CodeChallenge(required=True)])

    return server
