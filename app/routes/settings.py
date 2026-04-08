"""User settings routes."""

from pathlib import Path

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, update

import app.deps as deps
from app.deps import (
    _saved_or_redirect,
    current_user,
    get_engine,
    is_htmx,
    templates,
)
from app.queries.media import list_media_for_user
from app.queries.pages import (
    create_page,
    delete_user_page,
    get_user_page,
    list_pages_for_user,
    update_user_page,
)
from app.queries.users import (
    create_invite,
    delete_invite,
    disable_invite,
    get_invites_for_user,
)
from app.schema import media, pages, profile_cards, users

router = APIRouter()


@router.get("/settings", response_class=HTMLResponse)
def settings_get(request: Request):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with get_engine(request).begin() as conn:
        my_pages = list_pages_for_user(conn, me["id"])
        card_settings = (
            conn.execute(
                select(profile_cards).where(profile_cards.c.user_id == me["id"])
            )
            .mappings()
            .first()
        )
        media_items = list_media_for_user(conn, me["id"])
        my_invites = get_invites_for_user(conn, me["id"])
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "me": me,
            "username": me["username"],
            "my_pages": my_pages,
            "card_settings": card_settings,
            "media_items": media_items,
            "my_invites": my_invites,
            "error": None,
        },
    )


@router.post("/settings/profile")
def settings_profile(
    request: Request,
    display_name: str = Form(""),
    content: str = Form(""),
    content_format: str = Form("html"),
    layout: str = Form("default"),
):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with get_engine(request).begin() as conn:
        conn.execute(
            update(users)
            .where(users.c.id == me["id"])
            .values(
                display_name=display_name,
                content=content,
                content_format=content_format,
                layout=layout,
            )
        )
    return _saved_or_redirect(request)


@router.post("/settings/username")
def settings_username(request: Request, username: str = Form(...)):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)

    new_username = username.strip().lower()
    if not deps.USERNAME_RE.match(new_username):
        if is_htmx(request):
            return HTMLResponse(
                '<span class="error">Username must be 3-32 chars using a-z, 0-9, - or _</span>',
                status_code=400,
            )
        return RedirectResponse(url="/settings?error=invalid_username", status_code=303)

    if new_username == me["username"]:
        return _saved_or_redirect(request)

    uploads_root = deps.UPLOADS_DIR
    old_username = me["username"]
    old_user_dir = uploads_root / old_username
    new_user_dir = uploads_root / new_username

    with get_engine(request).begin() as conn:
        existing = conn.execute(
            select(users.c.id).where(users.c.username == new_username)
        ).first()
        if existing:
            if is_htmx(request):
                return HTMLResponse(
                    '<span class="error">That username is already taken</span>',
                    status_code=400,
                )
            return RedirectResponse(
                url="/settings?error=username_taken", status_code=303
            )

        media_rows = (
            conn.execute(
                select(media.c.id, media.c.storage_path).where(
                    media.c.user_id == me["id"]
                )
            )
            .mappings()
            .all()
        )

        for row in media_rows:
            old_storage = row["storage_path"]
            if not old_storage.startswith(f"{old_username}/"):
                continue

            filename = old_storage.split("/", 1)[1]
            src = uploads_root / old_storage
            dst = new_user_dir / filename
            dst.parent.mkdir(parents=True, exist_ok=True)

            if src.exists():
                if dst.exists() and dst != src:
                    base = Path(filename).stem
                    ext = Path(filename).suffix
                    n = 2
                    while True:
                        candidate = dst.parent / f"{base}-{n}{ext}"
                        if not candidate.exists():
                            dst = candidate
                            break
                        n += 1
                src.rename(dst)

            new_storage = f"{new_username}/{dst.name}"
            conn.execute(
                update(media)
                .where(media.c.id == row["id"], media.c.user_id == me["id"])
                .values(storage_path=new_storage)
            )

        conn.execute(
            update(users).where(users.c.id == me["id"]).values(username=new_username)
        )

    if old_user_dir.exists() and old_user_dir != new_user_dir:
        try:
            old_user_dir.rmdir()
        except OSError:
            pass

    return _saved_or_redirect(request, url="/settings?saved=username")


@router.post("/settings/css")
def settings_css(request: Request, custom_css: str = Form("")):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with get_engine(request).begin() as conn:
        conn.execute(
            update(users).where(users.c.id == me["id"]).values(custom_css=custom_css)
        )
    return _saved_or_redirect(request)


@router.post("/settings/html")
def settings_html(request: Request, custom_html: str = Form("")):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with get_engine(request).begin() as conn:
        conn.execute(
            update(users).where(users.c.id == me["id"]).values(custom_html=custom_html)
        )
    return _saved_or_redirect(request)


@router.post("/settings/guestbook")
def settings_guestbook(
    request: Request,
    guestbook_css: str = Form(""),
    guestbook_html: str = Form(""),
):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with get_engine(request).begin() as conn:
        conn.execute(
            update(users)
            .where(users.c.id == me["id"])
            .values(guestbook_css=guestbook_css, guestbook_html=guestbook_html)
        )
    return _saved_or_redirect(request)


