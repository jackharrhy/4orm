"""OAuth client administration queries and atomic credential transitions."""

import secrets

from sqlalchemy import Integer, func, insert, select, update

from app.schema import oauth2_audit_events, oauth2_clients, oauth2_tokens
from app.security import hash_client_secret


class OAuthClientAdminError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


def list_oauth_clients(conn):
    return (
        conn.execute(
            select(
                oauth2_clients,
                func.count(oauth2_tokens.c.id).label("token_count"),
                func.sum(func.cast(oauth2_tokens.c.revoked.is_(False), Integer)).label(
                    "active_token_count"
                ),
                func.max(oauth2_tokens.c.issued_at).label("last_token_issued_at"),
            )
            .select_from(
                oauth2_clients.outerjoin(
                    oauth2_tokens,
                    oauth2_tokens.c.client_id == oauth2_clients.c.client_id,
                )
            )
            .group_by(oauth2_clients.c.id)
            .order_by(oauth2_clients.c.client_name)
        )
        .mappings()
        .all()
    )


def _client(conn, client_id: str):
    row = (
        conn.execute(
            select(oauth2_clients).where(oauth2_clients.c.client_id == client_id)
        )
        .mappings()
        .first()
    )
    if not row:
        raise OAuthClientAdminError(404, "OAuth client not found")
    return row


def _audit(conn, event_type: str, client_id: str, actor_id: int, detail=""):
    conn.execute(
        insert(oauth2_audit_events).values(
            event_type=event_type,
            client_id=client_id,
            actor_user_id=actor_id,
            detail=detail,
        )
    )


def generate_secret(conn, client_id: str, actor_id: int) -> str:
    client = _client(conn, client_id)
    if client["client_kind"] == "public":
        raise OAuthClientAdminError(400, "Public clients do not use a client secret")
    if client["client_secret_hash"]:
        raise OAuthClientAdminError(
            409, "This client already has a secret; rotate it instead"
        )
    secret = secrets.token_urlsafe(48)
    conn.execute(
        update(oauth2_clients)
        .where(oauth2_clients.c.client_id == client_id)
        .values(client_secret_hash=hash_client_secret(secret), updated_at=func.now())
    )
    _audit(conn, "client_secret_generated", client_id, actor_id)
    return secret


def rotate_secret(conn, client_id: str, actor_id: int) -> str:
    client = _client(conn, client_id)
    if client["client_kind"] == "public":
        raise OAuthClientAdminError(400, "Public clients do not use a client secret")
    if not client["client_secret_hash"]:
        raise OAuthClientAdminError(409, "Generate the first secret before rotating it")
    secret = secrets.token_urlsafe(48)
    conn.execute(
        update(oauth2_clients)
        .where(oauth2_clients.c.client_id == client_id)
        .values(
            previous_client_secret_hash=client["client_secret_hash"],
            client_secret_hash=hash_client_secret(secret),
            secret_rotated_at=func.now(),
            updated_at=func.now(),
        )
    )
    _audit(conn, "client_secret_rotated", client_id, actor_id)
    return secret


def finish_rotation(conn, client_id: str, actor_id: int) -> None:
    _client(conn, client_id)
    conn.execute(
        update(oauth2_clients)
        .where(oauth2_clients.c.client_id == client_id)
        .values(previous_client_secret_hash="", updated_at=func.now())
    )
    _audit(conn, "client_secret_rotation_finished", client_id, actor_id)


def revoke_tokens(conn, client_id: str, actor_id: int) -> None:
    _client(conn, client_id)
    result = conn.execute(
        update(oauth2_tokens)
        .where(
            oauth2_tokens.c.client_id == client_id,
            oauth2_tokens.c.revoked.is_(False),
        )
        .values(revoked=True)
    )
    _audit(conn, "tokens_revoked", client_id, actor_id, str(result.rowcount))


def toggle_client(conn, client_id: str, actor_id: int) -> None:
    client = _client(conn, client_id)
    enabled = not client["is_enabled"]
    conn.execute(
        update(oauth2_clients)
        .where(oauth2_clients.c.client_id == client_id)
        .values(
            is_enabled=enabled,
            disabled_at=None if enabled else func.now(),
            updated_at=func.now(),
        )
    )
    if not enabled:
        conn.execute(
            update(oauth2_tokens)
            .where(oauth2_tokens.c.client_id == client_id)
            .values(revoked=True)
        )
    _audit(
        conn,
        "client_enabled" if enabled else "client_disabled",
        client_id,
        actor_id,
    )
