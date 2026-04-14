"""Tests for the chatroom."""

import pytest
from sqlalchemy import select

from app.routes.chat import _post_history, _timed_out_until
from app.schema import chat_messages


@pytest.fixture(autouse=True)
def _clear_rate_limit():
    """Reset the in-memory rate-limit state between tests."""
    _post_history.clear()
    _timed_out_until.clear()
    yield
    _post_history.clear()
    _timed_out_until.clear()


def test_chat_page_renders(client, seed_user):
    r = client.get("/chat")
    assert r.status_code == 200
    assert "chat" in r.text.lower()


def test_chat_post_requires_login(client, seed_user):
    r = client.post("/chat", data={"message": "hello"})
    assert r.status_code == 403


def test_chat_post_creates_message(authed_client, seed_user, test_engine):
    r = authed_client.post(
        "/chat", data={"message": "hello from test"}, follow_redirects=False
    )
    assert r.status_code in (200, 303)

    with test_engine.begin() as conn:
        row = (
            conn.execute(
                select(chat_messages).order_by(chat_messages.c.id.desc()).limit(1)
            )
            .mappings()
            .first()
        )
    assert row is not None
    assert row["message"] == "hello from test"


def test_chat_message_escaped(authed_client, seed_user):
    authed_client.post("/chat", data={"message": "<script>alert(1)</script>"})
    r = authed_client.get("/chat")
    assert "<script>alert(1)</script>" not in r.text
    assert "&lt;script&gt;" in r.text


def test_chat_message_truncated(authed_client, seed_user, test_engine):
    long_msg = "a" * 600
    authed_client.post("/chat", data={"message": long_msg})

    with test_engine.begin() as conn:
        row = (
            conn.execute(
                select(chat_messages).order_by(chat_messages.c.id.desc()).limit(1)
            )
            .mappings()
            .first()
        )
    assert len(row["message"]) == 500


def test_chat_page_has_sse_connect(client, seed_user):
    """Verify the chat page includes the SSE connection attribute."""
    r = client.get("/chat")
    assert 'sse-connect="/chat/stream"' in r.text


def test_chat_anonymous_sees_sign_in(client):
    r = client.get("/chat")
    assert "sign in" in r.text.lower()


def test_homepage_has_chat_button(client, seed_user):
    r = client.get("/")
    assert 'href="/chat"' in r.text
