def test_home_empty(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "no users yet" in r.text


def test_home_shows_cards(client, seed_user):
    r = client.get("/")
    assert r.status_code == 200
    assert "test card" in r.text
    assert "card content" in r.text


def test_home_card_with_markdown(client, test_engine, seed_user):
    from sqlalchemy import update

    from app.schema import profile_cards

    with test_engine.begin() as conn:
        conn.execute(
            update(profile_cards)
            .where(profile_cards.c.user_id == seed_user["id"])
            .values(content="**bold text**", content_format="markdown")
        )

    r = client.get("/")
    assert r.status_code == 200
    assert "&lt;strong&gt;bold text&lt;/strong&gt;" in r.text


def test_home_card_links_to_profile(client, seed_user):
    r = client.get("/")
    assert r.status_code == 200
    assert "/u/testuser" in r.text


def test_home_forum_preview_unescapes_html_entities(authed_client, seed_user):
    r = authed_client.post(
        "/forum/new",
        data={
            "title": "encoding test",
            "content": "Something that doesn't taste like before",
            "content_format": "bbcode",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303

    home = authed_client.get("/")
    assert home.status_code == 200
    assert "Something that" in home.text
    assert "taste like before" in home.text
    assert "doesn&amp;#39;t" not in home.text
