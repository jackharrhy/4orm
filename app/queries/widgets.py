from sqlalchemy import and_, delete, func, insert, select, update
from sqlalchemy.engine import Connection

from app.schema import media, playlist_items, users

# --- Webring ---


def get_webring_members(conn: Connection):
    """Get all webring members ordered by created_at."""
    return (
        conn.execute(
            select(users.c.id, users.c.username, users.c.display_name)
            .where(users.c.in_webring == True, users.c.is_disabled == False)
            .order_by(users.c.created_at)
        )
        .mappings()
        .all()
    )


def get_webring_neighbors(conn: Connection, username: str):
    """Get prev and next webring members for a given user. Returns (prev, next)."""
    members = get_webring_members(conn)
    if not members:
        return None, None

    usernames = [m["username"] for m in members]
    if username not in usernames:
        return None, None

    idx = usernames.index(username)
    prev_member = members[(idx - 1) % len(members)]
    next_member = members[(idx + 1) % len(members)]
    return prev_member, next_member


# --- Playlist ---


def get_playlist(conn: Connection, user_id: int):
    """Get a user's playlist items with media info, ordered by position."""
    return (
        conn.execute(
            select(
                playlist_items.c.id,
                playlist_items.c.position,
                playlist_items.c.title,
                media.c.storage_path,
                media.c.mime_type,
            )
            .select_from(
                playlist_items.join(media, playlist_items.c.media_id == media.c.id)
            )
            .where(playlist_items.c.user_id == user_id)
            .order_by(playlist_items.c.position)
        )
        .mappings()
        .all()
    )


def add_to_playlist(conn: Connection, user_id: int, media_id: int, title: str = None):
    """Add a track to the end of the playlist."""
    max_pos = conn.execute(
        select(func.coalesce(func.max(playlist_items.c.position), -1)).where(
            playlist_items.c.user_id == user_id
        )
    ).scalar()
    conn.execute(
        insert(playlist_items).values(
            user_id=user_id,
            media_id=media_id,
            position=max_pos + 1,
            title=title,
        )
    )


def remove_from_playlist(conn: Connection, item_id: int, user_id: int):
    """Remove a track from the playlist."""
    conn.execute(
        delete(playlist_items).where(
            and_(playlist_items.c.id == item_id, playlist_items.c.user_id == user_id)
        )
    )


def move_playlist_item(conn: Connection, item_id: int, user_id: int, direction: str):
    """Move a playlist item up or down by swapping positions."""
    items = conn.execute(
        select(playlist_items.c.id, playlist_items.c.position)
        .where(playlist_items.c.user_id == user_id)
        .order_by(playlist_items.c.position)
    ).fetchall()

    ids = [i[0] for i in items]
    if item_id not in ids:
        return

    idx = ids.index(item_id)
    if direction == "up" and idx > 0:
        swap_idx = idx - 1
    elif direction == "down" and idx < len(ids) - 1:
        swap_idx = idx + 1
    else:
        return

    pos_a = items[idx][1]
    pos_b = items[swap_idx][1]
    conn.execute(
        update(playlist_items)
        .where(playlist_items.c.id == item_id)
        .values(position=pos_b)
    )
    conn.execute(
        update(playlist_items)
        .where(playlist_items.c.id == ids[swap_idx])
        .values(position=pos_a)
    )
