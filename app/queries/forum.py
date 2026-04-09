from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, delete, func, insert, select, update
from sqlalchemy.engine import Connection

from app.schema import forum_posts, forum_threads, thread_watchers, users


def recent_forum_posts(conn: Connection, hours: int = 2, limit: int = 5):
    """Get recent forum posts from the last N hours, newest first."""
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    q = (
        select(
            forum_posts.c.id,
            forum_posts.c.thread_id,
            forum_posts.c.content,
            forum_posts.c.content_format,
            forum_posts.c.created_at,
            forum_threads.c.title.label("thread_title"),
            users.c.username.label("author_username"),
            users.c.display_name.label("author_display_name"),
        )
        .select_from(
            forum_posts.join(users, forum_posts.c.author_id == users.c.id).join(
                forum_threads, forum_posts.c.thread_id == forum_threads.c.id
            )
        )
        .where(forum_posts.c.created_at >= cutoff)
        .order_by(forum_posts.c.created_at.desc())
        .limit(limit)
    )
    return conn.execute(q).mappings().all()


def recent_forum_posts_for_rss(conn: Connection, limit: int = 100):
    """Get recent forum posts for the RSS feed, newest first."""
    q = (
        select(
            forum_posts.c.id,
            forum_posts.c.thread_id,
            forum_posts.c.created_at,
            forum_threads.c.title.label("thread_title"),
            users.c.username.label("author_username"),
            users.c.display_name.label("author_display_name"),
        )
        .select_from(
            forum_posts.join(users, forum_posts.c.author_id == users.c.id).join(
                forum_threads, forum_posts.c.thread_id == forum_threads.c.id
            )
        )
        .order_by(forum_posts.c.created_at.desc())
        .limit(limit)
    )
    return conn.execute(q).mappings().all()


def list_threads(conn: Connection, page: int = 1, per_page: int = 25):
    """List threads: pinned first, then by last_reply_at. Returns (threads, total)."""
    total = conn.execute(select(func.count(forum_threads.c.id))).scalar()
    q = (
        select(
            forum_threads,
            users.c.username.label("author_username"),
            users.c.display_name.label("author_display_name"),
        )
        .select_from(forum_threads.join(users, forum_threads.c.author_id == users.c.id))
        .order_by(
            forum_threads.c.is_pinned.desc(), forum_threads.c.last_reply_at.desc()
        )
        .limit(per_page)
        .offset((page - 1) * per_page)
    )
    threads = conn.execute(q).mappings().all()
    return threads, total


def get_thread(conn: Connection, thread_id: int):
    q = (
        select(
            forum_threads,
            users.c.username.label("author_username"),
            users.c.display_name.label("author_display_name"),
        )
        .select_from(forum_threads.join(users, forum_threads.c.author_id == users.c.id))
        .where(forum_threads.c.id == thread_id)
    )
    return conn.execute(q).mappings().first()


def list_posts(conn: Connection, thread_id: int, page: int = 1, per_page: int = 50):
    """List posts for a thread, oldest first. Returns (posts, total)."""
    total = conn.execute(
        select(func.count(forum_posts.c.id)).where(forum_posts.c.thread_id == thread_id)
    ).scalar()
    q = (
        select(
            forum_posts,
            users.c.username.label("author_username"),
            users.c.display_name.label("author_display_name"),
            users.c.forum_signature.label("author_signature"),
        )
        .select_from(forum_posts.join(users, forum_posts.c.author_id == users.c.id))
        .where(forum_posts.c.thread_id == thread_id)
        .order_by(forum_posts.c.created_at.asc())
        .limit(per_page)
        .offset((page - 1) * per_page)
    )
    posts = conn.execute(q).mappings().all()
    return posts, total


def get_post(conn: Connection, post_id: int):
    """Get a single post with author info."""
    q = (
        select(
            forum_posts,
            users.c.username.label("author_username"),
            users.c.display_name.label("author_display_name"),
        )
        .select_from(forum_posts.join(users, forum_posts.c.author_id == users.c.id))
        .where(forum_posts.c.id == post_id)
    )
    return conn.execute(q).mappings().first()


def create_thread(
    conn: Connection,
    author_id: int,
    title: str,
    content: str,
    content_format: str = "bbcode",
    custom_css: str = "",
    custom_html: str = "",
) -> int:
    """Create a thread and its first post. Returns the thread ID."""
    result = conn.execute(
        insert(forum_threads).values(
            author_id=author_id,
            title=title,
            custom_css=custom_css,
            custom_html=custom_html,
            last_reply_by_id=author_id,
        )
    )
    thread_id = result.inserted_primary_key[0]
    conn.execute(
        insert(forum_posts).values(
            thread_id=thread_id,
            author_id=author_id,
            content=content,
            content_format=content_format,
        )
    )
    watch_thread(conn, author_id, thread_id)
    return thread_id


