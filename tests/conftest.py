import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, insert
from sqlalchemy.pool import StaticPool

from app.main import app
from app.schema import metadata, profile_cards, users
from app.security import hash_password


@pytest.fixture()
def test_engine():
    """Create a fresh in-memory SQLite database for each test."""
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(eng, "connect")
    def _set_sqlite_pragma(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def client(test_engine):
    """TestClient with the app's engine swapped to the test database."""
    original_engine = app.state.engine
    original_handlers = app.router.on_startup.copy()

    app.state.engine = test_engine
    app.router.on_startup.clear()

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    app.router.on_startup = original_handlers
    app.state.engine = original_engine


@pytest.fixture()
def seed_user(test_engine):
    """Create a user with a profile card and return the user dict."""
    with test_engine.begin() as conn:
        result = conn.execute(
            insert(users).values(
                username="testuser",
                password_hash=hash_password("testpass"),
                display_name="Test User",
                bio="hello",
            )
        )
        user_id = result.inserted_primary_key[0]
        conn.execute(
            insert(profile_cards).values(
                user_id=user_id,
                headline="test card",
                content="card content",
            )
        )
    return {"id": user_id, "username": "testuser", "password": "testpass"}


@pytest.fixture()
def authed_client(client, seed_user):
    """A TestClient that is logged in as the seed user."""
    client.post(
        "/login",
        data={"username": seed_user["username"], "password": seed_user["password"]},
    )
    return client
