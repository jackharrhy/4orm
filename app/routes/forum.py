"""Forum routes: threads, posts, replies."""

import math
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

from app.deps import (
    current_user,
    get_engine,
    is_htmx,
    json_response,
    require_admin,
    require_user_dep,
    templates,
    wants_json,
)
from app.models import (
    CreatedResponse,
    ErrorResponse,
    ForumPost,
    ForumThreadDetail,
    ForumThreadList,
    ForumThreadSummary,
    SuccessResponse,
)
from app.push import send_notification
from app.queries.forum import (
    create_reply,
    create_thread,
    delete_post_safe,
    delete_thread,
    get_post,
    get_thread,
    get_watchers,
    is_watching,
    list_posts,
    list_threads,
    toggle_lock,
    toggle_pin,
    unwatch_thread,
    update_post,
    update_thread_meta,
    watch_thread,
)
from app.queries.media import list_media_for_user
from app.rendering import render_forum_post, render_signature
from app.schema import forum_posts

router = APIRouter(prefix="/forum", tags=["forum"])

THREADS_PER_PAGE = 25
POSTS_PER_PAGE = 50


RATE_LIMIT_SECONDS = 10


def _check_rate_limit(request: Request, conn, user_id: int):
    """Rate limit: max 1 post per RATE_LIMIT_SECONDS. Returns wait time or 0."""
    if getattr(request.app.state, "testing", False):
        return 0

    last_post = conn.execute(
        select(forum_posts.c.created_at)
        .where(forum_posts.c.author_id == user_id)
        .order_by(forum_posts.c.created_at.desc())
        .limit(1)
    ).scalar()

    if last_post:
        if last_post.tzinfo is None:
            last_post = last_post.replace(tzinfo=UTC)
        elapsed = (datetime.now(UTC) - last_post).total_seconds()
        if elapsed < RATE_LIMIT_SECONDS:
            return int(RATE_LIMIT_SECONDS - elapsed)
    return 0


def _enforce_rate_limit(request: Request, conn, user_id: int):
    """Check rate limit and raise/return error if exceeded."""
    wait = _check_rate_limit(request, conn, user_id)
    if wait > 0:
        if wants_json(request):
            return ErrorResponse(error="please wait before posting again")
        if is_htmx(request):
            return HTMLResponse(
                f'<p class="error">please wait {wait} seconds before posting again</p>',
                status_code=429,
            )
        raise HTTPException(429, detail="Please wait before posting again")
    return None


@router.post("/preview", response_class=HTMLResponse, summary="Preview post content")
def preview_post(
    request: Request,
    content: str = Form(""),
    content_format: str = Form("bbcode"),
):
    """Render BBCode or Markdown content and return the HTML fragment."""
    rendered = render_forum_post(content, content_format)
    return HTMLResponse(
        f'<div class="forum-post-content">{rendered}</div>'
        if rendered.strip()
        else '<p class="muted">nothing to preview</p>'
    )


@router.get("", response_class=HTMLResponse)
def forum_index(request: Request, page: int = 1):
    current_page = max(1, page)
    with get_engine(request).begin() as conn:
        threads, total = list_threads(
            conn, page=current_page, per_page=THREADS_PER_PAGE
        )
    total_pages = max(1, math.ceil(total / THREADS_PER_PAGE))
    if wants_json(request):
        return json_response(
            ForumThreadList(
                threads=[
                    ForumThreadSummary(
                        id=t["id"],
                        title=t["title"],
                        author_username=t["author_username"],
                        author_display_name=t.get("author_display_name", ""),
                        reply_count=t.get("reply_count", 0),
                        is_pinned=t.get("is_pinned", False),
                        is_locked=t.get("is_locked", False),
                        last_reply_at=t.get("last_reply_at"),
                        created_at=t.get("created_at"),
                    )
                    for t in threads
                ],
                total=total,
                page=current_page,
                total_pages=total_pages,
            )
        )
    return templates.TemplateResponse(
        request,
        "forum/index.html",
        {
            "threads": threads,
            "total": total,
            "current_page": current_page,
            "total_pages": total_pages,
            "me": current_user(request),
        },
    )


