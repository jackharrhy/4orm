"""Tests for the OAuth2 client TOML sync."""

import textwrap
from pathlib import Path

from sqlalchemy import delete, insert, select

from app.oauth2_clients_sync import sync_oauth2_clients
from app.schema import oauth2_clients


def test_sync_creates_new_client(test_engine, tmp_path):
    """A client in the TOML but not in the DB gets created."""
    toml = tmp_path / "clients.toml"
    toml.write_text(textwrap.dedent("""\
        [clients.myapp]
        client_name = "My App"
        redirect_uris = ["http://localhost:3000/callback"]
        scope = "openid profile"
    """))

    sync_oauth2_clients(test_engine, toml)

    with test_engine.begin() as conn:
        row = conn.execute(
            select(oauth2_clients).where(oauth2_clients.c.client_id == "myapp")
        ).mappings().first()
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
    toml.write_text(textwrap.dedent("""\
        [clients.myapp]
        client_name = "New Name"
        redirect_uris = ["http://new.com/callback"]
        scope = "openid profile"
    """))

    sync_oauth2_clients(test_engine, toml)

    with test_engine.begin() as conn:
        row = conn.execute(
            select(oauth2_clients).where(oauth2_clients.c.client_id == "myapp")
        ).mappings().first()
    assert row["client_name"] == "New Name"
    assert row["redirect_uris"] == "http://new.com/callback"
    assert row["scope"] == "openid profile"


def test_sync_removes_absent_client(test_engine, tmp_path):
    """A client in the DB but not in the TOML gets deleted."""
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
    toml.write_text(textwrap.dedent("""\
        [clients.fresh]
        client_name = "Fresh App"
        redirect_uris = ["http://fresh.com/callback"]
    """))

    sync_oauth2_clients(test_engine, toml)

    with test_engine.begin() as conn:
        stale = conn.execute(
            select(oauth2_clients).where(oauth2_clients.c.client_id == "stale")
        ).mappings().first()
        fresh = conn.execute(
            select(oauth2_clients).where(oauth2_clients.c.client_id == "fresh")
        ).mappings().first()
    assert stale is None
    assert fresh is not None


def test_sync_noop_when_unchanged(test_engine, tmp_path):
    """Running sync twice with the same config doesn't error or duplicate."""
    toml = tmp_path / "clients.toml"
    toml.write_text(textwrap.dedent("""\
        [clients.myapp]
        client_name = "My App"
        redirect_uris = ["http://localhost:3000/callback"]
    """))

    sync_oauth2_clients(test_engine, toml)
    sync_oauth2_clients(test_engine, toml)

    with test_engine.begin() as conn:
        rows = conn.execute(
            select(oauth2_clients).where(oauth2_clients.c.client_id == "myapp")
        ).mappings().all()
    assert len(rows) == 1


def test_sync_multiple_redirect_uris(test_engine, tmp_path):
    """Multiple redirect URIs are stored newline-separated."""
    toml = tmp_path / "clients.toml"
    toml.write_text(textwrap.dedent("""\
        [clients.myapp]
        client_name = "My App"
        redirect_uris = [
            "https://prod.example.com/callback",
            "http://localhost:3000/callback",
        ]
    """))

    sync_oauth2_clients(test_engine, toml)

    with test_engine.begin() as conn:
        row = conn.execute(
            select(oauth2_clients).where(oauth2_clients.c.client_id == "myapp")
        ).mappings().first()
    assert row["redirect_uris"] == "https://prod.example.com/callback\nhttp://localhost:3000/callback"


def test_sync_missing_file_is_noop(test_engine, tmp_path):
    """If the TOML file doesn't exist, sync does nothing."""
    missing = tmp_path / "does_not_exist.toml"
    # Should not raise
    sync_oauth2_clients(test_engine, missing)


def test_sync_empty_clients_section_removes_all(test_engine, tmp_path):
    """An empty [clients] section removes all existing clients."""
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
    assert len(rows) == 0
