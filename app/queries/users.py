import secrets
import time
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import and_, delete, func, insert, select, update
from sqlalchemy.engine import Connection

from app.schema import auth_enrollments, invites, pages, profile_cards, users


class AccountState(StrEnum):
    DISABLED = "disabled"
    AWAITING_TRUST = "awaiting_trust"
    ACTIVE = "active"


def account_state(user) -> AccountState:
    if user["is_disabled"]:
        return AccountState.DISABLED
    return (
        AccountState.ACTIVE
        if user["has_accepted_trust"]
        else AccountState.AWAITING_TRUST
    )


class InviteState(StrEnum):
    DISABLED = "disabled"
    EXPIRED = "expired"
    EXHAUSTED = "exhausted"
    RESERVED = "reserved"
    ACTIVE = "active"


def invite_state(invite, pending=0, now=None) -> InviteState:
    now = datetime.now(UTC) if now is None else now
    if invite["disabled"]:
        return InviteState.DISABLED
    expiration = invite["expires_at"]
    if expiration:
        expiration = (
            expiration.replace(tzinfo=UTC) if expiration.tzinfo is None else expiration
        )
        if expiration <= now:
            return InviteState.EXPIRED
    if invite["uses_count"] >= invite["max_uses"]:
        return InviteState.EXHAUSTED
    if invite["uses_count"] + pending >= invite["max_uses"]:
        return InviteState.RESERVED
    return InviteState.ACTIVE


def pending_reservations(now=None):
    now = int(time.time()) if now is None else now
    return and_(
        auth_enrollments.c.invite_id == invites.c.id,
        auth_enrollments.c.expires_at > now,
        auth_enrollments.c.consumed_at.is_(None),
    )


def get_user_by_username(conn: Connection, username: str):
    return (
        conn.execute(select(users).where(users.c.username == username))
        .mappings()
        .first()
    )


def get_user_by_id(conn: Connection, user_id: int):
    return conn.execute(select(users).where(users.c.id == user_id)).mappings().first()


def create_invite(conn: Connection, creator_user_id: int, max_uses: int = 1) -> str:
    code = secrets.token_urlsafe(12)
    conn.execute(
        insert(invites).values(
            code=code, created_by_user_id=creator_user_id, max_uses=max_uses
        )
    )
    return code


def get_invites_for_user(conn: Connection, user_id: int):
    rows = (
        conn.execute(
            select(
                invites,
                select(func.count())
                .select_from(auth_enrollments)
                .where(pending_reservations())
                .correlate(invites)
                .scalar_subquery()
                .label("pending_reservations"),
            )
            .where(invites.c.created_by_user_id == user_id)
            .order_by(invites.c.created_at.desc())
        )
        .mappings()
        .all()
    )
    result = []
    for inv in rows:
        redeemed_by = (
            conn.execute(
                select(users.c.username, users.c.display_name).where(
                    users.c.invite_id == inv["id"]
                )
            )
            .mappings()
            .all()
        )
        result.append(
            {
                **inv,
                "redeemed_by": list(redeemed_by),
                "status": invite_state(inv, inv["pending_reservations"]),
            }
        )
    return result


def disable_invite(conn: Connection, invite_id: int, user_id: int) -> bool:
    result = conn.execute(
        update(invites)
        .where(
            and_(
                invites.c.id == invite_id,
                invites.c.created_by_user_id == user_id,
            )
        )
        .values(disabled=True)
    )
    return result.rowcount > 0


def delete_invite(conn: Connection, invite_id: int, user_id: int) -> bool:
    """Delete only unused invites without an active enrollment reservation."""
    result = conn.execute(
        delete(invites).where(
            and_(
                invites.c.id == invite_id,
                invites.c.created_by_user_id == user_id,
                invites.c.uses_count == 0,
                ~select(auth_enrollments.c.id).where(pending_reservations()).exists(),
            )
        )
    )
    return result.rowcount > 0


def list_profile_cards(conn: Connection):
    # Subquery: most recent page update per user
    latest_page = (
        select(
            pages.c.user_id,
            func.max(pages.c.updated_at).label("latest_page_at"),
        )
        .group_by(pages.c.user_id)
        .subquery()
    )

    q = (
        select(
            users.c.username,
            profile_cards.c.headline,
            profile_cards.c.content,
            profile_cards.c.content_format,
            profile_cards.c.accent_color,
            profile_cards.c.border_style,
            profile_cards.c.card_css,
        )
        .select_from(
            users.join(profile_cards, users.c.id == profile_cards.c.user_id).outerjoin(
                latest_page, users.c.id == latest_page.c.user_id
            )
        )
        .order_by(
            func.max(
                users.c.updated_at,
                profile_cards.c.updated_at,
                func.coalesce(latest_page.c.latest_page_at, users.c.created_at),
            ).desc()
        )
    )
    return conn.execute(q).mappings().all()


def get_invite_tree(conn: Connection):
    """Build the full invite tree as nested dicts.

    Returns a list of root nodes, each with a "children" list.
    """
    all_users = (
        conn.execute(
            select(
                users.c.id,
                users.c.username,
                users.c.display_name,
                users.c.invited_by_user_id,
            ).order_by(users.c.created_at)
        )
        .mappings()
        .all()
    )

    nodes = {}
    for u in all_users:
        nodes[u["id"]] = {
            "username": u["username"],
            "display_name": u["display_name"],
            "children": [],
        }

    roots = []
    for u in all_users:
        node = nodes[u["id"]]
        parent_id = u["invited_by_user_id"]
        if parent_id and parent_id in nodes:
            nodes[parent_id]["children"].append(node)
        else:
            roots.append(node)

    return roots
