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
        client["principal_usage"] = []

    usage_rows = (
        conn.execute(
            select(
                oauth2_tokens.c.client_id,
                oauth2_tokens.c.principal_type,
                oauth2_tokens.c.subject,
                oauth2_tokens.c.scope,
                users.c.username,
                users.c.display_name,
                func.count(oauth2_tokens.c.id).label("tokens_minted"),
                func.sum(
                    case(
                        (
                            and_(
                                oauth2_tokens.c.revoked.is_(False),
                                oauth2_tokens.c.issued_at + oauth2_tokens.c.expires_in
                                > now,
                            ),
                            1,
                        ),
                        else_=0,
                    )
                ).label("active_tokens"),
                func.max(oauth2_tokens.c.issued_at).label("last_minted_at"),
            )
            .select_from(
                oauth2_tokens.outerjoin(users, oauth2_tokens.c.user_id == users.c.id)
            )
            .group_by(
                oauth2_tokens.c.client_id,
                oauth2_tokens.c.principal_type,
                oauth2_tokens.c.subject,
                oauth2_tokens.c.scope,
                users.c.username,
                users.c.display_name,
            )
        )
        .mappings()
        .all()
    )
    usage_by_principal = {}
    for row in usage_rows:
        client = by_client.get(row["client_id"])
        if not client:
            continue
        key = (row["client_id"], row["principal_type"], row["subject"])
        usage = usage_by_principal.setdefault(
            key,
            {
                "principal_label": (
                    f"{row['display_name']} (@{row['username']})"
                    if row["principal_type"] == "user" and row["username"]
                    else row["subject"] or row["client_id"]
                ),
                "scopes": set(),
                "tokens_minted": 0,
                "active_tokens": 0,
                "last_minted_at": 0,
            },
        )
        usage["scopes"].update(row["scope"].split())
        usage["tokens_minted"] += row["tokens_minted"]
        usage["active_tokens"] += row["active_tokens"] if client["is_enabled"] else 0
        usage["last_minted_at"] = max(usage["last_minted_at"], row["last_minted_at"])

    for (client_id, _principal_type, _subject), usage in usage_by_principal.items():
        usage["scopes"] = " ".join(sorted(usage["scopes"])) or "—"
        usage["last_minted_at_iso"] = datetime.fromtimestamp(
            usage["last_minted_at"], UTC
        ).isoformat()
        by_client[client_id]["principal_usage"].append(usage)
    for client in clients:
        client["principal_usage"].sort(
            key=lambda usage: usage["last_minted_at"], reverse=True
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
