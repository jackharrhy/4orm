"""Tests for the OAuth2 client TOML sync."""

import textwrap
import tomllib
from pathlib import Path

import pytest
from sqlalchemy import insert, select

from app.oauth2_clients_sync import sync_oauth2_clients
from app.schema import oauth2_clients


def test_repository_registers_worldview_client():
    config = tomllib.loads(
        (Path(__file__).parents[1] / "oauth2_clients.toml").read_text()
    )
    worldview = config["clients"]["worldview"]

    assert worldview["client_name"] == "Worldview"
    assert worldview["scope"] == "openid profile"
    assert worldview["grant_types"] == "authorization_code"
    assert worldview["token_endpoint_auth_method"] == "none"
    assert "https://worldview.harrhy.xyz/auth/callback" in worldview["redirect_uris"]
    assert "http://localhost:8789/auth/callback" in worldview["redirect_uris"]

    service = config["clients"]["worldview-service"]
    assert service["client_kind"] == "service"
    assert service["scope"] == "artbin:assets:read artbin:assets:content"
    assert "artbin:wads:inspect" not in service["scope"]

    artbin = config["clients"]["artbin-server"]
    assert artbin["client_kind"] == "resource_server"


def test_sync_derives_service_and_resource_server_invariants(test_engine, tmp_path):
    toml = tmp_path / "clients.toml"
    toml.write_text(
        textwrap.dedent("""\
        [clients.service]
        client_name = "Service"
        client_kind = "service"
        subject = "service"
        scope = "assets:read"

        [clients.resource]
        client_name = "Resource"
        client_kind = "resource_server"
    """)
    )
    sync_oauth2_clients(test_engine, toml)
    with test_engine.begin() as conn:
        rows = {
            row["client_id"]: row
            for row in conn.execute(select(oauth2_clients)).mappings().all()
        }
    assert rows["service"]["grant_types"] == "client_credentials"
    assert rows["service"]["token_endpoint_auth_method"] == "client_secret_basic"
    assert rows["resource"]["grant_types"] == ""
    assert rows["resource"]["scope"] == ""
    assert rows["resource"]["token_endpoint_auth_method"] == "client_secret_basic"


def test_sync_creates_new_client(test_engine, tmp_path):
    """A client in the TOML but not in the DB gets created."""
    toml = tmp_path / "clients.toml"
    toml.write_text(
        textwrap.dedent("""\
        [clients.myapp]
        client_name = "My App"
        redirect_uris = ["http://localhost:3000/callback"]
        scope = "openid profile"
    """)
    )

    sync_oauth2_clients(test_engine, toml)

    with test_engine.begin() as conn:
        row = (
            conn.execute(
                select(oauth2_clients).where(oauth2_clients.c.client_id == "myapp")
            )
            .mappings()
            .first()
        )
    assert row is not None
    assert row["client_name"] == "My App"
    assert row["redirect_uris"] == "http://localhost:3000/callback"
    assert row["scope"] == "openid profile"
    assert row["token_endpoint_auth_method"] == "none"


def test_sync_updates_existing_client(test_engine, tmp_path):
    """A client that already exists gets updated when the TOML changes."""
    with test_engine.begin() as conn:
        conn.execute(
            insert(oauth2_clients).values(
                client_id="myapp",
                client_name="Old Name",
                redirect_uris="http://old.com/callback",
                scope="openid",
                token_endpoint_auth_method="none",
            )
        )

    toml = tmp_path / "clients.toml"
    toml.write_text(
        textwrap.dedent("""\
        [clients.myapp]
        client_name = "New Name"
        redirect_uris = ["http://new.com/callback"]
        scope = "openid profile"
    """)
    )

    sync_oauth2_clients(test_engine, toml)

    with test_engine.begin() as conn:
        row = (
            conn.execute(
                select(oauth2_clients).where(oauth2_clients.c.client_id == "myapp")
            )
            .mappings()
            .first()
        )
    assert row["client_name"] == "New Name"
    assert row["redirect_uris"] == "http://new.com/callback"
    assert row["scope"] == "openid profile"


def test_sync_disables_absent_client(test_engine, tmp_path):
    """A client absent from TOML is retained but disabled."""
    with test_engine.begin() as conn:
        conn.execute(
            insert(oauth2_clients).values(
                client_id="stale",
                client_name="Stale App",
                redirect_uris="http://stale.com/callback",
                token_endpoint_auth_method="none",
            )
        )

    toml = tmp_path / "clients.toml"
    toml.write_text(
        textwrap.dedent("""\
        [clients.fresh]
        client_name = "Fresh App"
        redirect_uris = ["http://fresh.com/callback"]
    """)
    )

    sync_oauth2_clients(test_engine, toml)

    with test_engine.begin() as conn:
        stale = (
            conn.execute(
                select(oauth2_clients).where(oauth2_clients.c.client_id == "stale")
            )
            .mappings()
            .first()
        )
        fresh = (
            conn.execute(
                select(oauth2_clients).where(oauth2_clients.c.client_id == "fresh")
            )
            .mappings()
            .first()
        )
    assert stale is not None
    assert stale["is_enabled"] is False
    assert fresh is not None


