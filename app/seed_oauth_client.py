"""Seed an OAuth2 client for artbin.

Usage: uv run python -m app.seed_oauth_client
"""

from sqlalchemy import insert, select

from app.db import engine
from app.schema import oauth2_clients


def seed():
    client_id = "artbin"
    with engine.begin() as conn:
        existing = (
            conn.execute(
                select(oauth2_clients).where(oauth2_clients.c.client_id == client_id)
            )
            .mappings()
            .first()
        )
        if existing:
            print(f"OAuth2 client '{client_id}' already exists.")
            return

        conn.execute(
            insert(oauth2_clients).values(
                client_id=client_id,
                client_secret="",
                client_name="artbin",
                redirect_uris="https://artbin.jackharrhy.dev/auth/4orm/callback\nhttp://localhost:5173/auth/4orm/callback",
                scope="openid profile",
                grant_types="authorization_code",
                response_types="code",
                token_endpoint_auth_method="none",
            )
        )
        print(f"Created OAuth2 client '{client_id}'.")


if __name__ == "__main__":
    seed()
