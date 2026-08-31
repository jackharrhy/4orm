"""OAuth administrator inventory queries."""

import time

from sqlalchemy import insert

from app.oauth_client_admin import get_oauth_admin_inventory
from app.schema import oauth2_audit_events, oauth2_clients, oauth2_tokens
from tests.conftest import login_as, make_admin_user


def test_oauth_admin_inventory_combines_policy_capabilities_and_history(test_engine):
    now = int(time.time())
    with test_engine.begin() as conn:
        admin_id = make_admin_user(conn, "inventory-admin")
        conn.execute(
            insert(oauth2_clients).values(
                client_id="inventory-client",
                client_name="Inventory client",
                registration_source="dynamic",
                redirect_uris="https://client.example/callback\nhttp://127.0.0.1/callback",
                scope="openid legacy:write",
                allowed_resources="https://resource.example/mcp",
                grant_types="authorization_code refresh_token",
                response_types="code",
                token_endpoint_auth_method="none",
                access_token_lifetime=600,
            )
        )
        conn.execute(
            insert(oauth2_tokens),
            [
                {
                    "client_id": "inventory-client",
                    "user_id": admin_id,
                    "access_token": "inventory-active",
                    "refresh_family_id": None,
                    "refresh_family_compromised": False,
                    "scope": "openid legacy:write",
                    "issued_at": now,
                    "expires_in": 600,
                    "revoked": False,
                },
                {
                    "client_id": "inventory-client",
                    "user_id": admin_id,
                    "access_token": "inventory-expired",
                    "refresh_family_id": None,
                    "refresh_family_compromised": False,
                    "scope": "profile obsolete:read",
                    "issued_at": now - 700,
                    "expires_in": 600,
                    "revoked": False,
                },
                {
                    "client_id": "inventory-client",
                    "user_id": admin_id,
                    "access_token": "inventory-revoked-a",
                    "refresh_family_id": "compromised-family",
                    "refresh_family_compromised": True,
                    "scope": "profile",
                    "issued_at": now,
                    "expires_in": 600,
                    "revoked": True,
                },
                {
                    "client_id": "inventory-client",
                    "user_id": admin_id,
                    "access_token": "inventory-revoked-b",
                    "refresh_family_id": "compromised-family",
                    "refresh_family_compromised": True,
                    "scope": "profile",
                    "issued_at": now - 10,
                    "expires_in": 600,
                    "revoked": True,
                },
            ],
        )
        conn.execute(
            insert(oauth2_audit_events),
            [
                {
                    "event_type": "client_registered",
                    "client_id": "inventory-client",
                    "actor_user_id": None,
                    "success": True,
                    "detail": "dynamic public client",
                    "source_ip": "",
                },
                {
                    "event_type": "token_request_failed",
                    "client_id": "inventory-client",
                    "actor_user_id": admin_id,
                    "success": False,
                    "detail": "invalid_scope",
                    "source_ip": "192.0.2.10",
                },
            ],
        )

        inventory = get_oauth_admin_inventory(conn)

    client = inventory["clients"][0]
    assert client["scope_list"] == ["openid", "legacy:write"]
    assert client["grant_type_list"] == ["authorization_code", "refresh_token"]
    assert client["response_type_list"] == ["code"]
    assert client["redirect_uri_list"] == [
        "https://client.example/callback",
        "http://127.0.0.1/callback",
    ]
    assert client["access_token_lifetime_label"] == "10 minutes"
    assert client["credential_status"] == "public client; no secret"
    assert client["token_count"] == 4
    assert client["active_token_count"] == 1
    assert client["expired_token_count"] == 1
    assert client["revoked_token_count"] == 2
    assert client["compromised_family_count"] == 1
    assert client["last_token_issued_at_iso"]

    scopes = {scope["name"]: scope for scope in inventory["scopes"]}
    assert set(("openid", "profile", "artbin:admin")) <= scopes.keys()
    assert scopes["artbin:assets:content"]["token_count"] == 0
    assert scopes["openid"]["active_token_count"] == 1
    assert scopes["legacy:write"]["is_defined"] is False
    assert scopes["legacy:write"]["client_count"] == 1
    assert scopes["obsolete:read"]["is_historical_only"] is True
    assert scopes["obsolete:read"]["token_count"] == 1

    assert inventory["summary"] == {
        "enabled_clients": 1,
        "total_clients": 1,
        "dynamic_clients": 1,
        "active_tokens": 1,
        "token_records": 4,
        "defined_scopes": 5,
    }
    assert inventory["events"][0]["event_label"] == "token request failed"
    assert inventory["events"][0]["actor_label"] == (
        "inventory-admin (@inventory-admin)"
    )
    assert inventory["events"][0]["success"] is False
    assert inventory["events"][0]["source_ip"] == "192.0.2.10"
    assert inventory["events"][1]["actor_label"] == "system"


