"""Tests for Sec-Fetch-Site / Origin CSRF protection."""

import pytest

from tests.conftest import make_test_user


@pytest.fixture()
def csrf_seed_user(test_engine):
    with test_engine.begin() as conn:
        uid = make_test_user(conn, "csrfuser", password="csrfpass")
    return {"id": uid, "username": "csrfuser", "password": "csrfpass"}


def _login(client, user):
    client.post(
        "/login", data={"username": user["username"], "password": user["password"]}
    )


class TestCSRFBlocksCrossOrigin:
    """Cross-origin browser requests must be rejected."""

    def test_cross_origin_post_returns_403(self, raw_client, csrf_seed_user):
        _login(raw_client, csrf_seed_user)
        r = raw_client.post(
            "/settings/profile",
            data={"display_name": "hacked"},
            headers={"Origin": "https://evil.example.com"},
        )
        assert r.status_code == 403

    def test_sec_fetch_site_cross_site_returns_403(self, raw_client, csrf_seed_user):
        _login(raw_client, csrf_seed_user)
        r = raw_client.post(
            "/settings/profile",
            data={"display_name": "hacked"},
            headers={"Sec-Fetch-Site": "cross-site"},
        )
        assert r.status_code == 403

    def test_sec_fetch_site_same_site_returns_403(self, raw_client, csrf_seed_user):
        """same-site but not same-origin is also rejected."""
        _login(raw_client, csrf_seed_user)
        r = raw_client.post(
            "/settings/profile",
            data={"display_name": "hacked"},
            headers={"Sec-Fetch-Site": "same-site"},
        )
        assert r.status_code == 403


class TestCSRFAllowsSameOrigin:
    """Requests that pass the algorithm must be allowed."""

    def test_no_browser_headers_allows_post(self, raw_client, csrf_seed_user):
        """Non-browser clients with no Origin header are allowed."""
        _login(raw_client, csrf_seed_user)
        r = raw_client.post(
            "/settings/profile",
            data={"display_name": "Legit", "content": "hi"},
            # No Origin, no Sec-Fetch-Site — simulates curl / API client
        )
        assert r.status_code in (200, 303)

    def test_sec_fetch_site_same_origin_allows_post(self, raw_client, csrf_seed_user):
        _login(raw_client, csrf_seed_user)
        r = raw_client.post(
            "/settings/profile",
            data={"display_name": "Legit", "content": "hi"},
            headers={"Sec-Fetch-Site": "same-origin"},
        )
        assert r.status_code in (200, 303)

    def test_sec_fetch_site_none_allows_post(self, raw_client, csrf_seed_user):
        """Sec-Fetch-Site: none means direct navigation (bookmark, etc.) — allow."""
        _login(raw_client, csrf_seed_user)
        r = raw_client.post(
            "/settings/profile",
            data={"display_name": "Legit", "content": "hi"},
            headers={"Sec-Fetch-Site": "none"},
        )
        assert r.status_code in (200, 303)

    def test_matching_origin_host_allows_post(self, raw_client, csrf_seed_user):
        """Origin host matching Host header passes the fallback check."""
        _login(raw_client, csrf_seed_user)
        # TestClient sends Host: testserver by default
        r = raw_client.post(
            "/settings/profile",
            data={"display_name": "Legit", "content": "hi"},
            headers={"Origin": "http://testserver"},
        )
        assert r.status_code in (200, 303)


class TestCSRFExemptPaths:
    """Exempt paths bypass CSRF checks entirely."""

    def test_login_exempt_from_csrf(self, raw_client, csrf_seed_user):
        r = raw_client.post(
            "/login",
            data={
                "username": csrf_seed_user["username"],
                "password": csrf_seed_user["password"],
            },
            headers={"Origin": "https://evil.example.com"},  # would normally block
        )
        assert r.status_code != 403

    def test_register_is_not_exempt(self, raw_client):
        r = raw_client.post(
            "/register",
            data={"invite_code": "x", "username": "u", "password": "p"},
            headers={"Origin": "https://evil.example.com"},
        )
        assert r.status_code == 403