def create_reply(
    conn: Connection,
    thread_id: int,
    author_id: int,
    content: str,
    content_format: str = "bbcode",
    quoted_post_id: int | None = None,
    quoted_content: str | None = None,
    quoted_content_format: str | None = None,
    quoted_author: str | None = None,
) -> int:
    """Create a reply and bump the thread. Returns the post ID."""
    result = conn.execute(
        insert(forum_posts).values(
            thread_id=thread_id,
            author_id=author_id,
            content=content,
            content_format=content_format,
            quoted_post_id=quoted_post_id,
            quoted_content=quoted_content,
            quoted_content_format=quoted_content_format,
            quoted_author=quoted_author,
        )
    )
    post_id = result.inserted_primary_key[0]
    conn.execute(
        update(forum_threads)
        .where(forum_threads.c.id == thread_id)
        .values(
            reply_count=forum_threads.c.reply_count + 1,
            last_reply_at=func.now(),
            last_reply_by_id=author_id,
        )
    )
    return post_id


def update_post(
    conn: Connection,
    post_id: int,
    author_id: int,
    content: str,
    content_format: str,
    is_admin: bool = False,
):
    """Update a post's content (author or admin)."""
    conditions = [forum_posts.c.id == post_id]
    if not is_admin:
        conditions.append(forum_posts.c.author_id == author_id)
    conn.execute(
        update(forum_posts)
        .where(and_(*conditions))
        .values(
            content=content,
            content_format=content_format,
            is_edited=True,
            updated_at=func.now(),
        )
    )


def delete_post_safe(
    conn: Connection, post_id: int, user_id: int, is_admin: bool = False
) -> bool:
    """Delete a post and update the thread's reply count. Author or admin can delete."""
    post = conn.execute(
        select(forum_posts.c.thread_id, forum_posts.c.author_id).where(
            forum_posts.c.id == post_id
        )
    ).first()
    if not post:
        return False
    if not is_admin and post.author_id != user_id:
        return False
    conn.execute(delete(forum_posts).where(forum_posts.c.id == post_id))
    conn.execute(
        update(forum_threads)
        .where(forum_threads.c.id == post.thread_id)
        .values(reply_count=forum_threads.c.reply_count - 1)
    )
    return True


def delete_thread(
    conn: Connection, thread_id: int, user_id: int, is_admin: bool = False
) -> bool:
    """Delete a thread and all its posts. Author or admin."""
    thread = conn.execute(
        select(forum_threads.c.author_id).where(forum_threads.c.id == thread_id)
    ).first()
    if not thread:
        return False
    if not is_admin and thread.author_id != user_id:
        return False
    conn.execute(delete(forum_threads).where(forum_threads.c.id == thread_id))
    return True


def update_thread_meta(
    conn: Connection,
    thread_id: int,
    author_id: int,
    title: str,
    custom_css: str,
    custom_html: str,
    is_admin: bool = False,
):
    """Update thread title/css/html (author or admin)."""
    conditions = [forum_threads.c.id == thread_id]
    if not is_admin:
        conditions.append(forum_threads.c.author_id == author_id)
    conn.execute(
        update(forum_threads)
        .where(and_(*conditions))
        .values(title=title, custom_css=custom_css, custom_html=custom_html)
    )


def toggle_pin(conn: Connection, thread_id: int):
    """Toggle pin status (caller must verify admin)."""
    thread = conn.execute(
        select(forum_threads.c.is_pinned).where(forum_threads.c.id == thread_id)
    ).scalar()
    if thread is None:
        return
    conn.execute(
        update(forum_threads)
        .where(forum_threads.c.id == thread_id)
        .values(is_pinned=not thread)
    )


def toggle_lock(conn: Connection, thread_id: int):
    """Toggle lock status (caller must verify admin)."""
    thread = conn.execute(
        select(forum_threads.c.is_locked).where(forum_threads.c.id == thread_id)
    ).scalar()
    if thread is None:
        return
    conn.execute(
        update(forum_threads)
        .where(forum_threads.c.id == thread_id)
        .values(is_locked=not thread)
    )


def is_watching(conn: Connection, user_id: int, thread_id: int) -> bool:
    return (
        conn.execute(
            select(thread_watchers.c.id).where(
                thread_watchers.c.user_id == user_id,
                thread_watchers.c.thread_id == thread_id,
            )
        ).first()
        is not None
    )


def watch_thread(conn: Connection, user_id: int, thread_id: int):
    """Add a watch. Ignores if already watching."""
    if not is_watching(conn, user_id, thread_id):
        conn.execute(
            insert(thread_watchers).values(user_id=user_id, thread_id=thread_id)
        )


def unwatch_thread(conn: Connection, user_id: int, thread_id: int):
    conn.execute(
        delete(thread_watchers).where(
            thread_watchers.c.user_id == user_id,
            thread_watchers.c.thread_id == thread_id,
        )
    )


def get_watchers(conn: Connection, thread_id: int) -> list[int]:
    """Get all user IDs watching a thread (explicit watchers + watch_all_threads users)."""
    explicit = set(
        row[0]
        for row in conn.execute(
            select(thread_watchers.c.user_id).where(
                thread_watchers.c.thread_id == thread_id
            )
        ).fetchall()
    )
    watch_all = set(
        row[0]
        for row in conn.execute(
            select(users.c.id).where(users.c.watch_all_threads == True)
        ).fetchall()
    )
    return list(explicit | watch_all)
