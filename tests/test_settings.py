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
        data={"display_name": "New Name", "bio": "new bio"},
        follow_redirects=False,
    )
    assert r.status_code == 303

    # Verify on profile page
    r2 = authed_client.get("/u/testuser")
    assert r2.status_code == 200
    assert "New Name" in r2.text
    assert "new bio" in r2.text


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
    from app.queries.users import create_invite

    with test_engine.begin() as conn:
        code = create_invite(conn, seed_user["id"], max_uses=1)

    # Get the invite ID
    from sqlalchemy import select

    from app.schema import invites

    with test_engine.begin() as conn:
        inv = conn.execute(select(invites.c.id).where(invites.c.code == code)).first()

    r = authed_client.post(
        f"/settings/invites/{inv[0]}/delete",
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "disabled" in r.text


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
