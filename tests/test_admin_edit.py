"""Tests that admin edits and renames don't nuke user data."""

from sqlalchemy import insert, select, update

from app.schema import pages, profile_cards, users
from app.security import hash_password


def _make_user(conn, username, invited_by=None):
    result = conn.execute(
        insert(users).values(
            username=username,
            password_hash=hash_password("pass"),
            display_name=username,
            invited_by_user_id=invited_by,
        )
    )
    uid = result.inserted_primary_key[0]
    conn.execute(
        insert(profile_cards).values(user_id=uid, headline=f"{username}'s page")
    )
    return uid


def _make_admin(conn, username):
    uid = _make_user(conn, username)
    conn.execute(update(users).where(users.c.id == uid).values(is_admin=True))
    return uid


def _login(client, username):
    client.post("/login", data={"username": username, "password": "pass"})


def _setup_user_with_data(conn, username, admin_id):
    """Create a user with CSS, HTML, layout, pages, and card styling."""
    uid = _make_user(conn, username, invited_by=admin_id)
    conn.execute(
        update(users)
        .where(users.c.id == uid)
        .values(
            custom_css="body { background: pink; }",
            custom_html='<script>console.log("hi")</script>',
            layout="simple",
            guestbook_css=".gb-entry { color: red; }",
            guestbook_html="<p>custom gb</p>",
            content="<h1>my profile</h1>",
            content_format="html",
        )
    )
    conn.execute(
        update(profile_cards)
        .where(profile_cards.c.user_id == uid)
        .values(
            headline="cool card",
            content="<p>card body</p>",
            content_format="html",
            accent_color="#ff0000",
            border_style="dashed",
            card_css="h2 { color: blue; }",
        )
    )
    conn.execute(
        insert(pages).values(
            user_id=uid,
            slug="mypage",
            title="My Page",
            content="<p>page content</p>",
            content_format="html",
            layout="raw",
        )
    )
    return uid


# --- Admin rename preserves data ---


def test_admin_rename_preserves_css(client, test_engine):
    with test_engine.begin() as conn:
        admin_id = _make_admin(conn, "admin")
        uid = _setup_user_with_data(conn, "target", admin_id)

    _login(client, "admin")
    client.post(
        f"/admin/users/{uid}/rename",
        data={"new_username": "renamed", "new_display_name": "Renamed"},
    )

    with test_engine.begin() as conn:
        u = conn.execute(
            select(
                users.c.custom_css,
                users.c.custom_html,
                users.c.layout,
                users.c.guestbook_css,
                users.c.guestbook_html,
                users.c.content,
                users.c.content_format,
            ).where(users.c.id == uid)
        ).first()
        assert u.custom_css == "body { background: pink; }"
        assert u.custom_html == '<script>console.log("hi")</script>'
        assert u.layout == "simple"
        assert u.guestbook_css == ".gb-entry { color: red; }"
        assert u.guestbook_html == "<p>custom gb</p>"
        assert u.content == "<h1>my profile</h1>"
        assert u.content_format == "html"


def test_admin_rename_preserves_card(client, test_engine):
    with test_engine.begin() as conn:
        admin_id = _make_admin(conn, "admin")
        uid = _setup_user_with_data(conn, "target", admin_id)

    _login(client, "admin")
    client.post(
        f"/admin/users/{uid}/rename",
        data={"new_username": "renamed", "new_display_name": "Renamed"},
    )

    with test_engine.begin() as conn:
        card = conn.execute(
            select(
                profile_cards.c.headline,
                profile_cards.c.content,
                profile_cards.c.accent_color,
                profile_cards.c.border_style,
                profile_cards.c.card_css,
            ).where(profile_cards.c.user_id == uid)
        ).first()
        assert card.headline == "cool card"
        assert card.content == "<p>card body</p>"
        assert card.accent_color == "#ff0000"
        assert card.border_style == "dashed"
        assert card.card_css == "h2 { color: blue; }"


def test_admin_rename_preserves_pages(client, test_engine):
    with test_engine.begin() as conn:
        admin_id = _make_admin(conn, "admin")
        uid = _setup_user_with_data(conn, "target", admin_id)

    _login(client, "admin")
    client.post(
        f"/admin/users/{uid}/rename",
        data={"new_username": "renamed", "new_display_name": "Renamed"},
    )

    with test_engine.begin() as conn:
        page = conn.execute(
            select(
                pages.c.slug,
                pages.c.title,
                pages.c.content,
                pages.c.layout,
            ).where(pages.c.user_id == uid)
        ).first()
        assert page.slug == "mypage"
        assert page.title == "My Page"
        assert page.content == "<p>page content</p>"
        assert page.layout == "raw"


# --- Admin profile edit preserves unedited fields ---


def test_admin_profile_edit_preserves_all_fields(client, test_engine):
    """Admin profile edit preserves all fields (custom_html, layout)."""
    with test_engine.begin() as conn:
        admin_id = _make_admin(conn, "admin")
        uid = _setup_user_with_data(conn, "target", admin_id)

    _login(client, "admin")
    client.post(
        f"/admin/users/{uid}/profile",
        data={
            "display_name": "New Display",
            "content": "new content",
            "content_format": "html",
            "custom_css": "body { color: green; }",
            "custom_html": '<script>console.log("hi")</script>',
            "layout": "simple",
        },
    )

    with test_engine.begin() as conn:
        u = conn.execute(
            select(
                users.c.display_name,
                users.c.content,
                users.c.custom_css,
                users.c.custom_html,
                users.c.layout,
                users.c.guestbook_css,
                users.c.guestbook_html,
            ).where(users.c.id == uid)
        ).first()
        assert u.display_name == "New Display"
        assert u.content == "new content"
        assert u.custom_css == "body { color: green; }"
        assert u.custom_html == '<script>console.log("hi")</script>'
        assert u.layout == "simple"
        # Guestbook settings are on a different form, should be untouched
        assert u.guestbook_css == ".gb-entry { color: red; }"
        assert u.guestbook_html == "<p>custom gb</p>"


# --- Admin card edit preserves unedited fields ---


def test_admin_card_edit_preserves_card_data(client, test_engine):
    """Editing a card via admin should update only the submitted fields."""
    with test_engine.begin() as conn:
        admin_id = _make_admin(conn, "admin")
        uid = _setup_user_with_data(conn, "target", admin_id)

    _login(client, "admin")
    client.post(
        f"/admin/users/{uid}/card",
        data={
            "headline": "new headline",
            "content": "new card content",
            "content_format": "html",
            "accent_color": "#00ff00",
            "border_style": "solid",
            "card_css": "h2 { color: red; }",
        },
    )

    with test_engine.begin() as conn:
        card = conn.execute(
            select(
                profile_cards.c.headline,
                profile_cards.c.content,
                profile_cards.c.accent_color,
                profile_cards.c.border_style,
                profile_cards.c.card_css,
            ).where(profile_cards.c.user_id == uid)
        ).first()
        assert card.headline == "new headline"
        assert card.content == "new card content"
        assert card.accent_color == "#00ff00"
        assert card.border_style == "solid"
        assert card.card_css == "h2 { color: red; }"
