from sqlalchemy import and_, delete, insert, select
from sqlalchemy.engine import Connection

from app.schema import guestbook_entries, users


def list_guestbook_entries(conn: Connection, user_id: int):
    """List all guestbook entries for a user, newest first."""
    q = (
        select(
            guestbook_entries.c.id,
            guestbook_entries.c.message,
            guestbook_entries.c.created_at,
            users.c.username.label("author_username"),
            users.c.display_name.label("author_display_name"),
        )
        .select_from(
            guestbook_entries.join(users, guestbook_entries.c.author_id == users.c.id)
        )
        .where(guestbook_entries.c.user_id == user_id)
        .order_by(guestbook_entries.c.created_at.desc())
    )
    return conn.execute(q).mappings().all()


def create_guestbook_entry(
    conn: Connection, user_id: int, author_id: int, message: str
):
    """Create a new guestbook entry. Message is truncated to 500 chars."""
    conn.execute(
        insert(guestbook_entries).values(
            user_id=user_id,
            author_id=author_id,
            message=message[:500],
        )
    )


def delete_guestbook_entry(conn: Connection, entry_id: int, owner_id: int) -> bool:
    """Delete a guestbook entry. Only the guestbook owner can delete."""
    result = conn.execute(
        delete(guestbook_entries).where(
            and_(
                guestbook_entries.c.id == entry_id,
                guestbook_entries.c.user_id == owner_id,
            )
        )
    )
    return result.rowcount > 0
