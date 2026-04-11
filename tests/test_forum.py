"""Comprehensive tests for the forum feature (threads, posts, moderation)."""

from sqlalchemy import select, update

from app.schema import forum_posts, forum_threads, users
from tests.conftest import login_as, make_test_user, promote_to_admin


def _create_second_user(test_engine):
    """Create a second user for multi-user tests."""
    with test_engine.begin() as conn:
        uid = make_test_user(conn, "user2", password="pass2")
    return {"id": uid, "username": "user2", "password": "pass2"}


def _promote_to_admin(test_engine, user_id):
    """Make a user an admin."""
    with test_engine.begin() as conn:
        promote_to_admin(conn, user_id)


def _create_thread(
    authed_client, title="Test Thread", content="Thread body", content_format="bbcode"
):
    """Create a thread and return the thread ID from the redirect URL."""
    r = authed_client.post(
        "/forum/new",
        data={"title": title, "content": content, "content_format": content_format},
        follow_redirects=False,
    )
    assert r.status_code == 303
    # Location header looks like /forum/{id}
    location = r.headers["location"]
    thread_id = int(location.rstrip("/").split("/")[-1])
    return thread_id


def _get_thread_reply_count(test_engine, thread_id):
    """Get the reply_count column for a thread."""
    with test_engine.begin() as conn:
        return conn.execute(
            select(forum_threads.c.reply_count).where(forum_threads.c.id == thread_id)
        ).scalar()


def _get_first_post_id(test_engine, thread_id):
    """Get the ID of the first post in a thread."""
    with test_engine.begin() as conn:
        return conn.execute(
            select(forum_posts.c.id)
            .where(forum_posts.c.thread_id == thread_id)
            .order_by(forum_posts.c.created_at.asc())
        ).scalar()


# ---------------------------------------------------------------------------
# Thread CRUD
# ---------------------------------------------------------------------------


def test_forum_index_renders(client, seed_user):
    """1. GET /forum renders without auth."""
    r = client.get("/forum")
    assert r.status_code == 200
    assert "forum" in r.text.lower()


def test_create_thread_requires_login(client):
    """2. GET /forum/new redirects to /login when not authenticated."""
    r = client.get("/forum/new", follow_redirects=False)
    assert r.status_code == 303
    assert "/login" in r.headers["location"]


def test_create_thread(authed_client, test_engine):
    """3. POST /forum/new creates a thread and redirects to it."""
    thread_id = _create_thread(
        authed_client,
        title="My First Thread",
        content="Hello forum!",
        content_format="bbcode",
    )

    # Verify the thread appears in the thread list
    r = authed_client.get("/forum")
    assert r.status_code == 200
    assert "My First Thread" in r.text

    # Verify the thread exists in the database
    with test_engine.begin() as conn:
        thread = (
            conn.execute(select(forum_threads).where(forum_threads.c.id == thread_id))
            .mappings()
            .first()
        )
        assert thread is not None
        assert thread["title"] == "My First Thread"


def test_thread_view_renders(authed_client):
    """4. GET /forum/{id} shows title and first post content."""
    thread_id = _create_thread(authed_client, title="View Me", content="Post body here")

    r = authed_client.get(f"/forum/{thread_id}")
    assert r.status_code == 200
    assert "View Me" in r.text
    assert "Post body here" in r.text


def test_thread_view_rendered_bbcode(authed_client):
    """5. Thread view renders BBCode to HTML."""
    thread_id = _create_thread(
        authed_client, content="[b]bold[/b]", content_format="bbcode"
    )

    r = authed_client.get(f"/forum/{thread_id}")
    assert r.status_code == 200
    assert "<strong>bold</strong>" in r.text


def test_thread_view_rendered_markdown(authed_client):
    """6. Thread view renders Markdown to HTML."""
    thread_id = _create_thread(
        authed_client, content="**bold markdown**", content_format="markdown"
    )

    r = authed_client.get(f"/forum/{thread_id}")
    assert r.status_code == 200
    assert "<strong>bold markdown</strong>" in r.text


