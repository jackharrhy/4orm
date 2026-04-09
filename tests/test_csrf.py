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
def csrf_client(csrf_engine):
    """A TestClient with CSRF enforcement enabled."""
    original_engine = app.state.engine
    original_lifespan = app.router.lifespan_context
    original_csrf = app.state.csrf_enabled

    app.state.engine = csrf_engine
    app.router.lifespan_context = _noop_lifespan
    app.state.csrf_enabled = True

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    app.router.lifespan_context = original_lifespan
    app.state.engine = original_engine
    app.state.csrf_enabled = original_csrf


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
    match = re.search(r'name="_csrf_token" value="([^"]+)"', html)
    return match.group(1) if match else ""


def _login(client, user):
    """Log in and return the CSRF token from the session."""
    # Login is exempt, so this works without a token
    client.post(
        "/login",
        data={"username": user["username"], "password": user["password"]},
    )
    # GET a page to obtain the CSRF token
    r = client.get("/settings")
    return _extract_csrf_token(r.text)


class TestCSRFBlocks:
    """POST without a valid CSRF token should be rejected."""

    def test_post_without_token_returns_403(self, csrf_client, csrf_seed_user):
        _login(csrf_client, csrf_seed_user)
        r = csrf_client.post(
            "/settings/profile",
            data={"display_name": "hacked"},
        )
        assert r.status_code == 403

    def test_post_with_wrong_token_returns_403(self, csrf_client, csrf_seed_user):
        _login(csrf_client, csrf_seed_user)
        r = csrf_client.post(
            "/settings/profile",
            data={"display_name": "hacked", "_csrf_token": "wrong-token"},
        )
        assert r.status_code == 403

    def test_no_session_returns_403(self, csrf_client):
        """A POST with no session at all should be rejected."""
        r = csrf_client.post(
            "/settings/profile",
            data={"display_name": "hacked"},
        )
        assert r.status_code == 403


class TestCSRFAllows:
    """POST with a valid CSRF token should succeed."""

    def test_form_token_allows_post(self, csrf_client, csrf_seed_user):
        token = _login(csrf_client, csrf_seed_user)
        r = csrf_client.post(
            "/settings/profile",
            data={"display_name": "Legit", "content": "hi", "_csrf_token": token},
        )
        # Should succeed (200 or 303 redirect)
        assert r.status_code in (200, 303)

    def test_header_token_allows_post(self, csrf_client, csrf_seed_user):
        token = _login(csrf_client, csrf_seed_user)
        r = csrf_client.post(
            "/settings/profile",
            data={"display_name": "Legit", "content": "hi"},
            headers={"X-CSRF-Token": token},
        )
        assert r.status_code in (200, 303)


class TestCSRFExemptPaths:
    """Login and register are exempt from CSRF checks."""

    def test_login_exempt(self, csrf_client, csrf_seed_user):
        r = csrf_client.post(
            "/login",
            data={
                "username": csrf_seed_user["username"],
                "password": csrf_seed_user["password"],
            },
        )
        # Should redirect on success, not 403
        assert r.status_code != 403

    def test_register_requires_csrf(self, csrf_client):
        r = csrf_client.post(
            "/register",
            data={
                "invite_code": "nonexistent",
                "username": "newuser",
                "password": "pass123",
            },
        )
        # /register is NOT exempt from CSRF — should be rejected without token
        assert r.status_code == 403


class TestCSRFTokenInTemplates:
    """Verify that rendered pages include CSRF tokens."""

    def test_login_page_has_csrf_input(self, csrf_client):
        r = csrf_client.get("/login")
        assert "_csrf_token" in r.text

    def test_settings_page_has_csrf_input(self, csrf_client, csrf_seed_user):
        _login(csrf_client, csrf_seed_user)
        r = csrf_client.get("/settings")
        assert "_csrf_token" in r.text
        # Should have multiple CSRF inputs (one per form)
        count = r.text.count('name="_csrf_token"')
        assert count >= 5

    def test_base_template_has_hx_headers(self, csrf_client, csrf_seed_user):
        _login(csrf_client, csrf_seed_user)
        r = csrf_client.get("/settings")
        assert "X-CSRF-Token" in r.text
