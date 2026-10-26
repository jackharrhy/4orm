"""Reserve member invites while Jack Auth handles account creation."""

import base64
import hmac
import json
import os
import secrets
import time
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, insert, or_, select, update

from app.deps import USERNAME_RE
from app.schema import (
    auth_enrollments,
    external_identities,
    invites,
    profile_cards,
    users,
)
from app.security import hash_password

LIFETIME = 1800


def integration_key():
    path = os.environ.get("CENTRAL_AUTH_ENROLLMENT_KEY_FILE")
    if not path:
        raise ValueError("Enrollment integration is not configured")
    value = json.loads(Path(path).read_text())["token"]
    if not isinstance(value, str) or len(value) < 32:
        raise ValueError("Enrollment integration key is invalid")
    return value


def ticket(record):
    payload = {
        "version": 1,
        "application": "fourm",
        "requestId": record["id"],
        "expires": record["expires_at"],
    }
    encoded = (
        base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode())
        .decode()
        .rstrip("=")
    )
    signature = (
        base64.urlsafe_b64encode(
            hmac.digest(integration_key().encode(), encoded.encode(), "sha256")
        )
        .decode()
        .rstrip("=")
    )
    return encoded + "." + signature


def reserve(conn, code, previous=None, now=None):
    now = int(time.time()) if now is None else now
    if previous:
        existing = (
            conn.execute(
                select(auth_enrollments)
                .join(invites, auth_enrollments.c.invite_id == invites.c.id)
                .where(
                    auth_enrollments.c.id == previous,
                    invites.c.code == code,
                    invites.c.disabled.is_(False),
                    or_(
                        invites.c.expires_at.is_(None),
                        invites.c.expires_at > datetime.fromtimestamp(now, UTC),
                    ),
                    auth_enrollments.c.expires_at > now,
                    auth_enrollments.c.consumed_at.is_(None),
                )
            )
            .mappings()
            .first()
        )
        if existing:
            return existing
    pending = (
        select(func.count())
        .select_from(auth_enrollments)
        .where(
            auth_enrollments.c.invite_id == invites.c.id,
            auth_enrollments.c.expires_at > now,
            auth_enrollments.c.consumed_at.is_(None),
        )
        .correlate(invites)
        .scalar_subquery()
    )
    # The conditional write serializes reservations on SQLite before inserting one.
    invite_id = conn.execute(
        update(invites)
        .where(
            invites.c.code == code,
            invites.c.disabled.is_(False),
            or_(
                invites.c.expires_at.is_(None),
                invites.c.expires_at > datetime.fromtimestamp(now, UTC),
            ),
            invites.c.uses_count + pending < invites.c.max_uses,
        )
        .values(uses_count=invites.c.uses_count)
        .returning(invites.c.id)
    ).scalar_one_or_none()
    if invite_id is None:
        raise ValueError("This invite is invalid, expired or already in use")
    request_id = secrets.token_urlsafe(24)
    conn.execute(
        insert(auth_enrollments).values(
            id=request_id, invite_id=invite_id, expires_at=now + LIFETIME
        )
    )
    return (
        conn.execute(
            select(auth_enrollments).where(auth_enrollments.c.id == request_id)
        )
        .mappings()
        .one()
    )


def get_pending(conn, request_id, now=None):
    now = int(time.time()) if now is None else now
    row = (
        conn.execute(
            select(auth_enrollments)
            .join(invites, auth_enrollments.c.invite_id == invites.c.id)
            .where(
                auth_enrollments.c.id == request_id,
                auth_enrollments.c.expires_at > now,
                invites.c.disabled.is_(False),
                or_(
                    invites.c.expires_at.is_(None),
                    invites.c.expires_at > datetime.fromtimestamp(now, UTC),
                ),
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ValueError("This registration has expired; request a new invite link")
    return row


def claim(conn, request_id, subject, username, display_name):
    row = get_pending(conn, request_id)
    if row["subject"] and row["subject"] != subject:
        raise ValueError("This registration is already linked to another account")
    if row["consumed_at"]:
        raise ValueError("This registration is already complete")
    existing_identity = (
        conn.execute(
            select(users)
            .join(external_identities, external_identities.c.user_id == users.c.id)
            .where(
                external_identities.c.issuer == "https://auth.jackharrhy.dev",
                external_identities.c.subject == subject,
            )
        )
        .mappings()
        .first()
    )
    if existing_identity:
        username, display_name = (
            existing_identity["username"],
            existing_identity["display_name"],
        )
    elif not USERNAME_RE.fullmatch(username):
        raise ValueError("Use 3-32 lowercase letters, numbers, underscores or hyphens")
    collision = conn.execute(
        select(users.c.id).where(users.c.username == username)
    ).scalar_one_or_none()
    if collision:
        linked = conn.execute(
            select(external_identities.c.user_id).where(
                external_identities.c.issuer == "https://auth.jackharrhy.dev",
                external_identities.c.subject == subject,
            )
        ).scalar_one_or_none()
        if linked != collision:
            raise ValueError("This username is already used on 4orm")
    result = conn.execute(
        update(auth_enrollments)
        .where(
            auth_enrollments.c.id == request_id,
            or_(
                auth_enrollments.c.subject.is_(None),
                auth_enrollments.c.subject == subject,
            ),
        )
        .values(subject=subject, username=username, display_name=display_name[:80])
    )
    if result.rowcount != 1:
        raise ValueError("This registration is already linked to another account")
    return get_pending(conn, request_id)


def finish(conn, request_id, issuer, subject):
    row = get_pending(conn, request_id)
    if row["subject"] != subject or not row["username"]:
        raise ValueError("This registration belongs to a different identity")
    linked = (
        conn.execute(
            select(users)
            .join(external_identities, external_identities.c.user_id == users.c.id)
            .where(
                external_identities.c.issuer == issuer,
                external_identities.c.subject == subject,
            )
        )
        .mappings()
        .first()
    )
    if row["consumed_at"]:
        if linked and linked["id"] == row["user_id"]:
            return linked
        raise ValueError("This registration is already complete")
    if linked:
        conn.execute(
            update(auth_enrollments)
            .where(auth_enrollments.c.id == request_id)
            .values(user_id=linked["id"], consumed_at=int(time.time()))
        )
        return linked
    invite = conn.execute(
        update(invites)
        .where(
            invites.c.id == row["invite_id"],
            invites.c.disabled.is_(False),
            invites.c.uses_count < invites.c.max_uses,
        )
        .values(uses_count=invites.c.uses_count + 1, used_at=func.now())
        .returning(invites.c.created_by_user_id)
    ).scalar_one_or_none()
    if invite is None:
        raise ValueError("This invite is no longer available")
    uid = conn.execute(
        insert(users).values(
            username=row["username"],
            display_name=row["display_name"],
            password_hash=hash_password(secrets.token_urlsafe(48)),
            invited_by_user_id=invite,
            invite_id=row["invite_id"],
        )
    ).inserted_primary_key[0]
    conn.execute(
        insert(external_identities).values(issuer=issuer, subject=subject, user_id=uid)
    )
    conn.execute(
        insert(profile_cards).values(user_id=uid, headline=f"{row['username']}'s page")
    )
    conn.execute(
        update(invites)
        .where(invites.c.id == row["invite_id"])
        .values(used_by_user_id=uid)
    )
    conn.execute(
        update(auth_enrollments)
        .where(auth_enrollments.c.id == request_id)
        .values(user_id=uid, consumed_at=int(time.time()))
    )
    return conn.execute(select(users).where(users.c.id == uid)).mappings().one()