@router.get("/new", response_class=HTMLResponse)
def new_thread_form(request: Request):
    me = require_user_dep(request)
    with get_engine(request).begin() as conn:
        media_items = list_media_for_user(conn, me["id"])
    return templates.TemplateResponse(
        request,
        "forum/new_thread.html",
        {"me": me, "media_items": media_items},
    )


@router.post("/new")
def new_thread_submit(
    request: Request,
    me: dict = Depends(require_user_dep),
    title: str = Form(...),
    content: str = Form(...),
    content_format: str = Form("bbcode"),
    custom_css: str = Form(""),
    custom_html: str = Form(""),
):
    with get_engine(request).begin() as conn:
        rate_error = _enforce_rate_limit(request, conn, me["id"])
        if rate_error:
            return rate_error

        thread_id = create_thread(
            conn,
            author_id=me["id"],
            title=title.strip(),
            content=content,
            content_format=content_format,
            custom_css=custom_css,
            custom_html=custom_html,
        )
    if wants_json(request):
        return CreatedResponse(ok=True, id=thread_id, redirect=f"/forum/{thread_id}")
    return RedirectResponse(url=f"/forum/{thread_id}", status_code=303)


@router.get("/{thread_id}", response_class=HTMLResponse)
def thread_view(request: Request, thread_id: int, page: int = 1):
    current_page = max(1, page)
    me = current_user(request)
    with get_engine(request).begin() as conn:
        thread = get_thread(conn, thread_id)
        if not thread:
            raise HTTPException(404)
        posts, total = list_posts(
            conn, thread_id, page=current_page, per_page=POSTS_PER_PAGE
        )
        media_items = list_media_for_user(conn, me["id"]) if me else []
        watching = is_watching(conn, me["id"], thread_id) if me else False

    total_pages = max(1, math.ceil(total / POSTS_PER_PAGE))

    rendered_posts = []
    for post in posts:
        rendered_quoted = ""
        if post.get("quoted_content"):
            qfmt = post.get("quoted_content_format") or "bbcode"
            rendered_quoted = render_forum_post(post["quoted_content"], qfmt)
        rendered_posts.append(
            {
                **post,
                "rendered_content": render_forum_post(
                    post["content"], post["content_format"]
                ),
                "rendered_quoted_content": rendered_quoted,
                "rendered_signature": render_signature(
                    post.get("author_signature") or ""
                ),
            }
        )

    if wants_json(request):
        return json_response(
            ForumThreadDetail(
                id=thread["id"],
                title=thread["title"],
                author_username=thread["author_username"],
                author_display_name=thread.get("author_display_name", ""),
                is_pinned=thread.get("is_pinned", False),
                is_locked=thread.get("is_locked", False),
                custom_css=thread.get("custom_css", ""),
                custom_html=thread.get("custom_html", ""),
                created_at=thread.get("created_at"),
                posts=[
                    ForumPost(
                        id=p["id"],
                        thread_id=p["thread_id"],
                        author_username=p["author_username"],
                        author_display_name=p.get("author_display_name", ""),
                        content=p["content"],
                        content_format=p["content_format"],
                        rendered_content=p.get("rendered_content", ""),
                        quoted_post_id=p.get("quoted_post_id"),
                        quoted_content=p.get("quoted_content"),
                        quoted_content_format=p.get("quoted_content_format"),
                        rendered_quoted_content=p.get("rendered_quoted_content"),
                        quoted_author=p.get("quoted_author"),
                        is_edited=p.get("is_edited", False),
                        author_signature=p.get("author_signature"),
                        rendered_signature=p.get("rendered_signature"),
                        created_at=p.get("created_at"),
                    )
                    for p in rendered_posts
                ],
                total_posts=total,
                page=current_page,
                total_pages=total_pages,
                watching=watching,
            )
        )

    is_author = me and me["id"] == thread["author_id"]

    return templates.TemplateResponse(
        request,
        "forum/thread.html",
        {
            "thread": thread,
            "posts": rendered_posts,
            "total": total,
            "current_page": current_page,
            "total_pages": total_pages,
            "me": me,
            "is_author": is_author,
            "media_items": media_items,
            "watching": watching,
        },
    )


