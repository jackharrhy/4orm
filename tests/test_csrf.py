"""Tests that verify CSRF protection is working."""

import re
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, insert
from sqlalchemy.pool import StaticPool

from app.main import app
from app.schema import metadata, profile_cards, users
from app.security import hash_password


@asynccontextmanager
async def _noop_lifespan(application):
    yield


@pytest.fixture()
def csrf_engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(eng, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def raw_client(csrf_engine):
    """A raw TestClient WITHOUT auto CSRF token injection."""
    original_engine = app.state.engine
    original_lifespan = app.router.lifespan_context

    app.state.engine = csrf_engine
    app.router.lifespan_context = _noop_lifespan

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    app.router.lifespan_context = original_lifespan
    app.state.engine = original_engine


@pytest.fixture()
def csrf_seed_user(csrf_engine):
    with csrf_engine.begin() as conn:
        result = conn.execute(
            insert(users).values(
                username="csrfuser",
                password_hash=hash_password("csrfpass"),
                display_name="CSRF User",
                content="hello",
            )
        )
        user_id = result.inserted_primary_key[0]
        conn.execute(
            insert(profile_cards).values(
                user_id=user_id,
                headline="card",
                content="card content",
            )
        )
    return {"id": user_id, "username": "csrfuser", "password": "csrfpass"}


def _extract_csrf_token(html: str) -> str:
    match = re.search(r'X-CSRF-Token["\s:]+([^"}\s]+)', html)
    return match.group(1) if match else ""


def _login(client, user):
    """Log in and return the CSRF token from the session."""
    client.post(
        "/login",
        data={"username": user["username"], "password": user["password"]},
    )
    r = client.get("/settings")
    return _extract_csrf_token(r.text)


class TestCSRFBlocks:
    """POST without a valid CSRF token should be rejected."""

    def test_post_without_token_returns_403(self, raw_client, csrf_seed_user):
        _login(raw_client, csrf_seed_user)
        r = raw_client.post(
            "/settings/profile",
            data={"display_name": "hacked"},
        )
        assert r.status_code == 403

    def test_post_with_wrong_header_returns_403(self, raw_client, csrf_seed_user):
        _login(raw_client, csrf_seed_user)
        r = raw_client.post(
            "/settings/profile",
            data={"display_name": "hacked"},
            headers={"X-CSRF-Token": "wrong-token"},
        )
        assert r.status_code == 403

    def test_no_session_returns_403(self, raw_client):
        """A POST with no session at all should be rejected."""
        r = raw_client.post(
            "/settings/profile",
            data={"display_name": "hacked"},
        )
        assert r.status_code == 403


class TestCSRFAllows:
    """POST with a valid CSRF token header should succeed."""

    def test_header_token_allows_post(self, raw_client, csrf_seed_user):
        token = _login(raw_client, csrf_seed_user)
        r = raw_client.post(
            "/settings/profile",
            data={"display_name": "Legit", "content": "hi"},
            headers={"X-CSRF-Token": token},
        )
        assert r.status_code in (200, 303)


class TestCSRFExemptPaths:
    """Login is exempt from CSRF checks."""

    def test_login_exempt(self, raw_client, csrf_seed_user):
        r = raw_client.post(
            "/login",
            data={
                "username": csrf_seed_user["username"],
                "password": csrf_seed_user["password"],
            },
        )
        assert r.status_code != 403

    def test_register_requires_csrf(self, raw_client):
        r = raw_client.post(
            "/register",
            data={
                "invite_code": "nonexistent",
                "username": "newuser",
                "password": "pass123",
            },
        )
        assert r.status_code == 403


class TestCSRFTokenInTemplates:
    """Verify that rendered pages include CSRF tokens."""

    def test_login_page_has_csrf_token(self, raw_client):
        r = raw_client.get("/login")
        assert "X-CSRF-Token" in r.text

    def test_settings_page_has_csrf_token(self, raw_client, csrf_seed_user):
        _login(raw_client, csrf_seed_user)
        r = raw_client.get("/settings")
        assert "X-CSRF-Token" in r.text

    def test_base_template_has_hx_headers(self, raw_client, csrf_seed_user):
        _login(raw_client, csrf_seed_user)
        r = raw_client.get("/settings")
        assert "hx-headers" in r.text
