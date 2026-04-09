import pytest
from sqlalchemy import select

from app.schema import visitor_counters


@pytest.fixture(autouse=True)
def _clear_counter_cache():
    """Clear the counter rate limit cache between tests."""
    from app.routes.pages import _counter_seen

    _counter_seen.clear()


def test_counter_not_found(client):
    r = client.get("/u/nobody/counter")
    assert r.status_code == 404


def test_counter_route_increments_views(client, test_engine, seed_user):
    r1 = client.get(f"/u/{seed_user['username']}/counter")
    assert r1.status_code == 200
    assert f"{seed_user['username']} visitors" in r1.text

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
    assert row["total_views"] == 1


def test_counter_rate_limited(client, test_engine, seed_user):
    """Rapid requests from the same IP only count once."""
    client.get(f"/u/{seed_user['username']}/counter")
    client.get(f"/u/{seed_user['username']}/counter")
    client.get(f"/u/{seed_user['username']}/counter")

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

    assert row["total_views"] == 1


def test_settings_shows_counter_embed_snippet(authed_client, seed_user):
    r = authed_client.get("/settings")
    assert r.status_code == 200
    assert f"/u/{seed_user['username']}/counter" in r.text
    assert "iframe" in r.text.lower()
