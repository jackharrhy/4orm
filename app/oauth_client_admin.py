"""OAuth client administration queries and atomic credential transitions."""

import secrets
import time
from datetime import UTC, datetime

from sqlalchemy import and_, case, func, insert, select, update

from app.oauth_policy import OAUTH_SCOPE_BY_NAME, OAUTH_SCOPE_DEFINITIONS
from app.schema import oauth2_audit_events, oauth2_clients, oauth2_tokens, users
from app.security import hash_client_secret


class OAuthClientAdminError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


def _split_values(value: str, *, lines: bool = False) -> list[str]:
    return [item for item in (value.splitlines() if lines else value.split()) if item]


def _datetime_iso(value: datetime | int | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, int):
        return datetime.fromtimestamp(value, UTC).isoformat()
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.isoformat()


def _lifetime_label(seconds: int) -> str:
    if seconds % 3600 == 0:
        amount, unit = seconds // 3600, "hour"
    elif seconds % 60 == 0:
        amount, unit = seconds // 60, "minute"
    else:
        amount, unit = seconds, "second"
    return f"{amount} {unit}{'' if amount == 1 else 's'}"


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
                    func.sum(
                        case(
                            (oauth2_tokens.c.revoked.is_(True), 1),
                            else_=0,
                        )
                    ).label("revoked_token_count"),
                    func.sum(
                        case(
                            (
                                and_(
                                    oauth2_tokens.c.id.is_not(None),
                                    oauth2_tokens.c.revoked.is_(False),
                                    oauth2_tokens.c.issued_at
                                    + oauth2_tokens.c.expires_in
                                    <= now,
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ).label("expired_token_count"),
                    func.count(
                        func.distinct(
                            case(
                                (
                                    oauth2_tokens.c.refresh_family_compromised.is_(
                                        True
                                    ),
                                    oauth2_tokens.c.refresh_family_id,
                                )
                            )
                        )
                    ).label("compromised_family_count"),
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
        client["scope_list"] = _split_values(client["scope"])
        client["allowed_resource_list"] = _split_values(
            client["allowed_resources"], lines=True
        )
        client["grant_type_list"] = _split_values(client["grant_types"])
        client["response_type_list"] = _split_values(client["response_types"])
        client["redirect_uri_list"] = _split_values(client["redirect_uris"], lines=True)
        client["access_token_lifetime_label"] = _lifetime_label(
            client["access_token_lifetime"]
        )
        client["created_at_iso"] = _datetime_iso(client["created_at"])
        client["updated_at_iso"] = _datetime_iso(client["updated_at"])
        client["disabled_at_iso"] = _datetime_iso(client["disabled_at"])
        client["last_token_issued_at_iso"] = _datetime_iso(
            client["last_token_issued_at"]
        )
        client["active_token_count"] = (
            client["active_token_count"] if client["is_enabled"] else 0
        )
        if client["token_endpoint_auth_method"] == "none":
            client["credential_status"] = "public client; no secret"
        elif client["previous_client_secret_hash"]:
            client["credential_status"] = "secret rotation overlap active"
        elif client["client_secret_hash"]:
            client["credential_status"] = "client secret configured"
        else:
            client["credential_status"] = "client secret not generated"

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


def list_oauth_scope_inventory(conn, clients=None):
    """Combine defined, configured, and historically observed OAuth scopes."""
    now = int(time.time())
    clients = clients if clients is not None else list_oauth_clients(conn)
    enabled_by_client = {
        client["client_id"]: client["is_enabled"] for client in clients
    }
    inventory = {
        definition.name: {
            "name": definition.name,
            "description": definition.description,
            "surface": definition.surface,
            "is_defined": True,
            "clients": [],
            "token_count": 0,
            "active_token_count": 0,
        }
        for definition in OAUTH_SCOPE_DEFINITIONS
    }

    def scope_entry(scope_name: str) -> dict:
        definition = OAUTH_SCOPE_BY_NAME.get(scope_name)
        return inventory.setdefault(
            scope_name,
            {
                "name": scope_name,
                "description": (
                    "Observed in stored client or token data; not defined by "
                    "current policy."
                ),
                "surface": "unrecognized",
                "is_defined": definition is not None,
                "clients": [],
                "token_count": 0,
                "active_token_count": 0,
            },
        )

    for client in clients:
        for scope_name in client["scope_list"]:
            scope_entry(scope_name)["clients"].append(
                {
                    "client_id": client["client_id"],
                    "client_name": client["client_name"],
                    "is_enabled": client["is_enabled"],
                }
            )

    token_rows = (
        conn.execute(
            select(
                oauth2_tokens.c.client_id,
                oauth2_tokens.c.scope,
                oauth2_tokens.c.revoked,
                oauth2_tokens.c.issued_at,
                oauth2_tokens.c.expires_in,
            )
        )
        .mappings()
        .all()
    )
    for token in token_rows:
        for scope_name in _split_values(token["scope"]):
            entry = scope_entry(scope_name)
            entry["token_count"] += 1
            if (
                enabled_by_client.get(token["client_id"], False)
                and not token["revoked"]
                and token["issued_at"] + token["expires_in"] > now
            ):
                entry["active_token_count"] += 1

    result = list(inventory.values())
    for entry in result:
        entry["client_count"] = len(entry["clients"])
        entry["is_historical_only"] = not entry["is_defined"] and not entry["clients"]
    return sorted(result, key=lambda entry: (not entry["is_defined"], entry["name"]))


def list_recent_oauth_audit_events(conn, limit: int = 25):
    rows = (
        conn.execute(
            select(
                oauth2_audit_events,
                oauth2_clients.c.client_name,
                users.c.username.label("actor_username"),
                users.c.display_name.label("actor_display_name"),
            )
            .select_from(
                oauth2_audit_events.outerjoin(
                    oauth2_clients,
                    oauth2_audit_events.c.client_id == oauth2_clients.c.client_id,
                ).outerjoin(users, oauth2_audit_events.c.actor_user_id == users.c.id)
            )
            .order_by(
                oauth2_audit_events.c.created_at.desc(),
                oauth2_audit_events.c.id.desc(),
            )
            .limit(limit)
        )
        .mappings()
        .all()
    )
    events = []
    for row in rows:
        event = dict(row)
        event["created_at_iso"] = _datetime_iso(event["created_at"])
        event["event_label"] = event["event_type"].replace("_", " ")
        if event["actor_username"]:
            event["actor_label"] = (
                f"{event['actor_display_name']} (@{event['actor_username']})"
                if event["actor_display_name"]
                else f"@{event['actor_username']}"
            )
        else:
            event["actor_label"] = "system"
        events.append(event)
    return events


def get_oauth_admin_inventory(conn):
    clients = list_oauth_clients(conn)
    scopes = list_oauth_scope_inventory(conn, clients)
    events = list_recent_oauth_audit_events(conn)
    return {
        "clients": clients,
        "scopes": scopes,
        "events": events,
        "summary": {
            "enabled_clients": sum(client["is_enabled"] for client in clients),
            "total_clients": len(clients),
            "dynamic_clients": sum(
                client["registration_source"] == "dynamic" for client in clients
            ),
            "active_tokens": sum(client["active_token_count"] for client in clients),
            "token_records": sum(client["token_count"] for client in clients),
            "defined_scopes": len(OAUTH_SCOPE_DEFINITIONS),
        },
    }


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
