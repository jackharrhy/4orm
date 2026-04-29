"""Tests for the OAuth2 provider."""

import base64
import hashlib
import os
import secrets
import time
from urllib.parse import parse_qs, urlparse

from sqlalchemy import insert, inspect, select

from app.schema import oauth2_clients, oauth2_tokens
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
        make_test_user(conn, "oauthuser", password="oauthpass")
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
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["pragma"] == "no-cache"
    token_data = r.json()
    assert "access_token" in token_data
    assert "refresh_token" not in token_data
    assert token_data["token_type"].lower() == "bearer"

    access_token = token_data["access_token"]
    r = client.get(
        "/oauth/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert r.status_code == 200
    userinfo = r.json()
    assert userinfo["username"] == "oauthuser"
    assert userinfo["is_admin"] is False


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


def test_authlib_insecure_transport_enabled_for_local_dev(monkeypatch):
    """Local HTTP dev keeps Authlib's insecure transport escape hatch."""
    from app.routes.oauth2 import _configure_authlib_transport

    monkeypatch.delenv("AUTHLIB_INSECURE_TRANSPORT", raising=False)

    _configure_authlib_transport("http://localhost:8000")

    assert os.environ["AUTHLIB_INSECURE_TRANSPORT"] == "1"


def test_authlib_insecure_transport_not_enabled_for_https_prod(monkeypatch):
    """HTTPS production config should not enable insecure OAuth transport."""
    from app.routes.oauth2 import _configure_authlib_transport

    monkeypatch.delenv("AUTHLIB_INSECURE_TRANSPORT", raising=False)

    _configure_authlib_transport("https://4orm.example")

    assert "AUTHLIB_INSECURE_TRANSPORT" not in os.environ


# ---------------------------------------------------------------------------
# Security validation helpers
# ---------------------------------------------------------------------------


def _seed_client_and_user(
    test_engine,
    client_id="test-app",
    username="oauthuser",
    password="oauthpass",
):
    """Seed an OAuth2 client and user, return (user_id, client_id)."""
    with test_engine.begin() as conn:
        user_id = make_test_user(conn, username, password=password)
        conn.execute(
            insert(oauth2_clients).values(
                client_id=client_id,
                client_secret="",
                client_name="Test App",
                redirect_uris="http://localhost:3000/callback",
                scope="openid profile",
                grant_types="authorization_code",
                response_types="code",
                token_endpoint_auth_method="none",
            )
        )
    return user_id, client_id


def _get_auth_code(
    client,
    challenge,
    client_id="test-app",
    redirect_uri="http://localhost:3000/callback",
    scope="openid profile",
):
    """Drive through consent and return the authorization code."""
    r = client.post(
        "/oauth/authorize",
        data={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "state": "s",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "confirm": "yes",
        },
        follow_redirects=False,
    )
    assert r.status_code in (302, 303), (
        f"Expected redirect, got {r.status_code}: {r.text}"
    )
    return parse_qs(urlparse(r.headers["location"]).query)["code"][0]


# ---------------------------------------------------------------------------
# Security validation tests
# ---------------------------------------------------------------------------


def test_authorize_rejects_wrong_redirect_uri(client, test_engine):
    """Valid client but unregistered redirect_uri should be rejected."""
    _seed_client_and_user(test_engine)
    client.post("/login", data={"username": "oauthuser", "password": "oauthpass"})

    # Try various malicious redirect URIs -- all should be rejected with 400
    bad_uris = [
        "http://evil.com/callback",
        "http://localhost:3000/callback/../evil",
        "http://localhost:3000/callback?extra=param",
        "//evil.com/callback",
        "javascript:alert(1)",
        "http://localhost:3000/CALLBACK",  # case sensitivity
    ]
    for uri in bad_uris:
        r = client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": "test-app",
                "redirect_uri": uri,
                "scope": "openid profile",
                "state": "s",
                "code_challenge": "abc",
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )
        assert r.status_code == 400, (
            f"redirect_uri '{uri}' should be rejected but got {r.status_code}"
        )


def test_authorize_rejects_missing_pkce(client, test_engine):
    """Authorization without code_challenge should be rejected."""
    _seed_client_and_user(test_engine)
    client.post("/login", data={"username": "oauthuser", "password": "oauthpass"})

    # Try to approve consent without code_challenge
    r = client.post(
        "/oauth/authorize",
        data={
            "response_type": "code",
            "client_id": "test-app",
            "redirect_uri": "http://localhost:3000/callback",
            "scope": "openid profile",
            "state": "s",
            # No code_challenge or code_challenge_method
            "confirm": "yes",
        },
        follow_redirects=False,
    )
    # Should either return 400 or redirect with error
    if r.status_code in (302, 303):
        qs = parse_qs(urlparse(r.headers["location"]).query)
        assert "error" in qs, "Missing PKCE should produce an error redirect"
    else:
        assert r.status_code == 400