@router.post("/settings/signature")
def settings_signature(request: Request, forum_signature: str = Form("")):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with get_engine(request).begin() as conn:
        conn.execute(
            update(users)
            .where(users.c.id == me["id"])
            .values(forum_signature=forum_signature[:200])
        )
    return _saved_or_redirect(request)


@router.post("/settings/card")
def settings_card(
    request: Request,
    headline: str = Form(""),
    content: str = Form(""),
    content_format: str = Form("html"),
    accent_color: str = Form("#00ffff"),
    border_style: str = Form("outset"),
    card_css: str = Form(""),
):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)

    with get_engine(request).begin() as conn:
        conn.execute(
            update(profile_cards)
            .where(profile_cards.c.user_id == me["id"])
            .values(
                headline=headline,
                content=content,
                content_format=content_format,
                accent_color=accent_color,
                border_style=border_style,
                card_css=card_css,
            )
        )
    return _saved_or_redirect(request)


def _invites_fragment(request: Request, me):
    with get_engine(request).begin() as conn:
        my_invites = get_invites_for_user(conn, me["id"])
    return templates.TemplateResponse(
        request, "fragments/invites.html", {"my_invites": my_invites}
    )


@router.post("/settings/invites")
def settings_invites(request: Request, max_uses: int = Form(1)):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)

    with get_engine(request).begin() as conn:
        code = create_invite(conn, me["id"], max_uses=max(1, min(50, max_uses)))

    if is_htmx(request):
        return _invites_fragment(request, me)
    return RedirectResponse(url=f"/settings?new_invite={code}", status_code=303)


@router.post("/settings/invites/{invite_id}/disable")
def settings_invite_disable(request: Request, invite_id: int):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with get_engine(request).begin() as conn:
        disable_invite(conn, invite_id, me["id"])

    if is_htmx(request):
        return _invites_fragment(request, me)
    return RedirectResponse(url="/settings", status_code=303)


@router.post("/settings/invites/{invite_id}/delete")
def settings_invite_delete(request: Request, invite_id: int):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with get_engine(request).begin() as conn:
        delete_invite(conn, invite_id, me["id"])

    if is_htmx(request):
        return _invites_fragment(request, me)
    return RedirectResponse(url="/settings", status_code=303)


@router.post("/settings/pages")
def settings_pages(
    request: Request,
    slug: str = Form(...),
    title: str = Form(...),
    content: str = Form(""),
    content_format: str = Form("html"),
    layout: str = Form("default"),
):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)

    from sqlalchemy.exc import IntegrityError

    try:
        with get_engine(request).begin() as conn:
            create_page(
                conn,
                user_id=me["id"],
                slug=slug.strip(),
                title=title.strip(),
                content=content,
                content_format=content_format,
                layout=layout,
                is_public=True,
            )
    except IntegrityError:
        return RedirectResponse(url="/settings?error=slug_taken", status_code=303)

    return RedirectResponse(
        url=f"/u/{me['username']}/page/{slug.strip()}", status_code=303
    )


@router.post("/settings/pages/{slug}/delete")
def settings_page_delete(request: Request, slug: str):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with get_engine(request).begin() as conn:
        delete_user_page(conn, me["id"], slug)
        if is_htmx(request):
            my_pages = list_pages_for_user(conn, me["id"])
            return templates.TemplateResponse(
                request,
                "fragments/pages_list.html",
                {"my_pages": my_pages, "username": me["username"]},
            )
    return RedirectResponse(url="/settings", status_code=303)


@router.get("/settings/pages/{slug}/edit", response_class=HTMLResponse)
def settings_pages_edit_get(request: Request, slug: str):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)

    with get_engine(request).begin() as conn:
        page = get_user_page(conn, me["id"], slug)
        media_items = list_media_for_user(conn, me["id"])

    if not page:
        raise HTTPException(404)

    return templates.TemplateResponse(
        request,
        "edit_page.html",
        {
            "me": me,
            "page": page,
            "media_items": media_items,
            "error": None,
        },
    )


@router.post("/settings/pages/{slug}/edit")
def settings_pages_edit_post(
    request: Request,
    slug: str,
    new_slug: str = Form(...),
    title: str = Form(...),
    content: str = Form(""),
    content_format: str = Form("html"),
    layout: str = Form("default"),
    is_public: str | None = Form(None),
):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)

    cleaned_slug = new_slug.strip()
    with get_engine(request).begin() as conn:
        page = get_user_page(conn, me["id"], slug)
        if not page:
            raise HTTPException(404)
        update_user_page(
            conn,
            me["id"],
            slug,
            slug=cleaned_slug,
            title=title.strip(),
            content=content,
            content_format=content_format,
            layout=layout,
            is_public=is_public == "on",
        )

    return RedirectResponse(
        url=f"/u/{me['username']}/page/{cleaned_slug}", status_code=303
    )
