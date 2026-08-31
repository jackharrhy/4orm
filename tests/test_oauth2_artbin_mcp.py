"""Artbin MCP dynamic registration and RFC 8707 audience tests."""

from __future__ import annotations

import time
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import insert, select

from app.oauth_policy import ARTBIN_ADMIN_SCOPE, ARTBIN_MCP_RESOURCE
from app.schema import (
    oauth2_authorization_codes,
    oauth2_clients,
    oauth2_tokens,
)
from app.security import hash_client_secret
from tests.conftest import login_as, make_admin_user, make_test_user
from tests.test_oauth2 import _create_pkce

LOOPBACK_REDIRECT = "http://127.0.0.1:43127/oauth/callback"


def _registration(**overrides):
    metadata = {
        "client_name": "MCP Test Client",
        "redirect_uris": [LOOPBACK_REDIRECT],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": ARTBIN_ADMIN_SCOPE,
    }
    metadata.update(overrides)
    return metadata


def _register(client, **overrides):
    response = client.post("/oauth/register", json=_registration(**overrides))
    assert response.status_code == 201, response.text
    return response.json()


def _seed_user_and_introspector(test_engine):
    with test_engine.begin() as conn:
        user_id = make_test_user(
            conn, "artbin-oauth-user", password="artbin-oauth-pass"
        )
        conn.execute(
            insert(oauth2_clients).values(
                client_id="artbin-server",
                client_secret_hash=hash_client_secret("introspection-secret"),
                client_name="Artbin server",
                client_kind="resource_server",
                subject="",
                redirect_uris="",
                scope="",
                grant_types="",
                response_types="",
                token_endpoint_auth_method="client_secret_basic",
            )
        )
    return user_id


def _authorize(client, client_id, resource=ARTBIN_MCP_RESOURCE):
    verifier, challenge = _create_pkce()
    data = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": LOOPBACK_REDIRECT,
        "scope": ARTBIN_ADMIN_SCOPE,
        "state": "artbin-state",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": resource,
    }
    consent = client.get("/oauth/authorize", params=data, follow_redirects=False)
    assert consent.status_code == 200, consent.text
    assert f'name="resource" value="{ARTBIN_MCP_RESOURCE}"' in consent.text
    assert ARTBIN_ADMIN_SCOPE in consent.text

    approved = client.post(
        "/oauth/authorize", data={**data, "confirm": "yes"}, follow_redirects=False
    )
    assert approved.status_code == 302, approved.text
    query = parse_qs(urlparse(approved.headers["location"]).query)
    return verifier, query["code"][0]


def _exchange(client, client_id, code, verifier, resource=ARTBIN_MCP_RESOURCE):
    return client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": LOOPBACK_REDIRECT,
            "code_verifier": verifier,
            "resource": resource,
        },
    )


def test_metadata_advertises_artbin_scope_resource_and_registration(client):
    metadata = client.get("/.well-known/oauth-authorization-server").json()

    assert metadata["registration_endpoint"].endswith("/oauth/register")
    assert ARTBIN_ADMIN_SCOPE in metadata["scopes_supported"]
    assert metadata["protected_resources"] == [ARTBIN_MCP_RESOURCE]
    assert metadata["code_challenge_methods_supported"] == ["S256"]


def test_dynamic_registration_creates_bounded_public_client(client, test_engine):
    response = client.post("/oauth/register", json=_registration())

    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["client_id"].startswith("artbin-mcp-")
    assert "client_secret" not in payload
    assert payload == {
        "client_id": payload["client_id"],
        **_registration(),
    }

    with test_engine.begin() as conn:
        row = (
            conn.execute(
                select(oauth2_clients).where(
                    oauth2_clients.c.client_id == payload["client_id"]
                )
            )
            .mappings()
            .one()
        )
    assert row["client_kind"] == "public"
    assert row["registration_source"] == "dynamic"
    assert row["client_secret_hash"] == ""
    assert row["scope"] == ARTBIN_ADMIN_SCOPE
    assert row["allowed_resources"] == ARTBIN_MCP_RESOURCE
    assert row["access_token_lifetime"] == 600


