"""Forum routes: threads, posts, replies."""

import math

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.deps import current_user, get_engine, require_admin, templates
from app.queries.forum import (
    create_reply,
    create_thread,
    delete_post_safe,
    delete_thread,
    get_post,
    get_thread,
    list_posts,
    list_threads,
    toggle_lock,
    toggle_pin,
    update_post,
    update_thread_meta,
)
from app.queries.media import list_media_for_user
from app.rendering import render_forum_post, render_signature

router = APIRouter(prefix="/forum", tags=["forum"])

THREADS_PER_PAGE = 25
POSTS_PER_PAGE = 50


@router.get("", response_class=HTMLResponse)
def forum_index(request: Request, page: int = 1):
    page = max(1, page)
    with get_engine(request).begin() as conn:
        threads, total = list_threads(conn, page=page, per_page=THREADS_PER_PAGE)
    total_pages = max(1, math.ceil(total / THREADS_PER_PAGE))
    return templates.TemplateResponse(
        request,
        "forum/index.html",
        {
            "threads": threads,
            "total": total,
            "current_page": page,
            "total_pages": total_pages,
            "me": current_user(request),
        },
    )


@router.get("/new", response_class=HTMLResponse)
def new_thread_form(request: Request):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
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
    title: str = Form(...),
    content: str = Form(...),
    content_format: str = Form("bbcode"),
    custom_css: str = Form(""),
    custom_html: str = Form(""),
):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with get_engine(request).begin() as conn:
        thread_id = create_thread(
            conn,
            author_id=me["id"],
            title=title.strip(),
            content=content,
            content_format=content_format,
            custom_css=custom_css,
            custom_html=custom_html,
        )
    return RedirectResponse(url=f"/forum/{thread_id}", status_code=303)


@router.get("/{thread_id}", response_class=HTMLResponse)
def thread_view(request: Request, thread_id: int, page: int = 1):
    page = max(1, page)
    me = current_user(request)
    with get_engine(request).begin() as conn:
        thread = get_thread(conn, thread_id)
        if not thread:
            raise HTTPException(404)
        posts, total = list_posts(conn, thread_id, page=page, per_page=POSTS_PER_PAGE)
        media_items = list_media_for_user(conn, me["id"]) if me else []

    total_pages = max(1, math.ceil(total / POSTS_PER_PAGE))

    rendered_posts = []
    for post in posts:
        rendered_posts.append(
            {
                **post,
                "rendered_content": render_forum_post(
                    post["content"], post["content_format"]
                ),
                "rendered_signature": render_signature(
                    post.get("author_signature") or ""
                ),
            }
        )

    is_author = me and me["id"] == thread["author_id"]

    return templates.TemplateResponse(
        request,
        "forum/thread.html",
        {
            "thread": thread,
            "posts": rendered_posts,
            "total": total,
            "current_page": page,
            "total_pages": total_pages,
            "me": me,
            "is_author": is_author,
            "media_items": media_items,
        },
    )


@router.post("/{thread_id}/reply")
def thread_reply(
    request: Request,
    thread_id: int,
    content: str = Form(...),
    content_format: str = Form("bbcode"),
    quoted_post_id: int | None = Form(None),
    quoted_content: str | None = Form(None),
    quoted_author: str | None = Form(None),
):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)

    with get_engine(request).begin() as conn:
        thread = get_thread(conn, thread_id)
        if not thread:
            raise HTTPException(404)
        if thread["is_locked"]:
            raise HTTPException(403, detail="Thread is locked")
        create_reply(
            conn,
            thread_id=thread_id,
            author_id=me["id"],
            content=content,
            content_format=content_format,
            quoted_post_id=quoted_post_id,
            quoted_content=quoted_content or None,
            quoted_author=quoted_author or None,
        )
        # Calculate last page after adding the reply
        _, total = list_posts(conn, thread_id, page=1, per_page=POSTS_PER_PAGE)

    last_page = max(1, math.ceil(total / POSTS_PER_PAGE))
    return RedirectResponse(url=f"/forum/{thread_id}?page={last_page}", status_code=303)


@router.get("/{thread_id}/edit", response_class=HTMLResponse)
def edit_thread_form(request: Request, thread_id: int):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
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
    title: str = Form(...),
    custom_css: str = Form(""),
    custom_html: str = Form(""),
):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
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
    return RedirectResponse(url=f"/forum/{thread_id}", status_code=303)


@router.get("/posts/{post_id}/edit", response_class=HTMLResponse)
def edit_post_form(request: Request, post_id: int):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
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
    content: str = Form(...),
    content_format: str = Form("bbcode"),
):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
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
    return RedirectResponse(url=f"/forum/{post['thread_id']}", status_code=303)


@router.post("/posts/{post_id}/delete")
def delete_post_route(request: Request, post_id: int):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with get_engine(request).begin() as conn:
        post = get_post(conn, post_id)
        if not post:
            raise HTTPException(404)
        deleted = delete_post_safe(
            conn, post_id, me["id"], is_admin=me.get("is_admin", False)
        )
        if not deleted:
            raise HTTPException(403)
    return RedirectResponse(url=f"/forum/{post['thread_id']}", status_code=303)


@router.post("/{thread_id}/delete")
def delete_thread_route(request: Request, thread_id: int):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with get_engine(request).begin() as conn:
        deleted = delete_thread(
            conn, thread_id, me["id"], is_admin=me.get("is_admin", False)
        )
        if not deleted:
            raise HTTPException(404)
    return RedirectResponse(url="/forum", status_code=303)


@router.post("/{thread_id}/pin")
def pin_thread(request: Request, thread_id: int):
    require_admin(request)
    with get_engine(request).begin() as conn:
        toggle_pin(conn, thread_id)
    return RedirectResponse(url="/forum", status_code=303)


@router.post("/{thread_id}/lock")
def lock_thread(request: Request, thread_id: int):
    require_admin(request)
    with get_engine(request).begin() as conn:
        toggle_lock(conn, thread_id)
    return RedirectResponse(url=f"/forum/{thread_id}", status_code=303)
