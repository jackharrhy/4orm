"""Chatroom routes: page, SSE stream, post message."""

import asyncio
import time
from datetime import UTC, datetime
from html import escape

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse
from sqlalchemy import insert, select

from app.deps import current_user, get_engine, is_htmx, templates
from app.schema import chat_messages, users

router = APIRouter(tags=["chat"])

_chat_buffer: list[dict] = []
_chat_event = asyncio.Event()
_BUFFER_MAX = 200
_FLOOD_WINDOW = 30  # seconds
_FLOOD_MAX = 20  # max messages in window
_FLOOD_TIMEOUT = 60  # seconds to time out
_post_history: dict[int, list[float]] = {}  # user_id -> list of timestamps
_timed_out_until: dict[int, float] = {}  # user_id -> monotonic time


def _inject_system_message(text: str) -> None:
    """Push a system message into the chat stream."""
    msg = {"username": "system", "message": text, "created_at": datetime.now(UTC)}
    _chat_buffer.append(msg)
    if len(_chat_buffer) > _BUFFER_MAX:
        _chat_buffer[:] = _chat_buffer[-_BUFFER_MAX:]
    _chat_event.set()


def _render_message_html(msg: dict, index: int, total: int) -> str:
    """Render a single chat message as HTML with opacity fade."""
    opacity = 1.0
    pos_from_end = total - index
    if pos_from_end > 60:
        fade_pos = pos_from_end - 60
        opacity = max(0.05, 1.0 - (fade_pos / 40) * 0.95)
    style = f"opacity: {opacity:.2f}" if opacity < 1.0 else ""
    username = escape(msg["username"])
    text = escape(msg["message"])
    return (
        f'<div class="chat-msg" style="{style}">'
        f'<a href="/u/{username}" class="chat-user">{username}</a>'
        f'<span class="chat-text">{text}</span>'
        f"</div>"
    )


@router.get("/chat", response_class=HTMLResponse, summary="Chatroom")
def chat_page(request: Request):
    with get_engine(request).begin() as conn:
        rows = (
            conn.execute(
                select(
                    chat_messages.c.id,
                    chat_messages.c.message,
                    chat_messages.c.created_at,
                    users.c.username,
                )
                .select_from(
                    chat_messages.join(users, chat_messages.c.author_id == users.c.id)
                )
                .order_by(chat_messages.c.id.desc())
                .limit(100)
            )
            .mappings()
            .all()
        )
    messages = list(reversed(rows))
    total = len(messages)
    rendered = [_render_message_html(m, i, total) for i, m in enumerate(messages)]
    return templates.TemplateResponse(
        request,
        "chat.html",
        {
            "me": current_user(request),
            "messages_html": "\n".join(rendered),
        },
    )


@router.get("/chat/stream")
async def chat_stream(request: Request):
    """SSE endpoint that pushes new chat messages."""
    last_seen = len(_chat_buffer)

    async def event_generator():
        nonlocal last_seen
        while True:
            _chat_event.clear()
            while len(_chat_buffer) > last_seen:
                msg = _chat_buffer[last_seen]
                html = _render_message_html(msg, 0, 1)
                yield f"event: message\ndata: {html}\n\n"
                last_seen += 1
            try:
                await asyncio.wait_for(_chat_event.wait(), timeout=30)
            except TimeoutError:
                yield ": keepalive\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/chat", response_class=HTMLResponse, summary="Send chat message")
def chat_post(request: Request, message: str = Form(...)):
    me = current_user(request)
    if not me:
        raise HTTPException(403)

    text = message.strip()[:500]
    if not text:
        raise HTTPException(400, detail="empty message")

    now = time.monotonic()
    uid = me["id"]

    # Check if user is timed out
    if uid in _timed_out_until and now < _timed_out_until[uid]:
        remaining = int(_timed_out_until[uid] - now)
        _inject_system_message(f"{me['username']} is timed out for {remaining}s")
        if is_htmx(request):
            return HTMLResponse("")
        raise HTTPException(429)

    # Track flood: sliding window of recent posts
    history = _post_history.setdefault(uid, [])
    history[:] = [t for t in history if now - t < _FLOOD_WINDOW]
    if len(history) >= _FLOOD_MAX:
        _timed_out_until[uid] = now + _FLOOD_TIMEOUT
        _inject_system_message(f"{me['username']} has been timed out for flooding")
        if is_htmx(request):
            return HTMLResponse("")
        raise HTTPException(429)
    history.append(now)

    with get_engine(request).begin() as conn:
        conn.execute(insert(chat_messages).values(author_id=me["id"], message=text))

    msg = {
        "username": me["username"],
        "message": text,
        "created_at": datetime.now(UTC),
    }
    _chat_buffer.append(msg)
    if len(_chat_buffer) > _BUFFER_MAX:
        _chat_buffer[:] = _chat_buffer[-_BUFFER_MAX:]
    _chat_event.set()

    if is_htmx(request):
        return HTMLResponse("")
    return RedirectResponse(url="/chat", status_code=303)
