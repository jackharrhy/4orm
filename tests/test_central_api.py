import pytest

from app import oidc


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


def test_stored_legacy_token_cannot_enable_fallback(
    client, central_api, test_engine, seed_user, monkeypatch
):
    import time

    from sqlalchemy import insert

    from app.schema import oauth2_clients, oauth2_tokens

    monkeypatch.setenv("CENTRAL_API_ENABLED", "0")
    with test_engine.begin() as conn:
        conn.execute(insert(oauth2_clients).values(client_id="old", client_name="Old"))
        conn.execute(
            insert(oauth2_tokens).values(
                client_id="old",
                user_id=seed_user["id"],
                access_token="old-bearer",
                issued_at=int(time.time()),
                expires_in=3600,
            )
        )
    central_api["active"] = False
    assert (
        client.get(
            "/api/v1/me", headers={"Authorization": "Bearer old-bearer"}
        ).status_code
        == 401
    )