def test_dynamic_oauth_clients_are_paginated_separately(client, test_engine):
    with test_engine.begin() as conn:
        make_admin_user(conn, "pagination-admin")
        conn.execute(
            insert(oauth2_clients).values(
                client_id="managed-client",
                client_name="Managed client",
                registration_source="declarative",
                scope="openid",
            )
        )
        conn.execute(
            insert(oauth2_clients),
            [
                {
                    "client_id": f"codex-registration-{index:03d}",
                    "client_name": f"Codex session {index:03d}",
                    "registration_source": "dynamic",
                    "scope": "artbin:admin",
                }
                for index in range(27)
            ],
        )

        first_page = get_oauth_admin_inventory(conn)
        second_page = get_oauth_admin_inventory(conn, dynamic_page=2)

    assert [client["client_id"] for client in first_page["declarative_clients"]] == [
        "managed-client"
    ]
    assert len(first_page["dynamic_clients"]) == 25
    assert first_page["dynamic_clients"][0]["client_id"] == (
        "codex-registration-026"
    )
    assert first_page["dynamic_pagination"] == {
        "page": 1,
        "page_size": 25,
        "total_items": 27,
        "total_pages": 2,
        "first_item": 1,
        "last_item": 25,
        "has_previous": False,
        "has_next": True,
        "previous_page": 0,
        "next_page": 2,
    }
    assert [client["client_id"] for client in second_page["dynamic_clients"]] == [
        "codex-registration-001",
        "codex-registration-000",
    ]
    assert second_page["dynamic_pagination"]["first_item"] == 26
    assert second_page["dynamic_pagination"]["last_item"] == 27

    scopes = {scope["name"]: scope for scope in first_page["scopes"]}
    assert scopes["openid"]["client_count"] == 1
    assert scopes["openid"]["declarative_client_count"] == 1
    assert scopes["artbin:admin"]["client_count"] == 27
    assert scopes["artbin:admin"]["dynamic_client_count"] == 27
    login_as(client, "pagination-admin")

    dashboard = client.get("/admin")
    assert dashboard.status_code == 200
    assert "27" in dashboard.text
    assert 'href="/admin/oauth"' in dashboard.text
    assert "codex-registration-026" not in dashboard.text

    page_one = client.get("/admin/oauth")
    assert page_one.status_code == 200
    assert "dynamic registrations (27)" in page_one.text
    assert "showing 1\u201325 of" in page_one.text
    assert "codex-registration-026" in page_one.text
    assert "codex-registration-001" not in page_one.text
    assert "older registrations" in page_one.text

    page_two = client.get("/admin/oauth?dynamic_page=2")
    assert page_two.status_code == 200
    assert "showing 26\u201327 of" in page_two.text
    assert "page 2 of 2" in page_two.text
    assert "codex-registration-001" in page_two.text
    assert "codex-registration-026" not in page_two.text

    toggled = client.post(
        "/admin/oauth/clients/codex-registration-001/toggle-enabled?dynamic_page=2",
        follow_redirects=False,
    )
    assert toggled.status_code == 303
    assert toggled.headers["location"] == (
        "/admin/oauth?dynamic_page=2#dynamic-clients"
    )