def test_sync_noop_when_unchanged(test_engine, tmp_path):
    """Running sync twice with the same config doesn't error or duplicate."""
    toml = tmp_path / "clients.toml"
    toml.write_text(
        textwrap.dedent("""\
        [clients.myapp]
        client_name = "My App"
        redirect_uris = ["http://localhost:3000/callback"]
    """)
    )

    sync_oauth2_clients(test_engine, toml)
    sync_oauth2_clients(test_engine, toml)

    with test_engine.begin() as conn:
        rows = (
            conn.execute(
                select(oauth2_clients).where(oauth2_clients.c.client_id == "myapp")
            )
            .mappings()
            .all()
        )
    assert len(rows) == 1


def test_sync_multiple_redirect_uris(test_engine, tmp_path):
    """Multiple redirect URIs are stored newline-separated."""
    toml = tmp_path / "clients.toml"
    toml.write_text(
        textwrap.dedent("""\
        [clients.myapp]
        client_name = "My App"
        redirect_uris = [
            "https://prod.example.com/callback",
            "http://localhost:3000/callback",
        ]
    """)
    )

    sync_oauth2_clients(test_engine, toml)

    with test_engine.begin() as conn:
        row = (
            conn.execute(
                select(oauth2_clients).where(oauth2_clients.c.client_id == "myapp")
            )
            .mappings()
            .first()
        )
    assert (
        row["redirect_uris"]
        == "https://prod.example.com/callback\nhttp://localhost:3000/callback"
    )


def test_sync_missing_file_is_noop(test_engine, tmp_path):
    """If the TOML file doesn't exist, sync does nothing."""
    missing = tmp_path / "does_not_exist.toml"
    # Should not raise
    sync_oauth2_clients(test_engine, missing)


def test_sync_empty_clients_section_disables_all(test_engine, tmp_path):
    """An empty clients section disables every declarative client."""
    with test_engine.begin() as conn:
        conn.execute(
            insert(oauth2_clients).values(
                client_id="old",
                client_name="Old App",
                redirect_uris="http://old.com/callback",
                token_endpoint_auth_method="none",
            )
        )

    toml = tmp_path / "clients.toml"
    toml.write_text("[clients]\n")

    sync_oauth2_clients(test_engine, toml)

    with test_engine.begin() as conn:
        rows = conn.execute(select(oauth2_clients)).mappings().all()
    assert len(rows) == 1
    assert rows[0]["is_enabled"] is False


def test_sync_preserves_dynamically_registered_clients(test_engine, tmp_path):
    with test_engine.begin() as conn:
        conn.execute(
            insert(oauth2_clients).values(
                client_id="artbin-mcp-dynamic",
                client_name="Dynamic MCP client",
                client_kind="public",
                registration_source="dynamic",
                redirect_uris="http://127.0.0.1:43127/oauth/callback",
                scope="artbin:admin",
                allowed_resources="https://artbin.jackharrhy.dev/mcp",
                grant_types="authorization_code refresh_token",
                response_types="code",
                token_endpoint_auth_method="none",
            )
        )

    toml = tmp_path / "clients.toml"
    toml.write_text("[clients]\n")
    sync_oauth2_clients(test_engine, toml)

    with test_engine.begin() as conn:
        row = (
            conn.execute(
                select(oauth2_clients).where(
                    oauth2_clients.c.client_id == "artbin-mcp-dynamic"
                )
            )
            .mappings()
            .one()
        )
    assert row["is_enabled"] is True
    assert row["registration_source"] == "dynamic"
    assert row["allowed_resources"] == "https://artbin.jackharrhy.dev/mcp"


def test_sync_refuses_to_overwrite_dynamic_client(test_engine, tmp_path):
    with test_engine.begin() as conn:
        conn.execute(
            insert(oauth2_clients).values(
                client_id="collision",
                client_name="Dynamic client",
                registration_source="dynamic",
                redirect_uris="http://127.0.0.1:43127/oauth/callback",
                token_endpoint_auth_method="none",
            )
        )

    toml = tmp_path / "clients.toml"
    toml.write_text(
        textwrap.dedent("""\
        [clients.collision]
        client_name = "Declarative client"
        redirect_uris = ["https://client.example/callback"]
    """)
    )

    with pytest.raises(ValueError, match="conflicts with a dynamically"):
        sync_oauth2_clients(test_engine, toml)
