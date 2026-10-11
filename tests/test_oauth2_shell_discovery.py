"""Fresh-client regression for the observed ChatGPT scope/resource mismatch.

Live retries 2026-10-04 00:59/01:00 UTC reused an Artbin client and requested
openid artbin:admin with the shell resource. Original DCR body was not captured;
omitted selectors below are a compatibility fixture, not claimed live evidence.
"""

from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import select

from app.schema import oauth2_clients
from tests.test_oauth2 import _create_pkce

RESOURCE = "https://jackharrhy.dev/mcp"


def test_resource_discovery_registers_selectorless_client_for_shell(client):
    discovery = client.get("/.well-known/oauth-authorization-server/newport-shell")
    assert discovery.status_code == 200
    metadata = discovery.json()
    assert metadata["issuer"].endswith("/newport-shell")
    assert metadata["scopes_supported"] == ["openid", "newport-shell:execute"]
    registration = client.post(
        urlparse(metadata["registration_endpoint"]).path,
        json={
            "redirect_uris": ["https://client.example/callback"],
            "grant_types": ["authorization_code", "refresh_token"],
            "token_endpoint_auth_method": "none",
        },
    )
    assert registration.status_code == 201
    registered = registration.json()
    assert registered["scope"] == "openid newport-shell:execute"
    _, challenge = _create_pkce()
    response = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": registered["client_id"],
            "redirect_uri": "https://client.example/callback",
            "scope": registered["scope"],
            "resource": RESOURCE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert urlparse(response.headers["location"]).path == "/login"


@pytest.mark.parametrize(
    "selectors",
    [
        {"resource": "https://artbin.jackharrhy.dev/mcp"},
        {"resource": RESOURCE + "/"},
        {"scope": "openid artbin:admin"},
        {"scope": "worldview:admin"},
    ],
)
def test_shell_endpoint_rejects_conflicting_selectors(client, test_engine, selectors):
    response = client.post(
        "/oauth/register/newport-shell",
        json={
            "redirect_uris": ["https://client.example/callback"],
            **selectors,
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_client_metadata"
    with test_engine.connect() as conn:
        assert conn.execute(select(oauth2_clients.c.client_id)).all() == []


def test_actual_retry_shape_stays_rejected_instead_of_expanding_old_grants(client):
    registered = client.post(
        "/oauth/register",
        json={
            "redirect_uris": ["https://client.example/callback"],
        },
    ).json()
    _, challenge = _create_pkce()
    response = client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": registered["client_id"],
            "redirect_uri": "https://client.example/callback",
            "scope": "openid artbin:admin",
            "resource": RESOURCE,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert parse_qs(urlparse(response.headers["location"]).query)["error"] == [
        "invalid_scope"
    ]
