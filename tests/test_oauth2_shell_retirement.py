"""Retired shell endpoints cannot advertise or recreate executable shell access."""

import pytest
from sqlalchemy import func, select

from app.schema import oauth2_clients

RESOURCE = "https://jackharrhy.dev/mcp"
SCOPE = "newport-shell:execute"


def test_discovery_preserves_other_resources_without_shell(client):
    metadata = client.get("/.well-known/oauth-authorization-server").json()
    assert RESOURCE not in metadata["protected_resources"]
    assert SCOPE not in metadata["scopes_supported"]
    assert len(metadata["protected_resources"]) == 3
    assert "maps:admin" in metadata["scopes_supported"]
    assert "worldview:admin" in metadata["scopes_supported"]
    assert "artbin:admin" in metadata["scopes_supported"]


@pytest.mark.parametrize(
    "path",
    [
        "/.well-known/oauth-authorization-server/newport-shell",
        "/.well-known/openid-configuration/newport-shell",
        "/newport-shell/.well-known/openid-configuration",
    ],
)
def test_shell_discovery_is_gone(client, path):
    assert client.get(path).status_code == 404


def test_shell_specific_registration_is_gone(client):
    assert client.post("/oauth/register/newport-shell", json={}).status_code == 404


@pytest.mark.parametrize("selection", [{"resource": RESOURCE}, {"scope": SCOPE}])
def test_generic_registration_cannot_recreate_shell_or_fall_back_to_artbin(
    client, test_engine, selection
):
    response = client.post(
        "/oauth/register",
        json={"redirect_uris": ["https://client.example/callback"], **selection},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_client_metadata"
    with test_engine.connect() as conn:
        assert conn.scalar(select(func.count()).select_from(oauth2_clients)) == 0