def test_dynamic_registration_downscopes_client_scope_metadata(client, test_engine):
    response = client.post(
        "/oauth/register",
        json=_registration(scope="openid profile artbin:admin unknown"),
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["scope"] == ARTBIN_ADMIN_SCOPE

    with test_engine.begin() as conn:
        registered_scope = conn.execute(
            select(oauth2_clients.c.scope).where(
                oauth2_clients.c.client_id == payload["client_id"]
            )
        ).scalar_one()
    assert registered_scope == ARTBIN_ADMIN_SCOPE


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "https://client.example/oauth/callback",
        "http://localhost:43127/oauth/callback",
        "http://127.0.0.1:43127/oauth/callback",
        "http://127.21.34.55:43127/oauth/callback",
        "http://[::1]:43127/oauth/callback",
    ],
)
def test_registration_accepts_https_and_http_loopback(client, redirect_uri):
    response = client.post(
        "/oauth/register", json=_registration(redirect_uris=[redirect_uri])
    )

    assert response.status_code == 201
    assert response.json()["redirect_uris"] == [redirect_uri]


@pytest.mark.parametrize(
    "redirect_uri",
    [
        "http://client.example/oauth/callback",
        "http://localhost.evil.example/oauth/callback",
        "https://user:password@client.example/oauth/callback",
        "https://client.example/oauth/callback#fragment",
        "custom-app://oauth/callback",
        "/relative/callback",
        "https://client.example:99999/oauth/callback",
        "https://client.example/oauth/%zz",
        "https://client.example\\@evil.example/oauth/callback",
        "https://client example/oauth/callback",
        "https://client.example/oauth/call back",
        "https://client.example/oauth/café",
    ],
)
def test_registration_rejects_unsafe_redirect_uris(client, redirect_uri):
    response = client.post(
        "/oauth/register", json=_registration(redirect_uris=[redirect_uri])
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_redirect_uri"


@pytest.mark.parametrize(
    ("override", "expected_error"),
    [
        (
            {"token_endpoint_auth_method": "client_secret_basic"},
            "invalid_client_metadata",
        ),
        ({"grant_types": ["client_credentials"]}, "invalid_client_metadata"),
        ({"response_types": ["token"]}, "invalid_client_metadata"),
        ({"scope": [ARTBIN_ADMIN_SCOPE]}, "invalid_client_metadata"),
    ],
)
def test_registration_rejects_unsupported_security_metadata(
    client, override, expected_error
):
    response = client.post("/oauth/register", json=_registration(**override))

    assert response.status_code == 400
    assert response.json()["error"] == expected_error


def test_artbin_authorization_persists_and_introspects_exact_audience(
    client, test_engine
):
    user_id = _seed_user_and_introspector(test_engine)
    registration = _register(client)
    client.post(
        "/login",
        data={"username": "artbin-oauth-user", "password": "artbin-oauth-pass"},
    )

    verifier, code = _authorize(client, registration["client_id"])
    with test_engine.begin() as conn:
        authorization_code = (
            conn.execute(
                select(oauth2_authorization_codes).where(
                    oauth2_authorization_codes.c.code == code
                )
            )
            .mappings()
            .one()
        )
    assert authorization_code["resource"] == ARTBIN_MCP_RESOURCE

    issued = _exchange(client, registration["client_id"], code, verifier)
    assert issued.status_code == 200, issued.text
    assert issued.json()["expires_in"] == 600

    with test_engine.begin() as conn:
        token_row = (
            conn.execute(
                select(oauth2_tokens).where(
                    oauth2_tokens.c.access_token == issued.json()["access_token"]
                )
            )
            .mappings()
            .one()
        )
    assert token_row["user_id"] == user_id
    assert token_row["audience"] == ARTBIN_MCP_RESOURCE
    assert token_row["scope"] == ARTBIN_ADMIN_SCOPE

    introspected = client.post(
        "/oauth/introspect",
        data={"token": issued.json()["access_token"]},
        auth=("artbin-server", "introspection-secret"),
    )
    assert introspected.status_code == 200
    assert introspected.json()["aud"] == ARTBIN_MCP_RESOURCE
    assert introspected.json()["client_id"] == registration["client_id"]
    assert introspected.json()["principal_type"] == "user"
    assert introspected.json()["sub"] == str(user_id)

    refreshed = client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": registration["client_id"],
            "refresh_token": issued.json()["refresh_token"],
        },
    )
    assert refreshed.status_code == 200, refreshed.text
    with test_engine.begin() as conn:
        refreshed_row = (
            conn.execute(
                select(oauth2_tokens).where(
                    oauth2_tokens.c.access_token == refreshed.json()["access_token"]
                )
            )
            .mappings()
            .one()
        )
    assert refreshed_row["audience"] == ARTBIN_MCP_RESOURCE

    reused = client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": registration["client_id"],
            "refresh_token": issued.json()["refresh_token"],
        },
    )
    assert reused.status_code == 400
    assert reused.json()["error"] == "invalid_grant"

    revoked_descendant = client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": registration["client_id"],
            "refresh_token": refreshed.json()["refresh_token"],
        },
    )
    assert revoked_descendant.status_code == 400
    assert revoked_descendant.json()["error"] == "invalid_grant"


