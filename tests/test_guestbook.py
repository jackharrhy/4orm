from sqlalchemy import update

from app.schema import users
from tests.conftest import make_test_user


def _create_second_user(test_engine):
    """Create a second user for guestbook interaction."""
    with test_engine.begin() as conn:
        uid = make_test_user(conn, "visitor", password="visitorpass")
        conn.execute(
            update(users).where(users.c.id == uid).values(display_name="Visitor")
        )
    return {"id": uid, "username": "visitor", "password": "visitorpass"}


def test_guestbook_custom_css(client, test_engine, seed_user):
    from sqlalchemy import update as sql_update

    with test_engine.begin() as conn:
        conn.execute(
            sql_update(users)
            .where(users.c.id == seed_user["id"])
            .values(guestbook_css="body { background: pink; }")
        )

    r = client.get(f"/u/{seed_user['username']}/guestbook")
    assert r.status_code == 200
    assert "body { background: pink; }" in r.text


def test_save_guestbook_settings(authed_client):
    r = authed_client.post(
        "/settings/guestbook",
        data={
            "guestbook_css": "body { color: red; }",
            "guestbook_html": "<p>custom</p>",
        },
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert "saved" in r.text.lower()


def test_guestbook_renders(client, seed_user):
    r = client.get(f"/u/{seed_user['username']}/guestbook")
    assert r.status_code == 200
    assert "guestbook" in r.text.lower()
    assert "no entries yet" in r.text


def test_guestbook_not_found(client):
    r = client.get("/u/nobody/guestbook")
    assert r.status_code == 404


def test_guestbook_sign_in_prompt(client, seed_user):
    r = client.get(f"/u/{seed_user['username']}/guestbook")
    assert "sign in" in r.text.lower()


def test_guestbook_post_requires_login(client, seed_user):
    r = client.post(
        f"/u/{seed_user['username']}/guestbook",
        data={"message": "hello"},
    )
    assert r.status_code == 403


def test_guestbook_post_and_display(client, test_engine, seed_user):
    visitor = _create_second_user(test_engine)
    # Log in as visitor
    client.post(
        "/login",
        data={"username": visitor["username"], "password": visitor["password"]},
    )

    r = client.post(
        f"/u/{seed_user['username']}/guestbook",
        data={"message": "nice page!"},
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "nice page!" in r.text
    assert "Visitor" in r.text


def test_guestbook_post_htmx(client, test_engine, seed_user):
    visitor = _create_second_user(test_engine)
    client.post(
        "/login",
        data={"username": visitor["username"], "password": visitor["password"]},
    )

    r = client.post(
        f"/u/{seed_user['username']}/guestbook",
        data={"message": "htmx post"},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert "htmx post" in r.text


def test_guestbook_message_truncated(client, test_engine, seed_user):
    visitor = _create_second_user(test_engine)
    client.post(
        "/login",
        data={"username": visitor["username"], "password": visitor["password"]},
    )

    long_msg = "a" * 600
    client.post(
        f"/u/{seed_user['username']}/guestbook",
        data={"message": long_msg},
        headers={"HX-Request": "true"},
    )

    r = client.get(f"/u/{seed_user['username']}/guestbook")
    # Should be truncated to 500
    assert "a" * 500 in r.text
    assert "a" * 501 not in r.text


def test_guestbook_owner_can_delete(client, test_engine, seed_user):
    visitor = _create_second_user(test_engine)

    # Visitor signs the guestbook
    client.post(
        "/login",
        data={"username": visitor["username"], "password": visitor["password"]},
    )
    client.post(
        f"/u/{seed_user['username']}/guestbook",
        data={"message": "delete me"},
    )

    # Get the entry ID
    from sqlalchemy import select

    from app.schema import guestbook_entries

    with test_engine.begin() as conn:
        entry = conn.execute(select(guestbook_entries.c.id)).first()

    # Log in as owner
    client.post(
        "/login",
        data={"username": seed_user["username"], "password": seed_user["password"]},
    )

    r = client.post(
        f"/u/{seed_user['username']}/guestbook/{entry[0]}/delete",
        follow_redirects=True,
    )
    assert r.status_code == 200
    assert "delete me" not in r.text


def test_guestbook_non_owner_cannot_delete(client, test_engine, seed_user):
    visitor = _create_second_user(test_engine)

    # Visitor signs the guestbook
    client.post(
        "/login",
        data={"username": visitor["username"], "password": visitor["password"]},
    )
    client.post(
        f"/u/{seed_user['username']}/guestbook",
        data={"message": "keep me"},
    )

    from sqlalchemy import select

    from app.schema import guestbook_entries

    with test_engine.begin() as conn:
        entry = conn.execute(select(guestbook_entries.c.id)).first()

    # Visitor tries to delete (not the owner)
    r = client.post(
        f"/u/{seed_user['username']}/guestbook/{entry[0]}/delete",
    )
    assert r.status_code == 403
