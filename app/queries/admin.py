from pathlib import Path

from sqlalchemy import delete, select, update
from sqlalchemy.engine import Connection

from app.schema import media, users


def _get_descendant_ids(conn: Connection, user_id: int) -> list[int]:
    """Recursively get all user IDs invited by this user (the full subtree)."""
    ids = []
    queue = [user_id]
    while queue:
        current = queue.pop()
        children = (
            conn.execute(
                select(users.c.id).where(users.c.invited_by_user_id == current)
            )
            .scalars()
            .all()
        )
        for child_id in children:
            if child_id not in ids:
                ids.append(child_id)
                queue.append(child_id)
    return ids


def _cleanup_user_files(conn: Connection, user_id: int, uploads_dir: Path):
    """Delete all media files on disk for a user."""
    paths = (
        conn.execute(select(media.c.storage_path).where(media.c.user_id == user_id))
        .scalars()
        .all()
    )
    for path in paths:
        disk_path = uploads_dir / path
        if disk_path.exists():
            disk_path.unlink()
    # Clean up empty user directory
    user_dir = uploads_dir / str(
        conn.execute(select(users.c.username).where(users.c.id == user_id)).scalar()
    )
    if user_dir.exists() and not any(user_dir.iterdir()):
        user_dir.rmdir()


def delete_user_reparent(conn: Connection, user_id: int, uploads_dir: Path):
    """Delete a user and reparent their invitees to the user's inviter."""
    user = conn.execute(
        select(users.c.id, users.c.invited_by_user_id).where(users.c.id == user_id)
    ).first()
    if not user:
        return False

    parent_id = user.invited_by_user_id

    # Reparent children to the deleted user's parent
    conn.execute(
        update(users)
        .where(users.c.invited_by_user_id == user_id)
        .values(invited_by_user_id=parent_id)
    )

    # Clean up files
    _cleanup_user_files(conn, user_id, uploads_dir)

    # Delete user (CASCADE handles pages, media rows, guestbook, profile_cards, invites)
    conn.execute(delete(users).where(users.c.id == user_id))
    return True


def delete_user_prune(conn: Connection, user_id: int, uploads_dir: Path) -> int:
    """Delete a user and all users they invited (recursively). Returns count deleted."""
    descendant_ids = _get_descendant_ids(conn, user_id)
    all_ids = [user_id] + descendant_ids

    # Clean up files for all users in the subtree
    for uid in all_ids:
        _cleanup_user_files(conn, uid, uploads_dir)

    # Delete from leaves up to avoid FK issues (children before parents)
    for uid in reversed(all_ids):
        conn.execute(delete(users).where(users.c.id == uid))

    return len(all_ids)