def test_refresh_cannot_switch_audience_and_a_failed_attempt_is_not_consumed(
    client, test_engine
):
    _seed_user_and_introspector(test_engine)
    registration = _register(client)
    client.post(
        "/login",
        data={"username": "artbin-oauth-user", "password": "artbin-oauth-pass"},
    )
    verifier, code = _authorize(client, registration["client_id"])
    issued = _exchange(client, registration["client_id"], code, verifier)
    assert issued.status_code == 200

    switched = client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": registration["client_id"],
            "refresh_token": issued.json()["refresh_token"],
            "resource": "https://other.example/mcp",
        },
    )
    assert switched.status_code == 400
    assert switched.json()["error"] == "invalid_target"

    retained = client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": registration["client_id"],
            "refresh_token": issued.json()["refresh_token"],
            "resource": ARTBIN_MCP_RESOURCE,
        },
    )
    assert retained.status_code == 200
    with test_engine.begin() as conn:
        row = (
            conn.execute(
                select(oauth2_tokens).where(
                    oauth2_tokens.c.access_token == retained.json()["access_token"]
                )
            )
            .mappings()
            .one()
        )
    assert row["audience"] == ARTBIN_MCP_RESOURCE


def test_resource_is_required_and_revalidated_across_consent_and_token(client):
    _seed_user_and_introspector(client.app.state.engine)
    registration = _register(client)
    client.post(
        "/login",
        data={"username": "artbin-oauth-user", "password": "artbin-oauth-pass"},
    )
    _verifier, challenge = _create_pkce()
    base = {
        "response_type": "code",
        "client_id": registration["client_id"],
        "redirect_uri": LOOPBACK_REDIRECT,
        "scope": ARTBIN_ADMIN_SCOPE,
        "state": "resource-state",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }

    for resource in (None, "not-a-uri", "https://other.example/mcp"):
        params = dict(base)
        if resource is not None:
            params["resource"] = resource
        response = client.get("/oauth/authorize", params=params, follow_redirects=False)
        assert response.status_code == 302
        query = parse_qs(urlparse(response.headers["location"]).query)
        assert query["error"] == ["invalid_target"]
        assert "code" not in query

    tampered = client.post(
        "/oauth/authorize",
        data={
            **base,
            "resource": "https://other.example/mcp",
            "confirm": "yes",
        },
        follow_redirects=False,
    )
    assert tampered.status_code == 302
    assert parse_qs(urlparse(tampered.headers["location"]).query)["error"] == [
        "invalid_target"
    ]

    verifier, code = _authorize(client, registration["client_id"])
    missing = _exchange(client, registration["client_id"], code, verifier, resource="")
    assert missing.status_code == 400
    assert missing.json()["error"] == "invalid_target"

    verifier, code = _authorize(client, registration["client_id"])
    mismatched = _exchange(
        client,
        registration["client_id"],
        code,
        verifier,
        resource="https://other.example/mcp",
    )
    assert mismatched.status_code == 400
    assert mismatched.json()["error"] == "invalid_target"


def test_authorization_rejects_disallowed_scope_instead_of_reducing_it(client):
    _seed_user_and_introspector(client.app.state.engine)
    registration = _register(client)
    client.post(
        "/login",
        data={"username": "artbin-oauth-user", "password": "artbin-oauth-pass"},
    )
    _verifier, challenge = _create_pkce()

    response = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": registration["client_id"],
            "redirect_uri": LOOPBACK_REDIRECT,
            "scope": "artbin:admin openid",
            "state": "scope-state",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "resource": ARTBIN_MCP_RESOURCE,
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["error"] == ["invalid_scope"]
    assert "code" not in query


