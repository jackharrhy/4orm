"""OAuth client administration queries and atomic credential transitions."""

import secrets
import time
from datetime import UTC, datetime

from sqlalchemy import and_, case, func, insert, select, update

from app.schema import oauth2_audit_events, oauth2_clients, oauth2_tokens, users
from app.security import hash_client_secret


class OAuthClientAdminError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


def list_oauth_clients(conn):
    now = int(time.time())
    clients = [
        dict(row)
        for row in (
            conn.execute(
                select(
                    oauth2_clients,
                    func.count(oauth2_tokens.c.id).label("token_count"),
                    func.sum(
                        case(
                            (
                                and_(
                                    oauth2_tokens.c.revoked.is_(False),
                                    oauth2_tokens.c.issued_at
                                    + oauth2_tokens.c.expires_in
                                    > now,
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ).label("active_token_count"),
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
    ]
    by_client = {client["client_id"]: client for client in clients}
    for client in clients:
        client["token_activity"] = []

    ranked_tokens = select(
        oauth2_tokens.c.id,
        oauth2_tokens.c.client_id,
        oauth2_tokens.c.user_id,
        oauth2_tokens.c.principal_type,
        oauth2_tokens.c.subject,
        oauth2_tokens.c.grant_type,
        oauth2_tokens.c.scope,
        oauth2_tokens.c.issued_at,
        oauth2_tokens.c.expires_in,
        oauth2_tokens.c.revoked,
        func.row_number()
        .over(
            partition_by=oauth2_tokens.c.client_id,
            order_by=(
                oauth2_tokens.c.issued_at.desc(),
                oauth2_tokens.c.id.desc(),
            ),
        )
        .label("client_rank"),
    ).subquery()
    activity = (
        conn.execute(
            select(
                ranked_tokens,
                users.c.username,
                users.c.display_name,
            )
            .select_from(
                ranked_tokens.outerjoin(users, ranked_tokens.c.user_id == users.c.id)
            )
            .where(ranked_tokens.c.client_rank <= 10)
            .order_by(ranked_tokens.c.issued_at.desc(), ranked_tokens.c.id.desc())
        )
        .mappings()
        .all()
    )
    for row in activity:
        client = by_client.get(row["client_id"])
        if not client:
            continue
        issued_at = row["issued_at"]
        expires_at = issued_at + row["expires_in"]
        client["token_activity"].append(
            {
                **dict(row),
                "principal_label": (
                    f"{row['display_name']} (@{row['username']})"
                    if row["principal_type"] == "user" and row["username"]
                    else row["subject"] or row["client_id"]
                ),
                "issued_at_iso": datetime.fromtimestamp(issued_at, UTC).isoformat(),
                "expires_at_iso": datetime.fromtimestamp(expires_at, UTC).isoformat(),
                "is_active": bool(
                    client["is_enabled"] and not row["revoked"] and expires_at > now
                ),
            }
        )
    return clients


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
