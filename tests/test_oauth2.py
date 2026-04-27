"""Tests for the OAuth2 provider."""

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlparse

from sqlalchemy import inspect, insert, select

from app.schema import oauth2_clients, oauth2_authorization_codes, oauth2_tokens
from tests.conftest import make_test_user


def test_oauth2_tables_exist(test_engine):
    """All three OAuth2 tables should be created."""
    inspector = inspect(test_engine)
    table_names = inspector.get_table_names()
    assert "oauth2_clients" in table_names
    assert "oauth2_authorization_codes" in table_names
    assert "oauth2_tokens" in table_names


def test_create_oauth2_client(test_engine):
    """Can insert and retrieve an OAuth2 client."""
    with test_engine.begin() as conn:
        conn.execute(
            insert(oauth2_clients).values(
                client_id="artbin",
                client_name="artbin",
                redirect_uris="https://artbin.jackharrhy.dev/auth/4orm/callback",
                scope="openid profile",
                grant_types="authorization_code",
                response_types="code",
                token_endpoint_auth_method="none",
            )
        )
        row = conn.execute(
            select(oauth2_clients).where(oauth2_clients.c.client_id == "artbin")
        ).mappings().first()
    assert row is not None
    assert row["client_name"] == "artbin"
    assert row["redirect_uris"] == "https://artbin.jackharrhy.dev/auth/4orm/callback"


def test_authorization_server_creates(test_engine):
    """The authorization server should instantiate without error."""
    from app.oauth2 import create_authorization_server

    server = create_authorization_server(test_engine)
    assert server is not None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_pkce():
    """Generate a PKCE code verifier and challenge."""
    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


# ---------------------------------------------------------------------------
# Route tests
# ---------------------------------------------------------------------------


def test_full_oauth2_flow(client, test_engine):
    """End-to-end: authorize -> consent -> token -> userinfo."""
    with test_engine.begin() as conn:
        user_id = make_test_user(conn, "oauthuser", password="oauthpass")
        conn.execute(
            insert(oauth2_clients).values(
                client_id="test-app",
                client_secret="",
                client_name="Test App",
                redirect_uris="http://localhost:3000/callback",
                scope="openid profile",
                grant_types="authorization_code",
                response_types="code",
                token_endpoint_auth_method="none",
            )
        )

    client.post("/login", data={"username": "oauthuser", "password": "oauthpass"})

    verifier, challenge = _create_pkce()
    r = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "test-app",
            "redirect_uri": "http://localhost:3000/callback",
            "scope": "openid profile",
            "state": "test-state",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert "Test App" in r.text

    r = client.post(
        "/oauth/authorize",
        data={
            "response_type": "code",
            "client_id": "test-app",
            "redirect_uri": "http://localhost:3000/callback",
            "scope": "openid profile",
            "state": "test-state",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "confirm": "yes",
        },
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    location = r.headers["location"]
    parsed = urlparse(location)
    qs = parse_qs(parsed.query)
    assert "code" in qs
    assert qs["state"] == ["test-state"]
    code = qs["code"][0]

    r = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://localhost:3000/callback",
            "client_id": "test-app",
            "code_verifier": verifier,
        },
    )
    assert r.status_code == 200
    token_data = r.json()
    assert "access_token" in token_data
    assert token_data["token_type"].lower() == "bearer"

    access_token = token_data["access_token"]
    r = client.get(
        "/oauth/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert r.status_code == 200
    userinfo = r.json()
    assert userinfo["username"] == "oauthuser"


def test_authorize_requires_login(client, test_engine):
    r = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "test-app",
            "redirect_uri": "http://localhost:3000/callback",
            "scope": "openid profile",
            "state": "s",
            "code_challenge": "abc",
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "/login" in r.headers["location"]


def test_authorize_rejects_bad_client(client, test_engine):
    with test_engine.begin() as conn:
        make_test_user(conn, "oauthuser2", password="pass")
    client.post("/login", data={"username": "oauthuser2", "password": "pass"})

    r = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "nonexistent",
            "redirect_uri": "http://evil.com/callback",
            "scope": "openid profile",
            "state": "s",
            "code_challenge": "abc",
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert r.status_code == 400


def test_token_rejects_bad_verifier(client, test_engine):
    with test_engine.begin() as conn:
        make_test_user(conn, "pkceuser", password="pass")
        conn.execute(
            insert(oauth2_clients).values(
                client_id="pkce-app",
                client_secret="",
                client_name="PKCE App",
                redirect_uris="http://localhost:3000/callback",
                scope="openid profile",
                grant_types="authorization_code",
                response_types="code",
                token_endpoint_auth_method="none",
            )
        )
    client.post("/login", data={"username": "pkceuser", "password": "pass"})

    verifier, challenge = _create_pkce()
    client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "pkce-app",
            "redirect_uri": "http://localhost:3000/callback",
            "scope": "openid profile",
            "state": "s",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
    )
    r = client.post(
        "/oauth/authorize",
        data={
            "response_type": "code",
            "client_id": "pkce-app",
            "redirect_uri": "http://localhost:3000/callback",
            "scope": "openid profile",
            "state": "s",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "confirm": "yes",
        },
        follow_redirects=False,
    )
    location = r.headers["location"]
    code = parse_qs(urlparse(location).query)["code"][0]

    r = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://localhost:3000/callback",
            "client_id": "pkce-app",
            "code_verifier": "wrong-verifier-that-does-not-match",
        },
    )
    assert r.status_code == 400


def test_userinfo_rejects_bad_token(client):
    r = client.get(
        "/oauth/userinfo",
        headers={"Authorization": "Bearer invalid-token-here"},
    )
    assert r.status_code == 401


def test_openid_configuration(client):
    r = client.get("/.well-known/openid-configuration")
    assert r.status_code == 200
    data = r.json()
    assert "authorization_endpoint" in data
    assert "token_endpoint" in data
    assert "userinfo_endpoint" in data
