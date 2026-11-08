"""Central-only authentication and retired issuer boundaries."""

import pytest

from tests.conftest import login_as


def test_login_redirects_to_central_start(client):
    response = client.get("/login", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/auth/start"


def test_registration_uses_signed_invite_enrollment(client):
    response = client.get("/register?invite=example")
    assert response.status_code == 200
    assert 'action="/auth/register"' in response.text
    assert 'type="password"' not in response.text


@pytest.mark.parametrize("path", ["/login", "/register", "/login/forgot-password"])
def test_local_password_authority_is_removed(client, path, monkeypatch):
    monkeypatch.setenv("CENTRAL_AUTH_ENABLED", "0")
    assert (
        client.post(
            path, data={"username": "testuser", "password": "testpass"}
        ).status_code
        == 405
    )


@pytest.mark.parametrize(
    "path",
    [
        "/oauth/authorize",
        "/oauth/token",
        "/oauth/introspect",
        "/oauth/register",
        "/oauth/userinfo",
        "/.well-known/oauth-authorization-server",
        "/.well-known/openid-configuration",
        "/admin/oauth",
    ],
)
def test_legacy_provider_surfaces_are_gone(client, path):
    assert client.get(path).status_code == 404
    assert client.post(path).status_code in {404, 405}


def test_old_local_session_cannot_be_used(client, seed_user):
    import json
    from base64 import b64encode

    from itsdangerous import TimestampSigner

    from app.config import session_config

    cookie = (
        TimestampSigner(session_config()["secret_key"])
        .sign(b64encode(json.dumps({"user_id": seed_user["id"]}).encode()))
        .decode()
    )
    client.cookies.set("session", cookie)
    assert client.get("/settings", follow_redirects=False).status_code == 303


def test_logout_clears_central_member_session(client, seed_user):
    login_as(client, seed_user["username"])
    assert client.get("/settings").status_code == 200
    assert client.post("/logout", follow_redirects=False).status_code == 303
    assert client.get("/settings", follow_redirects=False).status_code == 303


def test_central_signin_outage_has_no_local_fallback(client, monkeypatch):
    from app import oidc

    def unavailable(*args):
        raise OSError("offline")

    monkeypatch.setattr(oidc, "discovery", unavailable)
    assert client.get("/auth/start").status_code == 503
    assert (
        client.post(
            "/login", data={"username": "testuser", "password": "testpass"}
        ).status_code
        == 405
    )


def test_member_trust_acceptance_is_preserved(authed_client, test_engine, seed_user):
    from sqlalchemy import select

    from app.schema import users

    assert authed_client.get("/trust-agreement").status_code == 200
    assert (
        authed_client.post(
            "/trust-agreement", data={"accept": "yes"}, follow_redirects=False
        ).status_code
        == 303
    )
    with test_engine.connect() as conn:
        assert (
            conn.execute(
                select(users.c.has_accepted_trust).where(users.c.id == seed_user["id"])
            ).scalar_one()
            is True
        )
