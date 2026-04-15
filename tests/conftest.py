from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, insert
from sqlalchemy.pool import StaticPool

from app.main import app
from app.schema import metadata, profile_cards, users
from app.security import hash_password


@asynccontextmanager
async def _noop_lifespan(application):
    yield


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
    original_lifespan = app.router.lifespan_context

    app.state.engine = test_engine
    app.state.testing = True
    app.router.lifespan_context = _noop_lifespan

    with TestClient(app, raise_server_exceptions=True) as c:
        yield c

    app.router.lifespan_context = original_lifespan
    app.state.engine = original_engine
    app.state.testing = False


@pytest.fixture()
def seed_user(test_engine):
    """Create a user with a profile card and return the user dict."""
    with test_engine.begin() as conn:
        result = conn.execute(
            insert(users).values(
                username="testuser",
                password_hash=hash_password("testpass"),
                display_name="Test User",
                content="hello",
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
def raw_client(test_engine):
    """Raw TestClient WITHOUT CSRF token injection."""
    original_engine = app.state.engine
    original_lifespan = app.router.lifespan_context
    app.state.engine = test_engine
    app.router.lifespan_context = _noop_lifespan
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.router.lifespan_context = original_lifespan
    app.state.engine = original_engine


@pytest.fixture()
def authed_client(client, seed_user):
    """A TestClient that is logged in as the seed user."""
    client.post(
        "/login",
        data={"username": seed_user["username"], "password": seed_user["password"]},
    )
    return client


# ---------------------------------------------------------------------------
# Shared test helpers (non-fixtures)
# ---------------------------------------------------------------------------


def make_test_user(conn, username, invited_by=None, password="pass"):
    """Create a user with a profile card. Returns user id."""
    result = conn.execute(
        insert(users).values(
            username=username,
            password_hash=hash_password(password),
            display_name=username,
            invited_by_user_id=invited_by,
        )
    )
    uid = result.inserted_primary_key[0]
    conn.execute(
        insert(profile_cards).values(user_id=uid, headline=f"{username}'s page")
    )
    return uid


def promote_to_admin(conn, user_id):
    """Make a user an admin."""
    from sqlalchemy import update as sql_update

    sql_update_stmt = (
        sql_update(users).where(users.c.id == user_id).values(is_admin=True)
    )
    conn.execute(sql_update_stmt)


def make_admin_user(conn, username, password="pass"):
    """Create a user and make them admin. Returns user id."""
    uid = make_test_user(conn, username, password=password)
    promote_to_admin(conn, uid)
    return uid


def login_as(client, username, password="pass"):
    """Log in the test client as the given user."""
    client.post("/login", data={"username": username, "password": password})
