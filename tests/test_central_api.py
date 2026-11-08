import json
import time

import pytest
from sqlalchemy import insert

from app import oidc
from app.schema import external_identities


@pytest.fixture
def central_api(monkeypatch, tmp_path, seed_user, test_engine):
    monkeypatch.setenv("CENTRAL_API_ENABLED", "1")
    monkeypatch.setenv("OIDC_CLIENT_ID", "browser")
    monkeypatch.setenv("OIDC_PROJECT_ID", "project")
    monkeypatch.setenv("OIDC_ORGANIZATION_ID", "org")
    secret = tmp_path / "resource.json"
    secret.write_text(json.dumps({"clientId": "resource", "clientSecret": "private"}))
    monkeypatch.setenv("OIDC_API_CREDENTIALS_FILE", str(secret))
    claims = {
        "active": True,
        "iss": "https://auth.jackharrhy.dev",
        "sub": "explicit-subject",
        "aud": ["project"],
        "client_id": "native-cli",
        "exp": int(time.time()) + 300,
        "jack_auth_principal_type": "user",
        "token_type": "Bearer",
        "scope": (
            "urn:zitadel:iam:org:project:id:project:aud "
            "urn:zitadel:iam:org:projects:roles "
            "urn:zitadel:iam:org:project:role:member"
        ),
        "urn:zitadel:iam:org:project:project:roles": {"member": {"org": "domain"}},
    }
    for permission in ("pages-read", "pages-write", "media-read", "media-write"):
        claims["scope"] += f" urn:zitadel:iam:org:project:role:{permission}"
        claims["urn:zitadel:iam:org:project:project:roles"][permission] = {
            "org": "domain"
        }
    monkeypatch.setattr(
        oidc,
        "discovery",
        lambda _: {"introspection_endpoint": "https://auth.jackharrhy.dev/introspect"},
    )
    monkeypatch.setattr(oidc, "provider_json", lambda *a, **kw: claims)
    with test_engine.begin() as conn:
        conn.execute(
            insert(external_identities).values(
                issuer=claims["iss"], subject=claims["sub"], user_id=seed_user["id"]
            )
        )
    return claims


def test_central_api_resolves_explicit_link_and_preserves_content_owner(
    client, central_api
):
    headers = {"Authorization": "Bearer central-token"}
    assert client.get("/api/v1/me", headers=headers).json()["username"] == "testuser"
    assert (
        client.put(
            "/api/v1/pages/central", headers=headers, json={"title": "Central"}
        ).status_code
        == 200
    )
    assert client.get("/api/v1/pages/central", headers=headers).status_code == 200


@pytest.mark.parametrize(
    "changed",
    [
        {"active": False},
        {"iss": "https://other.example"},
        {"aud": ["other"]},
        {"sub": "unlinked", "preferred_username": "testuser"},
        {"exp": 1},
        {"jack_auth_principal_type": "service"},
        {"scope": "openid profile"},
        {"urn:zitadel:iam:org:project:project:roles": {"member": {"other": "x"}}},
    ],
)
def test_central_api_fails_closed(client, central_api, changed):
    central_api.update(changed)
    assert (
        client.get(
            "/api/v1/me", headers={"Authorization": "Bearer invalid"}
        ).status_code
        == 401
    )


def test_central_api_provider_failure_is_unavailable(client, central_api, monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("provider offline")

    monkeypatch.setattr(oidc, "provider_json", unavailable)
    assert (
        client.get("/api/v1/me", headers={"Authorization": "Bearer token"}).status_code
        == 503
    )


def test_read_only_scope_cannot_use_broad_role_claims_to_write(client, central_api):
    central_api["scope"] = central_api["scope"].replace(
        "urn:zitadel:iam:org:project:role:pages-write", ""
    )
    headers = {"Authorization": "Bearer read-only"}
    assert client.get("/api/v1/pages", headers=headers).status_code == 200
    response = client.put(
        "/api/v1/pages/forbidden", headers=headers, json={"title": "Forbidden"}
    )
    assert response.status_code == 401


def test_scope_without_role_does_not_grant_content_access(client, central_api):
    del central_api["urn:zitadel:iam:org:project:project:roles"]["media-read"]
    assert (
        client.get(
            "/api/v1/media", headers={"Authorization": "Bearer scope-without-grant"}
        ).status_code
        == 401
    )
