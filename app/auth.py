"""Authentication helpers shared by OAuth resources and the API."""

from __future__ import annotations

import time

from sqlalchemy import select

from app.schema import oauth2_tokens, users


def get_access_token_context(conn, access_token: str):
    """Return the token and active user for a bearer token, or ``None``."""
    token_row = (
        conn.execute(
            select(oauth2_tokens).where(
                oauth2_tokens.c.access_token == access_token,
            )
        )
        .mappings()
        .first()
    )
    if not token_row or token_row["revoked"]:
        return None
    if token_row["issued_at"] + token_row["expires_in"] < int(time.time()):
        return None

    user_row = (
        conn.execute(select(users).where(users.c.id == token_row["user_id"]))
        .mappings()
        .first()
    )
    if not user_row or user_row["is_disabled"]:
        return None
    return token_row, user_row


def get_user_for_access_token(conn, access_token: str):
    context = get_access_token_context(conn, access_token)
    return context[1] if context else None
