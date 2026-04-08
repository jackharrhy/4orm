from sqlalchemy import select

from app.schema import visitor_counters


def test_counter_not_found(client):
    r = client.get("/u/nobody/counter")
    assert r.status_code == 404


def test_counter_route_increments_views(client, test_engine, seed_user):
    r1 = client.get(f"/u/{seed_user['username']}/counter")
    assert r1.status_code == 200
    assert f"{seed_user['username']} visitors" in r1.text

    r2 = client.get(f"/u/{seed_user['username']}/counter")
    assert r2.status_code == 200

    with test_engine.begin() as conn:
        row = (
            conn.execute(
                select(visitor_counters).where(
                    visitor_counters.c.user_id == seed_user["id"]
                )
            )
            .mappings()
            .first()
        )

    assert row is not None
    assert row["total_views"] == 2


def test_settings_shows_counter_embed_snippet(authed_client, seed_user):
    r = authed_client.get("/settings")
    assert r.status_code == 200
    assert f'/u/{seed_user["username"]}/counter' in r.text
    assert "iframe" in r.text.lower()