def test_authorize_rejects_plain_pkce_method(client, test_engine):
    """Only S256 PKCE should be accepted for new authorization codes."""
    _seed_client_and_user(test_engine)
    client.post("/login", data={"username": "oauthuser", "password": "oauthpass"})

    verifier = secrets.token_urlsafe(32)
    r = client.post(
        "/oauth/authorize",
        data={
            "response_type": "code",
            "client_id": "test-app",
            "redirect_uri": "http://localhost:3000/callback",
            "scope": "openid profile",
            "state": "s",
            "code_challenge": verifier,
            "code_challenge_method": "plain",
            "confirm": "yes",
        },
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    qs = parse_qs(urlparse(r.headers["location"]).query)
    assert qs.get("error") == ["invalid_request"]
    assert "code" not in qs


def test_authorize_post_denial_rejects_unregistered_redirect_uri(client, test_engine):
    """Consent denial must not turn POST /oauth/authorize into an open redirect."""
    _seed_client_and_user(test_engine)
    client.post("/login", data={"username": "oauthuser", "password": "oauthpass"})

    r = client.post(
        "/oauth/authorize",
        data={
            "response_type": "code",
            "client_id": "test-app",
            "redirect_uri": "https://evil.example/callback",
            "scope": "openid profile",
            "state": "s",
            "code_challenge": "abc",
            "code_challenge_method": "S256",
            "confirm": "no",
        },
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert (
        r.headers.get("location")
        != "https://evil.example/callback?error=access_denied&state=s"
    )


def test_authorize_post_error_rejects_unregistered_redirect_uri(client, test_engine):
    """Authorization errors must not redirect to an unregistered redirect_uri."""
    _seed_client_and_user(test_engine)
    client.post("/login", data={"username": "oauthuser", "password": "oauthpass"})

    r = client.post(
        "/oauth/authorize",
        data={
            "response_type": "code",
            "client_id": "test-app",
            "redirect_uri": "https://evil.example/callback",
            "scope": "openid profile",
            "state": "s",
            "confirm": "yes",
        },
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert r.headers.get("location") is None


def test_token_rejects_missing_verifier(client, test_engine):
    """Token exchange without code_verifier should fail."""
    _seed_client_and_user(test_engine)
    client.post("/login", data={"username": "oauthuser", "password": "oauthpass"})

    verifier, challenge = _create_pkce()
    code = _get_auth_code(client, challenge)

    r = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://localhost:3000/callback",
            "client_id": "test-app",
            # No code_verifier
        },
    )
    assert r.status_code == 400


def test_code_cannot_be_reused(client, test_engine):
    """An authorization code should only be usable once."""
    _seed_client_and_user(test_engine)
    client.post("/login", data={"username": "oauthuser", "password": "oauthpass"})

    verifier, challenge = _create_pkce()
    code = _get_auth_code(client, challenge)

    # First exchange should succeed
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

    # Second exchange with same code should fail
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
    assert r.status_code == 400


def test_code_rejected_for_wrong_client(client, test_engine):
    """A code issued to client-a cannot be exchanged by client-b."""
    with test_engine.begin() as conn:
        make_test_user(conn, "oauthuser", password="oauthpass")
        conn.execute(
            insert(oauth2_clients).values(
                client_id="client-a",
                client_secret="",
                client_name="App A",
                redirect_uris="http://localhost:3000/callback",
                scope="openid profile",
                grant_types="authorization_code",
                response_types="code",
                token_endpoint_auth_method="none",
            )
        )
        conn.execute(
            insert(oauth2_clients).values(
                client_id="client-b",
                client_secret="",
                client_name="App B",
                redirect_uris="http://localhost:4000/callback",
                scope="openid profile",
                grant_types="authorization_code",
                response_types="code",
                token_endpoint_auth_method="none",
            )
        )
    client.post("/login", data={"username": "oauthuser", "password": "oauthpass"})

    verifier, challenge = _create_pkce()
    code = _get_auth_code(client, challenge, client_id="client-a")

    # Try to exchange using client-b
    r = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://localhost:3000/callback",
            "client_id": "client-b",
            "code_verifier": verifier,
        },
    )
    assert r.status_code == 400


def test_code_rejected_for_wrong_redirect_uri(client, test_engine):
    """Token exchange must use the same redirect_uri as the authorize request."""
    _seed_client_and_user(test_engine)
    client.post("/login", data={"username": "oauthuser", "password": "oauthpass"})

    verifier, challenge = _create_pkce()
    code = _get_auth_code(client, challenge)

    r = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://localhost:9999/different",
            "client_id": "test-app",
            "code_verifier": verifier,
        },
    )
    assert r.status_code == 400


