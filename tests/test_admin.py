from sqlalchemy import update

from app.schema import users


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
