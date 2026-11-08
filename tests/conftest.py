import json
import os
import time
from base64 import b64encode
from contextlib import asynccontextmanager

# Application imports validate deployment configuration. Tests intentionally use
# the local-only session key rather than requiring a production secret.
os.environ.setdefault("FOURM_ENV", "test")
os.environ.setdefault("OIDC_CLIENT_ID", "test-browser-client")

import pytest
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from sqlalchemy import create_engine, event, insert
from sqlalchemy.pool import StaticPool

from app import oidc
from app.config import session_config
from app.main import app
from app.schema import external_identities, metadata, profile_cards, users


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
                password_hash="",
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
    login_as(client, seed_user["username"])
    return client


# ---------------------------------------------------------------------------
# Shared test helpers (non-fixtures)
# ---------------------------------------------------------------------------


def make_test_user(conn, username, invited_by=None):
    """Create a user with a profile card. Returns user id."""
    result = conn.execute(
        insert(users).values(
            username=username,
            password_hash="",
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


def make_admin_user(conn, username):
    """Create a user and make them admin. Returns user id."""
    uid = make_test_user(conn, username)
    promote_to_admin(conn, uid)
    return uid


def login_as(client, username):
    """Set a signed post-OIDC session for isolated route tests."""
    from sqlalchemy import select

    from app import oidc

    with client.app.state.engine.connect() as conn:
        uid = conn.execute(
            select(users.c.id).where(users.c.username == username)
        ).scalar_one()
    session = {
        "user_id": uid,
        "oidc_issuer": oidc.configuration()[0],
        "oidc_expires_at": int(time.time()) + 300,
    }
    signer = TimestampSigner(session_config()["secret_key"])
    client.cookies.clear()
    client.cookies.set(
        "session",
        signer.sign(b64encode(json.dumps(session).encode())).decode(),
        domain="testserver.local",
    )


@pytest.fixture
def central_api(monkeypatch, tmp_path, seed_user, test_engine):
    monkeypatch.setenv("OIDC_CLIENT_ID", "browser")
    monkeypatch.setenv("OIDC_PROJECT_ID", "project")
    monkeypatch.setenv("OIDC_ORGANIZATION_ID", "org")
    secret = tmp_path / "resource.json"
    secret.write_text(json.dumps({"clientId": "resource", "clientSecret": "private"}))
    monkeypatch.setenv("OIDC_API_CREDENTIALS_FILE", str(secret))
    claims = {
        "active": True,
        "iss": "https://auth.jackharrhy.dev",
        "sub": "explicit-subject",
        "aud": ["project"],
        "client_id": "native-cli",
        "exp": int(time.time()) + 300,
        "jack_auth_principal_type": "user",
        "token_type": "Bearer",
        "scope": (
            "urn:zitadel:iam:org:project:id:project:aud "
            "urn:zitadel:iam:org:projects:roles "
            "urn:zitadel:iam:org:project:role:member"
        ),
        "urn:zitadel:iam:org:project:project:roles": {"member": {"org": "domain"}},
    }
    for permission in ("pages-read", "pages-write", "media-read", "media-write"):
        claims["scope"] += f" urn:zitadel:iam:org:project:role:{permission}"
        claims["urn:zitadel:iam:org:project:project:roles"][permission] = {
            "org": "domain"
        }
    monkeypatch.setattr(
        oidc,
        "discovery",
        lambda _: {"introspection_endpoint": "https://auth.jackharrhy.dev/introspect"},
    )
    monkeypatch.setattr(oidc, "provider_json", lambda *a, **kw: claims)
    with test_engine.begin() as conn:
        conn.execute(
            insert(external_identities).values(
                issuer=claims["iss"], subject=claims["sub"], user_id=seed_user["id"]
            )
        )
    return claims
