"""Adversarial OAuth protocol-boundary and refresh-token tests."""

import time
from urllib.parse import parse_qs, urlparse

from sqlalchemy import insert, update

from app.schema import oauth2_clients, oauth2_tokens
from tests.test_oauth2 import _create_pkce, _seed_client_and_user


def test_refresh_token_expires_after_inactivity(client, test_engine):
    """Refresh credentials cannot remain usable indefinitely."""
    user_id, client_id = _seed_client_and_user(test_engine)
    with test_engine.begin() as conn:
        conn.execute(
            update(oauth2_clients)
            .where(oauth2_clients.c.client_id == client_id)
            .values(grant_types="authorization_code refresh_token")
        )
        conn.execute(
            insert(oauth2_tokens).values(
                client_id=client_id,
                user_id=user_id,
                principal_type="user",
                subject=str(user_id),
                grant_type="authorization_code",
                access_token="expired-refresh-access",
                refresh_token="expired-refresh-token",
                refresh_family_id="expired-family",
                scope="openid profile",
                issued_at=int(time.time()) - (31 * 24 * 60 * 60),
                expires_in=3600,
            )
        )

    response = client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": "expired-refresh-token",
            "client_id": client_id,
        },
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


def test_authorize_rejects_disabled_client_before_login(client, test_engine):
    """Disabled clients cannot initiate or resume an authorization flow."""
    _seed_client_and_user(test_engine)
    with test_engine.begin() as conn:
        conn.execute(
            update(oauth2_clients)
            .where(oauth2_clients.c.client_id == "test-app")
            .values(is_enabled=False)
        )
    _verifier, challenge = _create_pkce()

    response = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "test-app",
            "redirect_uri": "http://localhost:3000/callback",
            "scope": "openid profile",
            "state": "s",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.headers.get("location") is None
    assert response.json()["error"] == "invalid_client"


def test_authorize_validates_request_before_showing_consent(client, test_engine):
    """Malformed protocol requests never reach the consent screen."""
    _seed_client_and_user(test_engine)
    client.post("/login", data={"username": "oauthuser", "password": "oauthpass"})

    unsupported_response = client.get(
        "/oauth/authorize",
        params={
            "response_type": "token",
            "client_id": "test-app",
            "redirect_uri": "http://localhost:3000/callback",
            "scope": "openid profile",
            "state": "response-test",
            "code_challenge": "a" * 43,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert unsupported_response.status_code == 302
    response_query = parse_qs(urlparse(unsupported_response.headers["location"]).query)
    assert response_query["error"] == ["unsupported_response_type"]
    assert response_query["state"] == ["response-test"]

    malformed_pkce = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "test-app",
            "redirect_uri": "http://localhost:3000/callback",
            "scope": "openid profile",
            "state": "pkce-test",
            "code_challenge": "too-short",
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert malformed_pkce.status_code == 302
    pkce_query = parse_qs(urlparse(malformed_pkce.headers["location"]).query)
    assert pkce_query["error"] == ["invalid_request"]
    assert pkce_query["state"] == ["pkce-test"]


def test_oauth_endpoints_reject_duplicate_parameters(client, test_engine):
    """Repeated protocol parameters are invalid instead of silently collapsed."""
    _seed_client_and_user(test_engine)
    _verifier, challenge = _create_pkce()

    authorize = client.get(
        "/oauth/authorize",
        params=[
            ("response_type", "code"),
            ("client_id", "test-app"),
            ("client_id", "attacker-app"),
            ("redirect_uri", "http://localhost:3000/callback"),
            ("scope", "openid profile"),
            ("code_challenge", challenge),
            ("code_challenge_method", "S256"),
        ],
        follow_redirects=False,
    )
    assert authorize.status_code == 400
    assert authorize.json()["error"] == "invalid_request"
    assert authorize.headers.get("location") is None

    token = client.post(
        "/oauth/token",
        content="grant_type=client_credentials&grant_type=refresh_token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert token.status_code == 400
    assert token.json()["error"] == "invalid_request"

    introspection = client.post(
        "/oauth/introspect",
        content="token=one&token=two",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    assert introspection.status_code == 400
    assert introspection.json()["error"] == "invalid_request"
