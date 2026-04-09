from sqlalchemy import insert, select, update

from app.schema import pages, profile_cards, users


def test_admin_requires_login(client):
    r = client.get("/admin")
    assert r.status_code == 403


def test_admin_requires_admin_role(authed_client):
    r = authed_client.get("/admin")
    assert r.status_code == 403


def test_admin_dashboard(authed_client, test_engine, seed_user):
    # Promote seed user to admin
    with test_engine.begin() as conn:
        conn.execute(
            update(users).where(users.c.id == seed_user["id"]).values(is_admin=True)
        )

    r = authed_client.get("/admin")
    assert r.status_code == 200
    assert "admin" in r.text.lower()
    assert "testuser" in r.text


def _promote_admin(test_engine, user_id: int):
    with test_engine.begin() as conn:
        conn.execute(update(users).where(users.c.id == user_id).values(is_admin=True))


def test_admin_can_edit_user_profile(authed_client, test_engine, seed_user):
    _promote_admin(test_engine, seed_user["id"])

    r = authed_client.post(
        f"/admin/users/{seed_user['id']}/profile",
        data={
            "display_name": "Updated Name",
            "content": "profile cleanup",
            "content_format": "markdown",
            "custom_css": "body { color: red; }",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    with test_engine.begin() as conn:
        row = (
            conn.execute(select(users).where(users.c.id == seed_user["id"]))
            .mappings()
            .first()
        )
    assert row["display_name"] == "Updated Name"
    assert row["content"] == "profile cleanup"
    assert row["custom_css"] == "body { color: red; }"


def test_admin_can_edit_card(authed_client, test_engine, seed_user):
    _promote_admin(test_engine, seed_user["id"])

    r = authed_client.post(
        f"/admin/users/{seed_user['id']}/card",
        data={
            "headline": "new headline",
            "content": "new card content",
            "content_format": "markdown",
            "accent_color": "#123456",
            "border_style": "solid",
            "card_css": ".x{display:none}",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    with test_engine.begin() as conn:
        card = (
            conn.execute(
                select(profile_cards).where(profile_cards.c.user_id == seed_user["id"])
            )
            .mappings()
            .first()
        )
    assert card["headline"] == "new headline"
    assert card["content"] == "new card content"
    assert card["accent_color"] == "#123456"


def test_admin_can_edit_page(authed_client, test_engine, seed_user):
    _promote_admin(test_engine, seed_user["id"])
    with test_engine.begin() as conn:
        page_id = conn.execute(
            insert(pages).values(
                user_id=seed_user["id"],
                slug="hello",
                title="Hello",
                content="old",
                content_format="html",
                is_public=True,
            )
        ).inserted_primary_key[0]

    r = authed_client.post(
        f"/admin/pages/{page_id}",
        data={
            "slug": "hello-updated",
            "title": "Hello Updated",
            "content": "clean content",
            "content_format": "html",
            "is_public": "on",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    with test_engine.begin() as conn:
        page = (
            conn.execute(select(pages).where(pages.c.id == page_id)).mappings().first()
        )
    assert page["slug"] == "hello-updated"
    assert page["title"] == "Hello Updated"
    assert page["content"] == "clean content"


def test_admin_can_toggle_user_disabled(authed_client, test_engine, seed_user):
    _promote_admin(test_engine, seed_user["id"])

    # Create a separate target user so the admin doesn't disable themselves
    with test_engine.begin() as conn:
        from app.security import hash_password

        result = conn.execute(
            insert(users).values(
                username="targetuser",
                password_hash=hash_password("pass"),
                display_name="Target User",
                content="",
            )
        )
        target_id = result.inserted_primary_key[0]

    r = authed_client.post(
        f"/admin/users/{target_id}/toggle-disabled",
        follow_redirects=False,
    )
    assert r.status_code == 303

    with test_engine.begin() as conn:
        user = (
            conn.execute(select(users).where(users.c.id == target_id))
            .mappings()
            .first()
        )
    assert user["is_disabled"] is True

    r = authed_client.post(
        f"/admin/users/{target_id}/toggle-disabled",
        follow_redirects=False,
    )
    assert r.status_code == 303

    with test_engine.begin() as conn:
        user = (
            conn.execute(select(users).where(users.c.id == target_id))
            .mappings()
            .first()
        )
    assert user["is_disabled"] is False