def test_edit_thread_meta_author(authed_client):
    """7. Author can edit their thread's title."""
    thread_id = _create_thread(authed_client, title="Original Title")

    r = authed_client.post(
        f"/forum/{thread_id}/edit",
        data={"title": "Updated Title", "custom_css": "", "custom_html": ""},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "Updated Title" in r.text


def test_edit_thread_non_author_rejected(client, test_engine, seed_user):
    """8. Non-author cannot edit a thread."""
    # Log in as seed_user and create a thread
    login_as(client, seed_user["username"], seed_user["password"])
    thread_id = _create_thread(client, title="Owner's Thread")

    # Create second user and log in as them
    user2 = _create_second_user(test_engine)
    login_as(client, user2["username"], user2["password"])

    r = client.post(
        f"/forum/{thread_id}/edit",
        data={"title": "Hacked Title", "custom_css": "", "custom_html": ""},
    )
    assert r.status_code == 403


def test_delete_thread_author(authed_client, test_engine):
    """9. Author can delete their own thread."""
    thread_id = _create_thread(authed_client, title="Delete Me")

    r = authed_client.post(f"/forum/{thread_id}/delete", follow_redirects=False)
    assert r.status_code == 303
    assert "/forum" in r.headers["location"]

    # Verify thread is gone
    with test_engine.begin() as conn:
        thread = conn.execute(
            select(forum_threads).where(forum_threads.c.id == thread_id)
        ).first()
        assert thread is None


def test_delete_thread_admin(client, test_engine, seed_user):
    """10. Admin can delete anyone's thread."""
    # Create a thread as seed_user
    login_as(client, seed_user["username"], seed_user["password"])
    thread_id = _create_thread(client, title="User Thread")

    # Create admin user
    user2 = _create_second_user(test_engine)
    _promote_to_admin(test_engine, user2["id"])
    login_as(client, user2["username"], user2["password"])

    r = client.post(f"/forum/{thread_id}/delete", follow_redirects=False)
    assert r.status_code == 303

    # Verify thread is gone
    with test_engine.begin() as conn:
        thread = conn.execute(
            select(forum_threads).where(forum_threads.c.id == thread_id)
        ).first()
        assert thread is None


# ---------------------------------------------------------------------------
# Post / Reply CRUD
# ---------------------------------------------------------------------------


def test_reply_to_thread(authed_client, test_engine):
    """11. Reply to a thread increments reply_count."""
    thread_id = _create_thread(authed_client)

    assert _get_thread_reply_count(test_engine, thread_id) == 0

    r = authed_client.post(
        f"/forum/{thread_id}/reply",
        data={"content": "A reply!", "content_format": "bbcode"},
        follow_redirects=False,
    )
    assert r.status_code == 303

    assert _get_thread_reply_count(test_engine, thread_id) == 1


def test_reply_with_quote(authed_client):
    """12. Reply with quoted content renders the quote."""
    thread_id = _create_thread(authed_client, content="Original post content")

    authed_client.post(
        f"/forum/{thread_id}/reply",
        data={
            "content": "I agree!",
            "content_format": "bbcode",
            "quoted_post_id": "1",
            "quoted_content": "Original post content",
            "quoted_author": "testuser",
        },
        follow_redirects=False,
    )

    r = authed_client.get(f"/forum/{thread_id}", follow_redirects=True)
    assert r.status_code == 200
    assert "Original post content" in r.text
    assert "testuser" in r.text


def test_reply_to_locked_thread_fails(client, test_engine, seed_user):
    """13. Replying to a locked thread returns 403."""
    login_as(client, seed_user["username"], seed_user["password"])
    thread_id = _create_thread(client)

    # Lock the thread via admin
    _promote_to_admin(test_engine, seed_user["id"])
    client.post(f"/forum/{thread_id}/lock")

    # Attempt to reply
    r = client.post(
        f"/forum/{thread_id}/reply",
        data={"content": "Can't post here", "content_format": "bbcode"},
    )
    assert r.status_code == 403


def test_edit_own_post(authed_client, test_engine):
    """14. Edit own post updates content and sets is_edited flag."""
    thread_id = _create_thread(authed_client, content="Before edit")
    post_id = _get_first_post_id(test_engine, thread_id)

    r = authed_client.post(
        f"/forum/posts/{post_id}/edit",
        data={"content": "After edit", "content_format": "bbcode"},
        follow_redirects=False,
    )
    assert r.status_code == 303

    # Verify is_edited is set
    with test_engine.begin() as conn:
        post = (
            conn.execute(select(forum_posts).where(forum_posts.c.id == post_id))
            .mappings()
            .first()
        )
        assert post["is_edited"] is True
        assert post["content"] == "After edit"


def test_edit_post_non_author_rejected(client, test_engine, seed_user):
    """15. Non-author cannot edit someone else's post."""
    login_as(client, seed_user["username"], seed_user["password"])
    thread_id = _create_thread(client, content="My post")
    post_id = _get_first_post_id(test_engine, thread_id)

    # Switch to second user
    user2 = _create_second_user(test_engine)
    login_as(client, user2["username"], user2["password"])

    r = client.post(
        f"/forum/posts/{post_id}/edit",
        data={"content": "Hacked content", "content_format": "bbcode"},
    )
    assert r.status_code == 403


def test_delete_own_post(authed_client, test_engine):
    """16. Author can delete their own reply post."""
    thread_id = _create_thread(authed_client)

    # Add a reply so we have a non-first post to delete
    authed_client.post(
        f"/forum/{thread_id}/reply",
        data={"content": "Reply to delete", "content_format": "bbcode"},
    )

    # Get the reply's post ID (second post)
    with test_engine.begin() as conn:
        posts = conn.execute(
            select(forum_posts.c.id)
            .where(forum_posts.c.thread_id == thread_id)
            .order_by(forum_posts.c.created_at.asc())
        ).fetchall()
    reply_post_id = posts[1][0]

    r = authed_client.post(
        f"/forum/posts/{reply_post_id}/delete",
        follow_redirects=False,
    )
    assert r.status_code == 303

    # Verify it's gone
    with test_engine.begin() as conn:
        post = conn.execute(
            select(forum_posts).where(forum_posts.c.id == reply_post_id)
        ).first()
        assert post is None


def test_admin_can_delete_any_post(client, test_engine, seed_user):
    """17. Admin can delete any user's post."""
    login_as(client, seed_user["username"], seed_user["password"])
    thread_id = _create_thread(client, content="User post")

    # Add a reply from seed_user
    client.post(
        f"/forum/{thread_id}/reply",
        data={"content": "Reply by user", "content_format": "bbcode"},
    )

    with test_engine.begin() as conn:
        posts = conn.execute(
            select(forum_posts.c.id)
            .where(forum_posts.c.thread_id == thread_id)
            .order_by(forum_posts.c.created_at.asc())
        ).fetchall()
    reply_post_id = posts[1][0]

    # Create admin user and delete the post
    user2 = _create_second_user(test_engine)
    _promote_to_admin(test_engine, user2["id"])
    login_as(client, user2["username"], user2["password"])

    r = client.post(f"/forum/posts/{reply_post_id}/delete", follow_redirects=False)
    assert r.status_code == 303

    with test_engine.begin() as conn:
        post = conn.execute(
            select(forum_posts).where(forum_posts.c.id == reply_post_id)
        ).first()
        assert post is None


# ---------------------------------------------------------------------------
# Forum rendering / sanitization
# ---------------------------------------------------------------------------


def test_bbcode_sanitization(authed_client):
    """18. BBCode does not allow script injection."""
    thread_id = _create_thread(
        authed_client,
        content='[b]bold[/b]<script>alert("xss")</script>',
        content_format="bbcode",
    )

    r = authed_client.get(f"/forum/{thread_id}")
    assert r.status_code == 200
    # BBCode parser escapes HTML — script tag should be entity-encoded
    assert '<script>alert("xss")</script>' not in r.text
    assert "&lt;script&gt;" in r.text
    assert "<strong>bold</strong>" in r.text


def test_markdown_sanitized(authed_client):
    """19. Markdown with <script> tag has it stripped by bleach."""
    thread_id = _create_thread(
        authed_client,
        content='**safe** <script>alert("xss")</script>',
        content_format="markdown",
    )

    r = authed_client.get(f"/forum/{thread_id}")
    assert r.status_code == 200
    # Bleach strips <script> tags — the literal injection should not appear
    assert '<script>alert("xss")</script>' not in r.text
    assert "<strong>safe</strong>" in r.text


def test_signature_renders(client, test_engine, seed_user):
    """20. User's forum_signature renders in posts."""
    with test_engine.begin() as conn:
        conn.execute(
            update(users)
            .where(users.c.id == seed_user["id"])
            .values(forum_signature="[i]my sig[/i]")
        )

    login_as(client, seed_user["username"], seed_user["password"])
    thread_id = _create_thread(client, content="Post with signature")

    r = client.get(f"/forum/{thread_id}")
    assert r.status_code == 200
    assert "<em>my sig</em>" in r.text


# ---------------------------------------------------------------------------
# Admin moderation
# ---------------------------------------------------------------------------


def test_pin_thread(client, test_engine, seed_user):
    """21. Admin can pin a thread (toggles is_pinned)."""
    login_as(client, seed_user["username"], seed_user["password"])
    thread_id = _create_thread(client)

    _promote_to_admin(test_engine, seed_user["id"])

    # Pin
    r = client.post(f"/forum/{thread_id}/pin", follow_redirects=False)
    assert r.status_code == 303
    with test_engine.begin() as conn:
        pinned = conn.execute(
            select(forum_threads.c.is_pinned).where(forum_threads.c.id == thread_id)
        ).scalar()
    assert pinned is True

    # Unpin (toggle)
    client.post(f"/forum/{thread_id}/pin")
    with test_engine.begin() as conn:
        pinned = conn.execute(
            select(forum_threads.c.is_pinned).where(forum_threads.c.id == thread_id)
        ).scalar()
    assert pinned is False


def test_lock_thread(client, test_engine, seed_user):
    """22. Admin can lock a thread (toggles is_locked)."""
    login_as(client, seed_user["username"], seed_user["password"])
    thread_id = _create_thread(client)

    _promote_to_admin(test_engine, seed_user["id"])

    # Lock
    r = client.post(f"/forum/{thread_id}/lock", follow_redirects=False)
    assert r.status_code == 303
    with test_engine.begin() as conn:
        locked = conn.execute(
            select(forum_threads.c.is_locked).where(forum_threads.c.id == thread_id)
        ).scalar()
    assert locked is True

    # Unlock (toggle)
    client.post(f"/forum/{thread_id}/lock")
    with test_engine.begin() as conn:
        locked = conn.execute(
            select(forum_threads.c.is_locked).where(forum_threads.c.id == thread_id)
        ).scalar()
    assert locked is False


def test_non_admin_cannot_pin_or_lock(authed_client):
    """23. Non-admin gets 403 when trying to pin or lock."""
    thread_id = _create_thread(authed_client)

    r = authed_client.post(f"/forum/{thread_id}/pin")
    assert r.status_code == 403

    r = authed_client.post(f"/forum/{thread_id}/lock")
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def test_thread_list_pagination(authed_client, test_engine):
    """24. Thread list paginated at 25 per page."""
    # Create 30 threads
    for i in range(30):
        _create_thread(authed_client, title=f"Thread {i:03d}")

    # Page 1 should have 25 threads
    r = authed_client.get("/forum?page=1")
    assert r.status_code == 200
    # Count how many of our threads appear on page 1
    page1_count = sum(1 for i in range(30) if f"Thread {i:03d}" in r.text)
    assert page1_count == 25

    # Page 2 should have the remaining 5
    r = authed_client.get("/forum?page=2")
    assert r.status_code == 200
    page2_count = sum(1 for i in range(30) if f"Thread {i:03d}" in r.text)
    assert page2_count == 5
