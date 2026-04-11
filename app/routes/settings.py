"""User settings routes."""

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select, update

import app.deps as deps
from app.deps import (
    USERNAME_INVALID_MSG,
    _error_or_redirect,
    _saved_or_redirect,
    get_engine,
    is_htmx,
    rename_user_media,
    require_user,
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
from app.queries.widgets import (
    add_to_playlist,
    get_playlist,
    move_playlist_item,
    remove_from_playlist,
)
from app.schema import media, profile_cards, users

router = APIRouter()


@router.get("/settings", response_class=HTMLResponse)
def settings_get(request: Request):
    me, redirect = require_user(request)
    if redirect:
        return redirect
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
        playlist = get_playlist(conn, me["id"])
        audio_items = (
            conn.execute(
                select(media)
                .where(
                    media.c.user_id == me["id"],
                    media.c.mime_type.like("audio%"),
                )
                .order_by(media.c.created_at.desc())
            )
            .mappings()
            .all()
        )
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
            "playlist": playlist,
            "audio_items": audio_items,
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
    me, redirect = require_user(request)
    if redirect:
        return redirect
    with get_engine(request).begin() as conn:
        conn.execute(
            update(users)
            .where(users.c.id == me["id"])
            .values(
                display_name=display_name,
                content=content,
                content_format=content_format,
                layout=layout,
                updated_at=func.now(),
            )
        )
    return _saved_or_redirect(request)


@router.post("/settings/username")
def settings_username(request: Request, username: str = Form(...)):
    me, redirect = require_user(request)
    if redirect:
        return redirect

    new_username = username.strip().lower()
    if not deps.USERNAME_RE.match(new_username):
        response, _ = _error_or_redirect(
            request,
            USERNAME_INVALID_MSG,
            "/settings?error=invalid_username",
        )
        return response

    if new_username == me["username"]:
        return _saved_or_redirect(request)

    old_username = me["username"]

    with get_engine(request).begin() as conn:
        existing = conn.execute(
            select(users.c.id).where(users.c.username == new_username)
        ).first()
        if existing:
            response, _ = _error_or_redirect(
                request,
                "That username is already taken",
                "/settings?error=username_taken",
            )
            return response

        rename_user_media(conn, me["id"], old_username, new_username, deps.UPLOADS_DIR)

        conn.execute(
            update(users)
            .where(users.c.id == me["id"])
            .values(username=new_username, updated_at=func.now())
        )

    return _saved_or_redirect(request, url="/settings?saved=username")


@router.post("/settings/css")
def settings_css(request: Request, custom_css: str = Form("")):
    me, redirect = require_user(request)
    if redirect:
        return redirect
    with get_engine(request).begin() as conn:
        conn.execute(
            update(users)
            .where(users.c.id == me["id"])
            .values(custom_css=custom_css, updated_at=func.now())
        )
    return _saved_or_redirect(request)


@router.post("/settings/html")
def settings_html(request: Request, custom_html: str = Form("")):
    me, redirect = require_user(request)
    if redirect:
        return redirect
    with get_engine(request).begin() as conn:
        conn.execute(
            update(users)
            .where(users.c.id == me["id"])
            .values(custom_html=custom_html, updated_at=func.now())
        )
    return _saved_or_redirect(request)


@router.post("/settings/guestbook")
def settings_guestbook(
    request: Request,
    guestbook_css: str = Form(""),
    guestbook_html: str = Form(""),
):
    me, redirect = require_user(request)
    if redirect:
        return redirect
    with get_engine(request).begin() as conn:
        conn.execute(
            update(users)
            .where(users.c.id == me["id"])
            .values(
                guestbook_css=guestbook_css,
                guestbook_html=guestbook_html,
                updated_at=func.now(),
            )
        )
    return _saved_or_redirect(request)


@router.post("/settings/counter")
def settings_counter(
    request: Request,
    counter_css: str = Form(""),
    counter_html: str = Form(""),
):
    me, redirect = require_user(request)
    if redirect:
        return redirect
    with get_engine(request).begin() as conn:
        conn.execute(
            update(users)
            .where(users.c.id == me["id"])
            .values(
                counter_css=counter_css,
                counter_html=counter_html,
                updated_at=func.now(),
            )
        )
    return _saved_or_redirect(request)


@router.post("/settings/webring")
def settings_webring(request: Request, in_webring: str | None = Form(None)):
    me, redirect = require_user(request)
    if redirect:
        return redirect
    with get_engine(request).begin() as conn:
        conn.execute(
            update(users)
            .where(users.c.id == me["id"])
            .values(in_webring=in_webring == "on", updated_at=func.now())
        )
    return _saved_or_redirect(request)


@router.post("/settings/status")
def settings_status(
    request: Request,
    status_emoji: str = Form(""),
    status_text: str = Form(""),
    status_css: str = Form(""),
    status_html: str = Form(""),
):
    me, redirect = require_user(request)
    if redirect:
        return redirect
    with get_engine(request).begin() as conn:
        conn.execute(
            update(users)
            .where(users.c.id == me["id"])
            .values(
                status_emoji=status_emoji[:10],
                status_text=status_text[:140],
                status_css=status_css,
                status_html=status_html,
                status_updated_at=func.now(),
                updated_at=func.now(),
            )
        )
    return _saved_or_redirect(request)


@router.post("/settings/player")
def settings_player(
    request: Request,
    player_css: str = Form(""),
    player_html: str = Form(""),
):
    me, redirect = require_user(request)
    if redirect:
        return redirect
    with get_engine(request).begin() as conn:
        conn.execute(
            update(users)
            .where(users.c.id == me["id"])
            .values(
                player_css=player_css, player_html=player_html, updated_at=func.now()
            )
        )
    return _saved_or_redirect(request)


def _playlist_fragment(request, me):
    with get_engine(request).begin() as conn:
        playlist = get_playlist(conn, me["id"])
        audio_items = (
            conn.execute(
                select(media).where(
                    media.c.user_id == me["id"],
                    media.c.mime_type.like("audio%"),
                )
            )
            .mappings()
            .all()
        )
    return templates.TemplateResponse(
        request,
        "fragments/playlist.html",
        {"playlist": playlist, "audio_items": audio_items},
    )


@router.post("/settings/player/add")
def settings_player_add(request: Request, media_id: int = Form(...)):
    me, redirect = require_user(request)
    if redirect:
        return redirect
    with get_engine(request).begin() as conn:
        add_to_playlist(conn, me["id"], media_id)
    if is_htmx(request):
        return _playlist_fragment(request, me)
    return RedirectResponse(url="/settings", status_code=303)


@router.post("/settings/player/{item_id}/remove")
def settings_player_remove(request: Request, item_id: int):
    me, redirect = require_user(request)
    if redirect:
        return redirect
    with get_engine(request).begin() as conn:
        remove_from_playlist(conn, item_id, me["id"])
    if is_htmx(request):
        return _playlist_fragment(request, me)
    return RedirectResponse(url="/settings", status_code=303)


@router.post("/settings/player/{item_id}/move")
def settings_player_move(request: Request, item_id: int, direction: str = Form(...)):
    me, redirect = require_user(request)
    if redirect:
        return redirect
    with get_engine(request).begin() as conn:
        move_playlist_item(conn, item_id, me["id"], direction)
    if is_htmx(request):
        return _playlist_fragment(request, me)
    return RedirectResponse(url="/settings", status_code=303)


@router.post("/settings/notifications")
def settings_notifications(
    request: Request,
    notifications_enabled: str | None = Form(None),
    watch_all_threads: str | None = Form(None),
):
    me, redirect = require_user(request)
    if redirect:
        return redirect
    with get_engine(request).begin() as conn:
        conn.execute(
            update(users)
            .where(users.c.id == me["id"])
            .values(
                notifications_enabled=notifications_enabled == "on",
                watch_all_threads=watch_all_threads == "on",
            )
        )
    return _saved_or_redirect(request)


@router.post("/settings/notifications/test")
def settings_notifications_test(request: Request):
    from app.push import send_notification

    me, redirect = require_user(request)
    if redirect:
        return redirect
    with get_engine(request).begin() as conn:
        send_notification(
            conn,
            me["id"],
            "4orm test notification",
            "if you see this, push notifications are working!",
            "/settings",
        )
    if is_htmx(request):
        return HTMLResponse('<span class="ok">sent!</span>')
    return RedirectResponse(url="/settings", status_code=303)


@router.post("/settings/signature")
def settings_signature(request: Request, forum_signature: str = Form("")):
    me, redirect = require_user(request)
    if redirect:
        return redirect
    with get_engine(request).begin() as conn:
        conn.execute(
            update(users)
            .where(users.c.id == me["id"])
            .values(forum_signature=forum_signature[:200], updated_at=func.now())
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
    me, redirect = require_user(request)
    if redirect:
        return redirect

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
                updated_at=func.now(),
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
    me, redirect = require_user(request)
    if redirect:
        return redirect

    with get_engine(request).begin() as conn:
        code = create_invite(conn, me["id"], max_uses=max(1, min(50, max_uses)))

    if is_htmx(request):
        return _invites_fragment(request, me)
    return RedirectResponse(url=f"/settings?new_invite={code}", status_code=303)


@router.post("/settings/invites/{invite_id}/disable")
def settings_invite_disable(request: Request, invite_id: int):
    me, redirect = require_user(request)
    if redirect:
        return redirect
    with get_engine(request).begin() as conn:
        disable_invite(conn, invite_id, me["id"])

    if is_htmx(request):
        return _invites_fragment(request, me)
    return RedirectResponse(url="/settings", status_code=303)


@router.post("/settings/invites/{invite_id}/delete")
def settings_invite_delete(request: Request, invite_id: int):
    me, redirect = require_user(request)
    if redirect:
        return redirect
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
    me, redirect = require_user(request)
    if redirect:
        return redirect

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
    me, redirect = require_user(request)
    if redirect:
        return redirect
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
    me, redirect = require_user(request)
    if redirect:
        return redirect

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
    me, redirect = require_user(request)
    if redirect:
        return redirect

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

    if is_htmx(request):
        return templates.TemplateResponse(request, "fragments/saved.html")
    return RedirectResponse(
        url=f"/u/{me['username']}/page/{cleaned_slug}", status_code=303
    )
