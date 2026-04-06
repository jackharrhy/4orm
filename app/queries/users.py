import secrets

from sqlalchemy import and_, func, insert, select, update
from sqlalchemy.engine import Connection

from app.schema import inventory_cards, invites, users
from app.security import hash_password


def get_user_by_username(conn: Connection, username: str):
    return (
        conn.execute(select(users).where(users.c.username == username))
        .mappings()
        .first()
    )


def get_user_by_id(conn: Connection, user_id: int):
    return conn.execute(select(users).where(users.c.id == user_id)).mappings().first()


def create_user_with_invite(
    conn: Connection, *, username: str, password: str, invite_code: str
):
    invite = (
        conn.execute(
            select(invites).where(
                and_(
                    invites.c.code == invite_code,
                    invites.c.disabled.is_(False),
                    invites.c.uses_count < invites.c.max_uses,
                )
            )
        )
        .mappings()
        .first()
    )

    if not invite:
        return None, "Invalid or exhausted invite code"

    if get_user_by_username(conn, username):
        return None, "Username already exists"

    result = conn.execute(
        insert(users).values(
            username=username,
            password_hash=hash_password(password),
            display_name=username,
            invited_by_user_id=invite["created_by_user_id"],
        )
    )
    user_id = result.inserted_primary_key[0]

    conn.execute(
        update(invites)
        .where(invites.c.id == invite["id"])
        .values(
            uses_count=invites.c.uses_count + 1,
            used_by_user_id=user_id,
            used_at=func.now(),
        )
    )

    conn.execute(
        insert(inventory_cards).values(user_id=user_id, headline=f"{username}'s card")
    )
    return get_user_by_id(conn, user_id), None


def create_invite(conn: Connection, creator_user_id: int, max_uses: int = 1) -> str:
    code = secrets.token_urlsafe(12)
    conn.execute(
        insert(invites).values(
            code=code, created_by_user_id=creator_user_id, max_uses=max_uses
        )
    )
    return code


def list_inventory_cards(conn: Connection):
    q = (
        select(
            users.c.username,
            users.c.display_name,
            users.c.bio,
            inventory_cards.c.headline,
            inventory_cards.c.subhead,
            inventory_cards.c.accent_color,
            inventory_cards.c.border_style,
            inventory_cards.c.card_css,
        )
        .select_from(
            users.join(inventory_cards, users.c.id == inventory_cards.c.user_id)
        )
        .order_by(users.c.created_at.desc())
    )
    return conn.execute(q).mappings().all()


def lineage_for_user(conn: Connection, username: str):
    user = get_user_by_username(conn, username)
    if not user:
        return []

    chain = [user]
    current = user
    while current["invited_by_user_id"]:
        parent = get_user_by_id(conn, current["invited_by_user_id"])
        if not parent:
            break
        chain.append(parent)
        current = parent

    chain.reverse()
    return chain
