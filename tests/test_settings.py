def test_settings_requires_login(client):
    r = client.get("/settings", follow_redirects=False)
    assert r.status_code == 303
    assert "/login" in r.headers["location"]


def test_settings_renders(authed_client):
    r = authed_client.get("/settings")
    assert r.status_code == 200
    assert "profile" in r.text.lower()
    assert "css" in r.text.lower()
    assert "profile card" in r.text.lower()
    assert "invites" in r.text.lower()


def test_save_profile(authed_client):
    r = authed_client.post(
        "/settings/profile",
        data={
            "display_name": "New Name",
            "content": "new content",
            "content_format": "html",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    # Verify on profile page
    r2 = authed_client.get("/u/testuser")
    assert r2.status_code == 200
    assert "New Name" in r2.text
    assert "new content" in r2.text


def test_save_css(authed_client):
    authed_client.post(
        "/settings/css",
        data={"custom_css": "body { color: red; }"},
    )

    r = authed_client.get("/u/testuser")
    assert r.status_code == 200
    assert "body { color: red; }" in r.text


def test_save_custom_html(authed_client):
    authed_client.post(
        "/settings/html",
        data={"custom_html": "<script>alert(1)</script>"},
    )

    r = authed_client.get("/u/testuser")
    assert r.status_code == 200
    assert "<script>alert(1)</script>" in r.text


def test_save_card(authed_client):
    r = authed_client.post(
        "/settings/card",
        data={
            "headline": "new headline",
            "content": "new card content",
            "content_format": "html",
            "accent_color": "#ff0000",
            "border_style": "dashed",
            "card_css": "h2 { color: blue; }",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    # Verify on homepage
    r2 = authed_client.get("/")
    assert r2.status_code == 200
    assert "new headline" in r2.text


def test_save_card_markdown(authed_client):
    authed_client.post(
        "/settings/card",
        data={
            "headline": "md card",
            "content": "**bold**",
            "content_format": "markdown",
            "accent_color": "#00ff00",
            "border_style": "solid",
            "card_css": "",
        },
    )

    r = authed_client.get("/")
    assert r.status_code == 200
    assert "md card" in r.text
    # Markdown should be rendered to HTML inside the srcdoc (HTML-escaped)
    assert "&lt;strong&gt;bold&lt;/strong&gt;" in r.text


def test_create_invite(authed_client):
    r = authed_client.post(
        "/settings/invites",
        data={"max_uses": "1"},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "new invite code" in r.text.lower()


def test_disable_invite(authed_client, test_engine, seed_user):
    from app.queries.users import create_invite, create_user_with_invite

    from sqlalchemy import select

    from app.schema import invites

    # Create invite and use it so it can't be deleted
    with test_engine.begin() as conn:
        code = create_invite(conn, seed_user["id"], max_uses=2)
        create_user_with_invite(
            conn, username="invited_user", password="pass", invite_code=code
        )
        inv = conn.execute(select(invites.c.id).where(invites.c.code == code)).first()

    r = authed_client.post(
        f"/settings/invites/{inv[0]}/disable",
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "disabled" in r.text


def test_delete_unused_invite(authed_client, test_engine, seed_user):
    from app.queries.users import create_invite

    from sqlalchemy import select

    from app.schema import invites

    with test_engine.begin() as conn:
        code = create_invite(conn, seed_user["id"], max_uses=1)
        inv = conn.execute(select(invites.c.id).where(invites.c.code == code)).first()

    r = authed_client.post(
        f"/settings/invites/{inv[0]}/delete",
        follow_redirects=True,
    )
    assert r.status_code == 200

    # Invite should be gone
    with test_engine.begin() as conn:
        remaining = conn.execute(
            select(invites.c.id).where(invites.c.code == code)
        ).first()
    assert remaining is None


def test_save_profile_htmx(authed_client):
    r = authed_client.post(
        "/settings/profile",
        data={
            "display_name": "HTMX Name",
            "content": "htmx content",
            "content_format": "html",
        },
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert "saved" in r.text.lower()


def test_save_css_htmx(authed_client):
    r = authed_client.post(
        "/settings/css",
        data={"custom_css": "body{}"},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert "saved" in r.text.lower()


def test_page_delete(authed_client, seed_user):
    authed_client.post(
        "/settings/pages",
        data={
            "slug": "to-delete",
            "title": "Delete Me",
            "content": "bye",
            "content_format": "html",
        },
    )

    r = authed_client.post(
        "/settings/pages/to-delete/delete",
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert "to-delete" not in r.text

    # Verify page is gone
    r2 = authed_client.get(f"/u/{seed_user['username']}/page/to-delete")
    assert r2.status_code == 404


def test_media_page_renders(authed_client):
    r = authed_client.get("/settings/media")
    assert r.status_code == 200
    assert "media library" in r.text.lower()


def test_lineage_renders(client, seed_user):
    r = client.get("/lineage")
    assert r.status_code == 200
    assert "testuser" in r.text


def test_profile_renders(client, seed_user):
    r = client.get("/u/testuser")
    assert r.status_code == 200
    assert "Test User" in r.text


def test_profile_not_found(client):
    r = client.get("/u/nobody")
    assert r.status_code == 404


def test_settings_username_change_updates_user(authed_client, test_engine, seed_user):
    r = authed_client.post(
        "/settings/username",
        data={"username": "newname"},
        follow_redirects=False,
    )
    assert r.status_code == 303

    with test_engine.begin() as conn:
        updated = (
            conn.execute(select(users).where(users.c.id == seed_user["id"]))
            .mappings()
            .first()
        )
    assert updated["username"] == "newname"


def test_settings_username_change_moves_media_paths_and_files(
    authed_client, test_engine, seed_user, tmp_path, monkeypatch
):
    uploads_root = tmp_path / "uploads"
    monkeypatch.setattr(deps, "UPLOADS_DIR", uploads_root)
    old_dir = uploads_root / seed_user["username"]
    old_dir.mkdir(parents=True, exist_ok=True)
    old_file = old_dir / "photo.jpg"
    old_file.write_bytes(b"abc")

    with test_engine.begin() as conn:
        conn.execute(
            insert(media).values(
                user_id=seed_user["id"],
                storage_path=f"{seed_user['username']}/photo.jpg",
                mime_type="image/jpeg",
                size_bytes=3,
            )
        )

    r = authed_client.post(
        "/settings/username",
        data={"username": "renamed"},
        follow_redirects=False,
    )
    assert r.status_code == 303

    new_file = uploads_root / "renamed" / "photo.jpg"
    assert new_file.exists()
    assert not old_file.exists()

    with test_engine.begin() as conn:
        row = conn.execute(select(media)).mappings().first()
        user = (
            conn.execute(select(users).where(users.c.id == seed_user["id"]))
            .mappings()
            .first()
        )
    assert row["storage_path"] == "renamed/photo.jpg"
    assert user["username"] == "renamed"


def test_settings_username_change_rejects_taken_username(
    authed_client, test_engine, seed_user
):
    with test_engine.begin() as conn:
        conn.execute(
            insert(users).values(
                username="takenname",
                password_hash="x",
                display_name="taken",
            )
        )

    r = authed_client.post(
        "/settings/username",
        data={"username": "takenname"},
        follow_redirects=False,
    )
    assert r.status_code == 303

    with test_engine.begin() as conn:
        user = (
            conn.execute(select(users).where(users.c.id == seed_user["id"]))
            .mappings()
            .first()
        )
    assert user["username"] == seed_user["username"]


def test_settings_username_change_rejects_invalid(
    authed_client, test_engine, seed_user
):
    r = authed_client.post(
        "/settings/username",
        data={"username": "no spaces allowed"},
        follow_redirects=False,
    )
    assert r.status_code == 303

    with test_engine.begin() as conn:
        user = (
            conn.execute(select(users).where(users.c.id == seed_user["id"]))
            .mappings()
            .first()
        )
    assert user["username"] == seed_user["username"]


from datetime import datetime

from sqlalchemy import insert, select, update as sql_update

from app import deps
from app.schema import media, profile_cards, users

# Set a known past time to test updated_at changes (SQLite has 1s precision)
_PAST = datetime(2020, 1, 1)


def test_profile_save_updates_updated_at(authed_client, test_engine, seed_user):
    """Saving profile should bump users.updated_at."""
    with test_engine.begin() as conn:
        conn.execute(
            sql_update(users)
            .where(users.c.id == seed_user["id"])
            .values(updated_at=_PAST)
        )

    authed_client.post(
        "/settings/profile",
        data={
            "display_name": "Updated",
            "content": "new",
            "content_format": "html",
            "layout": "default",
        },
    )

    with test_engine.begin() as conn:
        after = conn.execute(
            select(users.c.updated_at).where(users.c.id == seed_user["id"])
        ).scalar()

    assert after > _PAST


def test_css_save_updates_updated_at(authed_client, test_engine, seed_user):
    """Saving CSS should bump users.updated_at."""
    with test_engine.begin() as conn:
        conn.execute(
            sql_update(users)
            .where(users.c.id == seed_user["id"])
            .values(updated_at=_PAST)
        )

    authed_client.post("/settings/css", data={"custom_css": "body{}"})

    with test_engine.begin() as conn:
        after = conn.execute(
            select(users.c.updated_at).where(users.c.id == seed_user["id"])
        ).scalar()

    assert after > _PAST


def test_card_save_updates_updated_at(authed_client, test_engine, seed_user):
    """Saving card should bump profile_cards.updated_at."""
    with test_engine.begin() as conn:
        conn.execute(
            sql_update(profile_cards)
            .where(profile_cards.c.user_id == seed_user["id"])
            .values(updated_at=_PAST)
        )

    authed_client.post(
        "/settings/card",
        data={
            "headline": "new",
            "content": "new",
            "content_format": "html",
            "accent_color": "#00ffff",
            "border_style": "solid",
            "card_css": "",
        },
    )

    with test_engine.begin() as conn:
        after = conn.execute(
            select(profile_cards.c.updated_at).where(
                profile_cards.c.user_id == seed_user["id"]
            )
        ).scalar()

    assert after > _PAST
