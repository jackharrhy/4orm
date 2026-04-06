def test_create_page_html(authed_client, seed_user):
    r = authed_client.post(
        "/settings/pages",
        data={
            "slug": "hello",
            "title": "Hello Page",
            "content": "<h1>Hello</h1>",
            "content_format": "html",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    # Page should render
    r2 = authed_client.get(f"/u/{seed_user['username']}/page/hello")
    assert r2.status_code == 200
    assert "<h1>Hello</h1>" in r2.text
    assert "Hello Page" in r2.text


def test_create_page_markdown(authed_client, seed_user):
    r = authed_client.post(
        "/settings/pages",
        data={
            "slug": "md-test",
            "title": "Markdown Page",
            "content": "# Heading\n\n**bold** text",
            "content_format": "markdown",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    r2 = authed_client.get(f"/u/{seed_user['username']}/page/md-test")
    assert r2.status_code == 200
    assert "<h1>Heading</h1>" in r2.text
    assert "<strong>bold</strong>" in r2.text


def test_edit_page(authed_client, seed_user):
    # Create a page first
    authed_client.post(
        "/settings/pages",
        data={
            "slug": "editable",
            "title": "Original",
            "content": "original content",
            "content_format": "html",
        },
    )

    # Edit it
    r = authed_client.post(
        "/settings/pages/editable/edit",
        data={
            "new_slug": "editable",
            "title": "Updated",
            "content": "new content",
            "content_format": "html",
            "is_public": "on",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    # Verify update
    r2 = authed_client.get(f"/u/{seed_user['username']}/page/editable")
    assert r2.status_code == 200
    assert "Updated" in r2.text
    assert "new content" in r2.text


def test_edit_page_renders(authed_client, seed_user):
    authed_client.post(
        "/settings/pages",
        data={
            "slug": "to-edit",
            "title": "Edit Me",
            "content": "<p>hello</p>",
            "content_format": "html",
        },
    )

    r = authed_client.get("/settings/pages/to-edit/edit")
    assert r.status_code == 200
    assert "to-edit" in r.text
    assert "Edit Me" in r.text


def test_create_duplicate_slug(authed_client, seed_user):
    authed_client.post(
        "/settings/pages",
        data={
            "slug": "dupe",
            "title": "First",
            "content": "first",
            "content_format": "html",
        },
    )

    r = authed_client.post(
        "/settings/pages",
        data={
            "slug": "dupe",
            "title": "Second",
            "content": "second",
            "content_format": "html",
        },
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "slug already exists" in r.text


def test_page_not_found(client, seed_user):
    r = client.get(f"/u/{seed_user['username']}/page/nonexistent")
    assert r.status_code == 404


def test_page_applies_custom_css(authed_client, test_engine, seed_user):
    from sqlalchemy import update

    from app.schema import users

    # Set custom CSS on the user
    with test_engine.begin() as conn:
        conn.execute(
            update(users)
            .where(users.c.id == seed_user["id"])
            .values(custom_css="body { background: red; }")
        )

    authed_client.post(
        "/settings/pages",
        data={
            "slug": "styled",
            "title": "Styled",
            "content": "hello",
            "content_format": "html",
        },
    )

    r = authed_client.get(f"/u/{seed_user['username']}/page/styled")
    assert r.status_code == 200
    assert "body { background: red; }" in r.text


def test_page_applies_custom_html(authed_client, test_engine, seed_user):
    from sqlalchemy import update

    from app.schema import users

    with test_engine.begin() as conn:
        conn.execute(
            update(users)
            .where(users.c.id == seed_user["id"])
            .values(custom_html='<script>console.log("hi")</script>')
        )

    authed_client.post(
        "/settings/pages",
        data={
            "slug": "scripted",
            "title": "Scripted",
            "content": "hello",
            "content_format": "html",
        },
    )

    r = authed_client.get(f"/u/{seed_user['username']}/page/scripted")
    assert r.status_code == 200
    assert 'console.log("hi")' in r.text
