from sqlalchemy import insert, select, update

from app.schema import pages, password_reset_tokens, profile_cards, site_settings, users
from tests.conftest import make_test_user


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


def test_admin_can_edit_site_banner(authed_client, test_engine, seed_user):
    _promote_admin(test_engine, seed_user["id"])

    response = authed_client.post(
        "/admin/site-banner",
        data={
            "banner_enabled": "on",
            "banner_html": "<strong>new feature</strong>",
            "banner_css": ".site-banner { background: pink; }",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    with test_engine.begin() as conn:
        banner = conn.execute(select(site_settings)).mappings().one()
    assert banner["banner_enabled"] is True
    assert banner["banner_html"] == "<strong>new feature</strong>"
    assert banner["banner_css"] == ".site-banner { background: pink; }"

    for path in ("/", "/forum", "/settings"):
        page = authed_client.get(path)
        assert page.status_code == 200
        assert '<aside class="site-banner"' in page.text
        assert "new feature" in page.text

    for path in ("/forum/new", f"/u/{seed_user['username']}", "/admin"):
        page = authed_client.get(path)
        assert page.status_code == 200
        assert '<aside class="site-banner" role="status"' not in page.text


def test_admin_randomizes_only_default_card_colors(
    authed_client, test_engine, seed_user
):
    _promote_admin(test_engine, seed_user["id"])
    with test_engine.begin() as conn:
        custom_id = make_test_user(conn, "custom-color")
        conn.execute(
            update(profile_cards)
            .where(profile_cards.c.user_id == custom_id)
            .values(accent_color="#123456")
        )

    r = authed_client.post(
        "/admin/cards/randomize-default-colors", follow_redirects=False
    )
    assert r.status_code == 303
    assert "randomized_cards=1" in r.headers["location"]

    with test_engine.begin() as conn:
        cards = {
            row["user_id"]: row["accent_color"]
            for row in conn.execute(select(profile_cards)).mappings()
        }
    assert cards[seed_user["id"]] != "#00ffff"
    assert cards[custom_id] == "#123456"


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


def test_admin_can_toggle_user_webring(authed_client, test_engine, seed_user):
    _promote_admin(test_engine, seed_user["id"])

    response = authed_client.post(
        f"/admin/users/{seed_user['id']}/toggle-webring",
        data={"in_webring": "on"},
        follow_redirects=False,
    )
    assert response.status_code == 303

    with test_engine.begin() as conn:
        enabled = conn.execute(
            select(users.c.in_webring).where(users.c.id == seed_user["id"])
        ).scalar_one()
    assert enabled is True

    response = authed_client.post(
        f"/admin/users/{seed_user['id']}/toggle-webring",
        follow_redirects=False,
    )
    assert response.status_code == 303

    with test_engine.begin() as conn:
        enabled = conn.execute(
            select(users.c.in_webring).where(users.c.id == seed_user["id"])
        ).scalar_one()
    assert enabled is False


def test_admin_can_create_password_reset_link(authed_client, test_engine, seed_user):
    _promote_admin(test_engine, seed_user["id"])

    with test_engine.begin() as conn:
        from app.security import hash_password

        target_id = conn.execute(
            insert(users).values(
                username="resetme",
                password_hash=hash_password("oldpass"),
                display_name="Reset Me",
                content="",
            )
        ).inserted_primary_key[0]

    r = authed_client.post(
        f"/admin/users/{target_id}/password-reset-link",
        headers={"HX-Request": "true"},
        follow_redirects=False,
    )
    assert r.status_code == 200
    assert "/login/forgot-password?token=" in r.text

    with test_engine.begin() as conn:
        row = (
            conn.execute(
                select(password_reset_tokens).where(
                    password_reset_tokens.c.user_id == target_id
                )
            )
            .mappings()
            .first()
        )
    assert row is not None
