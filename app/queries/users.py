import secrets

from sqlalchemy import and_, delete, func, insert, select, update
from sqlalchemy.engine import Connection

from app.schema import invites, pages, profile_cards, users
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
            invite_id=invite["id"],
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
        insert(profile_cards).values(user_id=user_id, headline=f"{username}'s page")
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


def get_invites_for_user(conn: Connection, user_id: int):
    rows = (
        conn.execute(
            select(invites)
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
        exhausted = inv["uses_count"] >= inv["max_uses"]
        if inv["disabled"]:
            status = "disabled"
        elif exhausted:
            status = "exhausted"
        else:
            status = "active"
        result.append(
            {
                **inv,
                "redeemed_by": list(redeemed_by),
                "status": status,
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
    """Delete an invite only if it has never been used."""
    result = conn.execute(
        delete(invites).where(
            and_(
                invites.c.id == invite_id,
                invites.c.created_by_user_id == user_id,
                invites.c.uses_count == 0,
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