def test_userinfo_rejects_expired_token(client, test_engine):
    """Userinfo should reject tokens past their expiry."""
    _seed_client_and_user(test_engine)

    # Insert a token that expired in the past
    with test_engine.begin() as conn:
        conn.execute(
            insert(oauth2_tokens).values(
                client_id="test-app",
                user_id=1,
                token_type="Bearer",
                access_token="expired-token-abc",
                scope="openid profile",
                issued_at=int(time.time()) - 7200,  # 2 hours ago
                expires_in=3600,  # 1 hour lifetime = expired 1 hour ago
            )
        )

    r = client.get(
        "/oauth/userinfo",
        headers={"Authorization": "Bearer expired-token-abc"},
    )
    assert r.status_code == 401


def test_userinfo_requires_openid_scope(client, test_engine):
    """The userinfo endpoint should not disclose profile data for unscoped tokens."""
    _seed_client_and_user(test_engine)

    with test_engine.begin() as conn:
        conn.execute(
            insert(oauth2_tokens).values(
                client_id="test-app",
                user_id=1,
                token_type="Bearer",
                access_token="profileless-token",
                scope="",
                issued_at=int(time.time()),
                expires_in=3600,
            )
        )

    r = client.get(
        "/oauth/userinfo",
        headers={"Authorization": "Bearer profileless-token"},
    )
    assert r.status_code == 403


def test_consent_denial_redirects_with_error(client, test_engine):
    """Clicking deny should redirect with error=access_denied."""
    _seed_client_and_user(test_engine)
    client.post("/login", data={"username": "oauthuser", "password": "oauthpass"})

    verifier, challenge = _create_pkce()
    r = client.post(
        "/oauth/authorize",
        data={
            "response_type": "code",
            "client_id": "test-app",
            "redirect_uri": "http://localhost:3000/callback",
            "scope": "openid profile",
            "state": "deny-test",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "confirm": "no",
        },
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    qs = parse_qs(urlparse(r.headers["location"]).query)
    assert qs.get("error") == ["access_denied"]


def test_userinfo_rejects_revoked_token(client, test_engine):
    """Userinfo should reject revoked tokens."""
    _seed_client_and_user(test_engine)

    import time
    with test_engine.begin() as conn:
        conn.execute(
            insert(oauth2_tokens).values(
                client_id="test-app",
                user_id=1,
                token_type="Bearer",
                access_token="revoked-token-xyz",
                scope="openid profile",
                issued_at=int(time.time()),
                expires_in=3600,
                revoked=True,
            )
        )

    r = client.get(
        "/oauth/userinfo",
        headers={"Authorization": "Bearer revoked-token-xyz"},
    )
    assert r.status_code == 401


def test_userinfo_rejects_missing_auth_header(client):
    """Userinfo with no Authorization header should return 401."""
    r = client.get("/oauth/userinfo")
    assert r.status_code == 401


def test_userinfo_rejects_non_bearer_auth(client):
    """Userinfo with non-Bearer auth scheme should return 401."""
    r = client.get(
        "/oauth/userinfo",
        headers={"Authorization": "Basic dXNlcjpwYXNz"},
    )
    assert r.status_code == 401


def test_authorize_unauthenticated_stashes_and_resumes(client, test_engine):
    """Full flow: unauthenticated authorize -> login -> consent screen."""
    _seed_client_and_user(test_engine)

    # 1. Hit authorize without being logged in
    verifier, challenge = _create_pkce()
    r = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "test-app",
            "redirect_uri": "http://localhost:3000/callback",
            "scope": "openid profile",
            "state": "resume-test",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    location = r.headers["location"]
    # Short, clean URL -- not a massive encoded blob
    assert location == "/login?next=oauth&client_id=test-app"

    # 2. Log in -- should redirect to the authorize URL, not the profile
    r = client.post(
        "/login",
        data={
            "username": "oauthuser",
            "password": "oauthpass",
            "next": "oauth",
            "client_id": "test-app",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    location = r.headers["location"]
    assert "/oauth/authorize?" in location
    assert "client_id=test-app" in location
    assert "state=resume-test" in location

    # 3. Follow the redirect -- should show consent page
    r = client.get(location, follow_redirects=False)
    assert r.status_code == 200
    assert "Test App" in r.text


def test_login_without_oauth_goes_to_profile(client, test_engine):
    """Normal login (no OAuth flow) still goes to profile."""
    with test_engine.begin() as conn:
        make_test_user(conn, "normaluser", password="pass")

    r = client.post(
        "/login",
        data={"username": "normaluser", "password": "pass"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "/u/normaluser" in r.headers["location"]


def test_login_next_oauth_without_session_goes_to_profile(client, test_engine):
    """Posting next=oauth without stashed session params goes to profile."""
    with test_engine.begin() as conn:
        make_test_user(conn, "trickuser", password="pass")

    r = client.post(
        "/login",
        data={
            "username": "trickuser",
            "password": "pass",
            "next": "oauth",
            "client_id": "fake",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    # No stashed oauth_params in session, so falls back to profile
    assert "/u/trickuser" in r.headers["location"]
