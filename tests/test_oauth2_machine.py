"""Machine OAuth and administrator credential lifecycle tests."""

import time

from sqlalchemy import insert, select

from app.oauth_client_admin import list_oauth_clients
from app.schema import oauth2_audit_events, oauth2_clients, oauth2_tokens
from app.security import hash_client_secret, verify_client_secret
from tests.conftest import login_as, make_admin_user


def _confidential_client(conn, client_id, secret, kind="service"):
    conn.execute(
        insert(oauth2_clients).values(
            client_id=client_id,
            client_name=client_id,
            client_secret_hash=hash_client_secret(secret),
            client_kind=kind,
            subject=client_id if kind == "service" else "",
            scope="artbin:assets:read artbin:assets:content",
            grant_types="client_credentials" if kind == "service" else "",
            response_types="",
            token_endpoint_auth_method="client_secret_basic",
            access_token_lifetime=600,
        )
    )


def test_client_credentials_and_introspection(client, test_engine):
    with test_engine.begin() as conn:
        _confidential_client(conn, "worldview-service", "worldview-secret")
        _confidential_client(
            conn, "artbin-server", "artbin-secret", kind="resource_server"
        )

    issued = client.post(
        "/oauth/token",
        data={"grant_type": "client_credentials", "scope": "artbin:assets:read"},
        auth=("worldview-service", "worldview-secret"),
    )
    assert issued.status_code == 200
    payload = issued.json()
    assert payload["scope"] == "artbin:assets:read"
    assert payload["expires_in"] == 600

    inspected = client.post(
        "/oauth/introspect",
        data={"token": payload["access_token"]},
        auth=("artbin-server", "artbin-secret"),
    )
    assert inspected.status_code == 200
    assert inspected.json() == {
        "active": True,
        "client_id": "worldview-service",
        "sub": "worldview-service",
        "principal_type": "service",
        "scope": "artbin:assets:read",
        "token_type": "Bearer",
        "exp": inspected.json()["exp"],
        "iat": inspected.json()["iat"],
    }
    assert inspected.headers["cache-control"] == "no-store"


def test_machine_oauth_rejects_bad_secret_scope_and_unauthorized_introspector(
    client, test_engine
):
    with test_engine.begin() as conn:
        _confidential_client(conn, "worldview-service", "right-secret")

    bad_secret = client.post(
        "/oauth/token",
        data={"grant_type": "client_credentials"},
        auth=("worldview-service", "wrong-secret"),
    )
    assert bad_secret.status_code == 401

    bad_scope = client.post(
        "/oauth/token",
        data={"grant_type": "client_credentials", "scope": "admin"},
        auth=("worldview-service", "right-secret"),
    )
    assert bad_scope.status_code == 400
    assert bad_scope.json()["error"] == "invalid_scope"

    denied = client.post(
        "/oauth/introspect",
        data={"token": "anything"},
        auth=("worldview-service", "right-secret"),
    )
    assert denied.status_code == 401


def test_admin_secret_rotation_is_one_time_and_overlapping(client, test_engine):
    with test_engine.begin() as conn:
        make_admin_user(conn, "admin")
        conn.execute(
            insert(oauth2_clients).values(
                client_id="worldview-service",
                client_name="Worldview service",
                client_kind="service",
                subject="worldview-service",
                grant_types="client_credentials",
                response_types="",
                token_endpoint_auth_method="client_secret_basic",
            )
        )
    login_as(client, "admin")

    generated = client.post("/admin/oauth/clients/worldview-service/secret/generate")
    assert generated.status_code == 200
    assert "will not be shown again" in generated.text
    generated_secret = generated.text.split('fourm-secret-value">', 1)[1].split("<", 1)[
        0
    ]

    with test_engine.begin() as conn:
        row = conn.execute(select(oauth2_clients)).mappings().one()
        assert generated_secret not in row["client_secret_hash"]
        assert verify_client_secret(generated_secret, row["client_secret_hash"])

    rotated = client.post("/admin/oauth/clients/worldview-service/secret/rotate")
    assert rotated.status_code == 200
    rotated_secret = rotated.text.split('fourm-secret-value">', 1)[1].split("<", 1)[0]
    with test_engine.begin() as conn:
        row = conn.execute(select(oauth2_clients)).mappings().one()
        assert verify_client_secret(rotated_secret, row["client_secret_hash"])
        assert verify_client_secret(
            generated_secret, row["previous_client_secret_hash"]
        )

    finished = client.post(
        "/admin/oauth/clients/worldview-service/secret/finish-rotation",
        follow_redirects=False,
    )
    assert finished.status_code == 303
    with test_engine.begin() as conn:
        row = conn.execute(select(oauth2_clients)).mappings().one()
        assert row["previous_client_secret_hash"] == ""
        assert conn.execute(select(oauth2_tokens)).first() is None