@router.post("/{thread_id}/reply")
def thread_reply(
    request: Request,
    thread_id: int,
    me: dict = Depends(require_user_dep),
    content: str = Form(...),
    content_format: str = Form("bbcode"),
    quoted_post_id: int | None = Form(None),
    quoted_content: str | None = Form(None),
    quoted_author: str | None = Form(None),
):
    with get_engine(request).begin() as conn:
        rate_error = _enforce_rate_limit(request, conn, me["id"])
        if rate_error:
            return rate_error

        thread = get_thread(conn, thread_id)
        if not thread:
            raise HTTPException(404)
        if thread["is_locked"]:
            raise HTTPException(403, detail="Thread is locked")
        # Look up the quoted post's content_format
        quoted_content_format = None
        if quoted_post_id:
            qp = get_post(conn, quoted_post_id)
            if qp:
                quoted_content_format = qp["content_format"]

        post_id = create_reply(
            conn,
            thread_id=thread_id,
            author_id=me["id"],
            content=content,
            content_format=content_format,
            quoted_post_id=quoted_post_id,
            quoted_content=quoted_content or None,
            quoted_content_format=quoted_content_format,
            quoted_author=quoted_author or None,
        )

        # Notify all watchers (except the replier)
        watcher_ids = get_watchers(conn, thread_id)
        for watcher_id in watcher_ids:
            if watcher_id != me["id"]:
                send_notification(
                    conn,
                    watcher_id,
                    f"New reply in {thread['title']}",
                    f"{me['display_name']} replied",
                    f"/forum/{thread_id}#post-{post_id}",
                )

        # Still notify quoted post author separately (if not already a watcher)
        if quoted_post_id:
            qp_notif = get_post(conn, quoted_post_id)
            if (
                qp_notif
                and qp_notif["author_id"] != me["id"]
                and qp_notif["author_id"] not in watcher_ids
            ):
                send_notification(
                    conn,
                    qp_notif["author_id"],
                    f"You were quoted in {thread['title']}",
                    f"{me['display_name']} quoted your post",
                    f"/forum/{thread_id}#post-{post_id}",
                )

        # Calculate last page after adding the reply
        _, total = list_posts(conn, thread_id, page=1, per_page=POSTS_PER_PAGE)

    last_page = max(1, math.ceil(total / POSTS_PER_PAGE))
    if wants_json(request):
        return CreatedResponse(
            ok=True, id=post_id, redirect=f"/forum/{thread_id}?page={last_page}"
        )
    if is_htmx(request):
        response = HTMLResponse("")
        response.headers["HX-Redirect"] = f"/forum/{thread_id}?page={last_page}"
        return response
    return RedirectResponse(url=f"/forum/{thread_id}?page={last_page}", status_code=303)


@router.get("/{thread_id}/edit", response_class=HTMLResponse)
def edit_thread_form(request: Request, thread_id: int):
    me = require_user_dep(request)
    with get_engine(request).begin() as conn:
        thread = get_thread(conn, thread_id)
    if not thread:
        raise HTTPException(404)
    if me["id"] != thread["author_id"] and not me.get("is_admin"):
        raise HTTPException(403)
    return templates.TemplateResponse(
        request,
        "forum/edit_thread.html",
        {"me": me, "thread": thread},
    )


@router.post("/{thread_id}/edit")
def edit_thread_submit(
    request: Request,
    thread_id: int,
    me: dict = Depends(require_user_dep),
    title: str = Form(...),
    custom_css: str = Form(""),
    custom_html: str = Form(""),
):
    with get_engine(request).begin() as conn:
        thread = get_thread(conn, thread_id)
        if not thread:
            raise HTTPException(404)
        if me["id"] != thread["author_id"] and not me.get("is_admin"):
            raise HTTPException(403)
        update_thread_meta(
            conn,
            thread_id=thread_id,
            author_id=thread["author_id"],
            title=title.strip(),
            custom_css=custom_css,
            custom_html=custom_html,
            is_admin=me.get("is_admin", False),
        )
    if wants_json(request):
        return SuccessResponse(message="thread updated")
    return RedirectResponse(url=f"/forum/{thread_id}", status_code=303)


