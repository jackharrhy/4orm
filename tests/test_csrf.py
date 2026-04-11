"""Tests that verify CSRF protection is working."""

import re

import pytest

from tests.conftest import make_test_user


@pytest.fixture()
def csrf_seed_user(test_engine):
    with test_engine.begin() as conn:
        uid = make_test_user(conn, "csrfuser", password="csrfpass")
    return {"id": uid, "username": "csrfuser", "password": "csrfpass"}


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
