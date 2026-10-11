from urllib.parse import parse_qs, urlparse

import pytest
from loguru import logger

from app.oauth_registration import (
    OAuthRegistrationError,
    validate_registration_metadata,
)
from tests.conftest import login_as, make_admin_user
from tests.test_oauth2 import _create_pkce
from tests.test_oauth2_artbin_mcp import _seed_user_and_introspector

RESOURCE = "https://jackharrhy.dev/mcp"
SCOPE = "newport-shell:execute"


def test_oauth_diagnostics_identify_scope_failure_without_secrets(client):
    messages = []
    sink = logger.add(
        lambda message: messages.append(str(message)),
        filter=lambda record: record["message"].startswith("oauth_diagnostic "),
    )
    try:
        registered = client.post(
            "/oauth/register",
            json={"redirect_uris": ["https://client.example/callback"]},
        )
        _, challenge = _create_pkce()
        response = client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": registered.json()["client_id"],
                "redirect_uri": "https://client.example/callback",
                "scope": f"openid {SCOPE}",
                "resource": RESOURCE,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "private-state-not-for-logs",
            },
            follow_redirects=False,
        )
        assert parse_qs(urlparse(response.headers["location"]).query)["error"] == [
            "invalid_scope"
        ]
        diagnostics = "\n".join(messages)
        assert '"stage": "registration"' in diagnostics
        assert '"scope_present": false' in diagnostics
        assert '"stage": "authorization"' in diagnostics
        assert '"error": "invalid_scope"' in diagnostics
        assert f'"scope": "openid {SCOPE}"' in diagnostics
        assert f'"resource": "{RESOURCE}"' in diagnostics
        assert "private-state-not-for-logs" not in diagnostics
        assert challenge not in diagnostics
    finally:
        logger.remove(sink)


def test_shell_discovery(client):
    metadata = client.get("/.well-known/oauth-authorization-server").json()
    assert RESOURCE in metadata["protected_resources"]
    assert SCOPE in metadata["scopes_supported"]
    assert metadata["introspection_endpoint_auth_methods_supported"] == [
        "client_secret_basic"
    ]


@pytest.mark.parametrize("selectorless", [False, True])
def test_shell_pkce_token_introspection_and_userinfo(client, test_engine, selectorless):
    _seed_user_and_introspector(test_engine)
    with test_engine.begin() as conn:
        owner = make_admin_user(conn, "harrhy")
    login_as(client, "harrhy")
    registered = client.post(
        "/oauth/register/newport-shell" if selectorless else "/oauth/register",
        json={
            "redirect_uris": ["https://client.example/callback"],
            **(
                {}
                if selectorless
                else {"resource": RESOURCE, "scope": f"openid {SCOPE}"}
            ),
            "grant_types": ["authorization_code", "refresh_token"],
        },
    )
    assert registered.status_code == 201
    client_id = registered.json()["client_id"]
    verifier, challenge = _create_pkce()
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": "https://client.example/callback",
        "scope": f"openid {SCOPE}",
        "state": "fixture-state",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": RESOURCE,
    }
    consent = client.get("/oauth/authorize", params=params)
    assert consent.status_code == 200
    approved = client.post(
        "/oauth/authorize", data={**params, "confirm": "yes"}, follow_redirects=False
    )
    assert approved.status_code == 302
    query = parse_qs(urlparse(approved.headers["location"]).query)
    assert query["state"] == ["fixture-state"]
    token = client.post(
        "/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": query["code"][0],
            "code_verifier": verifier,
            "redirect_uri": params["redirect_uri"],
            "resource": RESOURCE,
        },
    )
    assert token.status_code == 200
    access_token = token.json()["access_token"]
    inspection = client.post(
        "/oauth/introspect",
        data={"token": access_token},
        auth=("artbin-server", "introspection-secret"),
    )
    assert inspection.status_code == 200
    assert inspection.json()["aud"] == RESOURCE
    assert inspection.json()["sub"] == str(owner)
    assert inspection.json()["active"] is True
    identity = client.get(
        "/oauth/userinfo", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert identity.json()["sub"] == str(owner)
    assert identity.json()["username"] == "harrhy"
    assert identity.json()["is_admin"] is True
    bad_refresh = client.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": token.json()["refresh_token"],
            "resource": "https://other.example/mcp",
        },
    )
    assert bad_refresh.status_code == 400


@pytest.mark.parametrize(
    "selection", [{"resource": RESOURCE}, {"scope": f"openid {SCOPE}"}]
)
def test_shell_registration_is_bound(selection):
    accepted = validate_registration_metadata(
        {"redirect_uris": ["https://client.example/callback"], **selection}
    )
    assert accepted["resource"] == RESOURCE
    assert accepted["client_name"] == "Newport Shell MCP client"
    assert accepted["scope"] == f"openid {SCOPE}"
    assert accepted["token_endpoint_auth_method"] == "none"


@pytest.mark.parametrize(
    "selection",
    [
        {"resource": RESOURCE, "scope": "worldview:admin"},
        {"resource": "https://artbin.jackharrhy.dev/mcp", "scope": SCOPE},
        {"resource": RESOURCE + "/"},
    ],
)
def test_shell_registration_rejects_resource_confusion(selection):
    with pytest.raises(OAuthRegistrationError):
        validate_registration_metadata(
            {"redirect_uris": ["https://client.example/callback"], **selection}
        )