def test_admin_token_activity_identifies_human_and_service_principals(
    client, test_engine
):
    with test_engine.begin() as conn:
        admin_id = make_admin_user(conn, "admin")
        conn.execute(
            insert(oauth2_clients),
            [
                {
                    "client_id": "worldview",
                    "client_name": "Worldview",
                    "client_kind": "public",
                    "subject": "",
                    "grant_types": "authorization_code",
                    "response_types": "code",
                    "token_endpoint_auth_method": "none",
                },
                {
                    "client_id": "worldview-service",
                    "client_name": "Worldview service",
                    "client_kind": "service",
                    "subject": "worldview-service",
                    "grant_types": "client_credentials",
                    "response_types": "",
                    "token_endpoint_auth_method": "client_secret_basic",
                },
            ],
        )
        now = int(time.time())
        conn.execute(
            insert(oauth2_tokens),
            [
                {
                    "client_id": "worldview",
                    "user_id": admin_id,
                    "principal_type": "user",
                    "subject": str(admin_id),
                    "grant_type": "authorization_code",
                    "access_token": "human-secret-token",
                    "scope": "openid profile",
                    "issued_at": now,
                    "expires_in": 3600,
                },
                {
                    "client_id": "worldview-service",
                    "user_id": None,
                    "principal_type": "service",
                    "subject": "worldview-service",
                    "grant_type": "client_credentials",
                    "access_token": "service-secret-token",
                    "scope": "artbin:assets:read",
                    "issued_at": now - 30,
                    "expires_in": 600,
                },
                {
                    "client_id": "worldview-service",
                    "user_id": None,
                    "principal_type": "service",
                    "subject": "worldview-service",
                    "grant_type": "client_credentials",
                    "access_token": "older-service-secret-token",
                    "scope": "artbin:assets:content",
                    "issued_at": now - 900,
                    "expires_in": 600,
                },
            ],
        )
        conn.execute(
            insert(oauth2_audit_events).values(
                event_type="token_request_failed",
                client_id="worldview-service",
                success=False,
                detail="invalid_scope",
                source_ip="192.0.2.20",
            )
        )
        clients = {
            oauth_client["client_id"]: oauth_client
            for oauth_client in list_oauth_clients(conn)
        }
        service_usage = clients["worldview-service"]["principal_usage"]
        assert len(service_usage) == 1
        assert service_usage[0]["tokens_minted"] == 2
        assert service_usage[0]["active_tokens"] == 1
        assert service_usage[0]["scopes"] == (
            "artbin:assets:content artbin:assets:read"
        )
    login_as(client, "admin")

    response = client.get("/admin")

    assert response.status_code == 200
    assert "admin (@admin)" in response.text
    assert "worldview-service" in response.text
    assert "artbin:assets:read" in response.text
    assert "OAuth administration" in response.text
    assert "scope inventory" in response.text
    assert "Read the contents of Artbin assets." in response.text
    assert "capabilities &amp; lifecycle" in response.text
    assert "client_credentials" in response.text
    assert "recent OAuth activity" in response.text
    assert "token request failed" in response.text
    assert "invalid_scope" in response.text
    assert "human-secret-token" not in response.text
    assert "service-secret-token" not in response.text
    assert "older-service-secret-token" not in response.text