def test_public_registration_cannot_use_client_secret_authentication(
    client, test_engine
):
    _seed_user_and_introspector(test_engine)
    registration = _register(client)
    client.post(
        "/login",
        data={"username": "artbin-oauth-user", "password": "artbin-oauth-pass"},
    )
    verifier, code = _authorize(client, registration["client_id"])

    response = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": LOOPBACK_REDIRECT,
            "code_verifier": verifier,
            "resource": ARTBIN_MCP_RESOURCE,
        },
        auth=(registration["client_id"], "invented-secret"),
    )

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"


def test_other_audience_is_never_reported_as_artbin(test_engine, client):
    _seed_user_and_introspector(test_engine)
    with test_engine.begin() as conn:
        conn.execute(
            insert(oauth2_clients).values(
                client_id="other-client",
                client_name="Other client",
                token_endpoint_auth_method="none",
            )
        )
        conn.execute(
            insert(oauth2_tokens).values(
                client_id="other-client",
                user_id=1,
                principal_type="user",
                subject="1",
                grant_type="authorization_code",
                access_token="other-audience-token",
                scope=ARTBIN_ADMIN_SCOPE,
                audience="https://other.example/mcp",
                issued_at=2_000_000_000,
                expires_in=600,
            )
        )

    response = client.post(
        "/oauth/introspect",
        data={"token": "other-audience-token"},
        auth=("artbin-server", "introspection-secret"),
    )

    assert response.status_code == 200
    assert response.json()["aud"] == "https://other.example/mcp"
    assert response.json()["aud"] != ARTBIN_MCP_RESOURCE


def test_admin_can_inventory_revoke_and_disable_dynamic_client(client, test_engine):
    _seed_user_and_introspector(test_engine)
    registration = _register(client, client_name="Managed MCP client")
    with test_engine.begin() as conn:
        admin_id = make_admin_user(conn, "oauth-admin", password="admin-pass")
        conn.execute(
            insert(oauth2_tokens).values(
                client_id=registration["client_id"],
                user_id=admin_id,
                principal_type="user",
                subject=str(admin_id),
                grant_type="authorization_code",
                access_token="dynamic-token-to-revoke",
                scope=ARTBIN_ADMIN_SCOPE,
                audience=ARTBIN_MCP_RESOURCE,
                issued_at=int(time.time()),
                expires_in=600,
            )
        )
    login_as(client, "oauth-admin", password="admin-pass")

    dashboard = client.get("/admin")
    assert dashboard.status_code == 200
    assert 'href="/admin/oauth"' in dashboard.text

    inventory = client.get("/admin/oauth")
    assert inventory.status_code == 200
    assert "Managed MCP client" in inventory.text
    assert "dynamic registrations" in inventory.text
    assert ARTBIN_MCP_RESOURCE in inventory.text

    revoked = client.post(
        f"/admin/oauth/clients/{registration['client_id']}/revoke-tokens",
        follow_redirects=False,
    )
    assert revoked.status_code == 303
    assert revoked.headers["location"] == "/admin/oauth"
    introspected = client.post(
        "/oauth/introspect",
        data={"token": "dynamic-token-to-revoke"},
        auth=("artbin-server", "introspection-secret"),
    )
    assert introspected.json() == {"active": False}

    with test_engine.begin() as conn:
        conn.execute(
            insert(oauth2_tokens).values(
                client_id=registration["client_id"],
                user_id=admin_id,
                principal_type="user",
                subject=str(admin_id),
                grant_type="authorization_code",
                access_token="dynamic-token-to-disable",
                scope=ARTBIN_ADMIN_SCOPE,
                audience=ARTBIN_MCP_RESOURCE,
                issued_at=int(time.time()),
                expires_in=600,
            )
        )
    disabled = client.post(
        f"/admin/oauth/clients/{registration['client_id']}/toggle-enabled",
        follow_redirects=False,
    )
    assert disabled.status_code == 303
    introspected = client.post(
        "/oauth/introspect",
        data={"token": "dynamic-token-to-disable"},
        auth=("artbin-server", "introspection-secret"),
    )
    assert introspected.json() == {"active": False}
