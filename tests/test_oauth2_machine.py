"""Machine OAuth and administrator credential lifecycle tests."""

from sqlalchemy import insert, select

from app.schema import oauth2_clients, oauth2_tokens
from app.security import hash_client_secret, verify_client_secret
from tests.conftest import login_as, make_admin_user


def _service_client(conn, client_id, secret, *, introspect=False):
    conn.execute(
        insert(oauth2_clients).values(
            client_id=client_id,
            client_name=client_id,
            client_secret_hash=hash_client_secret(secret),
            principal_type="service",
            subject=client_id,
            scope="artbin:assets:read artbin:assets:content",
            grant_types="client_credentials" if not introspect else "",
            response_types="",
            token_endpoint_auth_method="client_secret_basic",
            can_introspect=introspect,
            access_token_lifetime=600,
        )
    )


def test_client_credentials_and_introspection(client, test_engine):
    with test_engine.begin() as conn:
        _service_client(conn, "worldview-service", "worldview-secret")
        _service_client(
            conn, "artbin-resource-server", "artbin-secret", introspect=True
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
        auth=("artbin-resource-server", "artbin-secret"),
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
        _service_client(conn, "worldview-service", "right-secret")

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
                principal_type="service",
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
