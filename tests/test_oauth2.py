"""Tests for the OAuth2 provider."""

from sqlalchemy import inspect, insert, select

from app.schema import oauth2_clients, oauth2_authorization_codes, oauth2_tokens


def test_oauth2_tables_exist(test_engine):
    """All three OAuth2 tables should be created."""
    inspector = inspect(test_engine)
    table_names = inspector.get_table_names()
    assert "oauth2_clients" in table_names
    assert "oauth2_authorization_codes" in table_names
    assert "oauth2_tokens" in table_names


def test_create_oauth2_client(test_engine):
    """Can insert and retrieve an OAuth2 client."""
    with test_engine.begin() as conn:
        conn.execute(
            insert(oauth2_clients).values(
                client_id="artbin",
                client_name="artbin",
                redirect_uris="https://artbin.jackharrhy.dev/auth/4orm/callback",
                scope="openid profile",
                grant_types="authorization_code",
                response_types="code",
                token_endpoint_auth_method="none",
            )
        )
        row = conn.execute(
            select(oauth2_clients).where(oauth2_clients.c.client_id == "artbin")
        ).mappings().first()
    assert row is not None
    assert row["client_name"] == "artbin"
    assert row["redirect_uris"] == "https://artbin.jackharrhy.dev/auth/4orm/callback"