@router.get("/posts/{post_id}/edit", response_class=HTMLResponse)
def edit_post_form(request: Request, post_id: int):
    me = require_user_dep(request)
    with get_engine(request).begin() as conn:
        post = get_post(conn, post_id)
        if not post:
            raise HTTPException(404)
        if me["id"] != post["author_id"] and not me.get("is_admin"):
            raise HTTPException(403)
        media_items = list_media_for_user(conn, me["id"])
    return templates.TemplateResponse(
        request,
        "forum/edit_post.html",
        {"me": me, "post": post, "media_items": media_items},
    )


@router.post("/posts/{post_id}/edit")
def edit_post_submit(
    request: Request,
    post_id: int,
    me: dict = Depends(require_user_dep),
    content: str = Form(...),
    content_format: str = Form("bbcode"),
):
    with get_engine(request).begin() as conn:
        post = get_post(conn, post_id)
        if not post:
            raise HTTPException(404)
        if me["id"] != post["author_id"] and not me.get("is_admin"):
            raise HTTPException(403)
        update_post(
            conn,
            post_id,
            post["author_id"],
            content,
            content_format,
            is_admin=me.get("is_admin", False),
        )
    if wants_json(request):
        return SuccessResponse(message="post updated")
    return RedirectResponse(url=f"/forum/{post['thread_id']}", status_code=303)


@router.post("/posts/{post_id}/delete")
def delete_post_route(request: Request, post_id: int):
    me = require_user_dep(request)
    with get_engine(request).begin() as conn:
        post = get_post(conn, post_id)
        if not post:
            raise HTTPException(404)
        deleted = delete_post_safe(
            conn, post_id, me["id"], is_admin=me.get("is_admin", False)
        )
        if not deleted:
            raise HTTPException(403)
    if wants_json(request):
        return SuccessResponse(message="post deleted")
    if is_htmx(request):
        return HTMLResponse("")
    return RedirectResponse(url=f"/forum/{post['thread_id']}", status_code=303)


@router.post("/{thread_id}/delete")
def delete_thread_route(request: Request, thread_id: int):
    me = require_user_dep(request)
    with get_engine(request).begin() as conn:
        deleted = delete_thread(
            conn, thread_id, me["id"], is_admin=me.get("is_admin", False)
        )
        if not deleted:
            raise HTTPException(404)
    if wants_json(request):
        return SuccessResponse(message="thread deleted")
    if is_htmx(request):
        response = HTMLResponse("")
        response.headers["HX-Redirect"] = "/forum"
        return response
    return RedirectResponse(url="/forum", status_code=303)


@router.post("/{thread_id}/pin")
def pin_thread(request: Request, thread_id: int):
    require_admin(request)
    with get_engine(request).begin() as conn:
        toggle_pin(conn, thread_id)
    if wants_json(request):
        return SuccessResponse(message="pin toggled")
    if is_htmx(request):
        response = HTMLResponse("")
        response.headers["HX-Refresh"] = "true"
        return response
    return RedirectResponse(url="/forum", status_code=303)


@router.post("/{thread_id}/lock")
def lock_thread(request: Request, thread_id: int):
    require_admin(request)
    with get_engine(request).begin() as conn:
        toggle_lock(conn, thread_id)
    if wants_json(request):
        return SuccessResponse(message="lock toggled")
    if is_htmx(request):
        response = HTMLResponse("")
        response.headers["HX-Refresh"] = "true"
        return response
    return RedirectResponse(url=f"/forum/{thread_id}", status_code=303)


@router.post("/{thread_id}/watch")
def toggle_watch(request: Request, thread_id: int):
    me = require_user_dep(request)
    with get_engine(request).begin() as conn:
        thread = get_thread(conn, thread_id)
        if not thread:
            raise HTTPException(404)
        if is_watching(conn, me["id"], thread_id):
            unwatch_thread(conn, me["id"], thread_id)
        else:
            watch_thread(conn, me["id"], thread_id)
    if wants_json(request):
        with get_engine(request).begin() as conn:
            now_watching = is_watching(conn, me["id"], thread_id)
        return SuccessResponse(message="watching" if now_watching else "unwatched")
    if is_htmx(request):
        response = HTMLResponse("")
        response.headers["HX-Refresh"] = "true"
        return response
    return RedirectResponse(url=f"/forum/{thread_id}", status_code=303)
