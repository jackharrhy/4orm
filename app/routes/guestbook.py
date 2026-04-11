"""Guestbook routes."""

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.deps import (
    current_user,
    get_engine,
    is_htmx,
    json_response,
    templates,
    wants_json,
)
from app.models import GuestbookEntry, GuestbookResponse, SuccessResponse
from app.push import send_notification
from app.queries.guestbook import (
    create_guestbook_entry,
    delete_guestbook_entry,
    list_guestbook_entries,
)
from app.queries.users import get_user_by_username

router = APIRouter(tags=["widgets"])


@router.get(
    "/guestbook-universe",
    response_class=HTMLResponse,
    summary="All guestbooks in one page",
)
def guestbook_universe(request: Request):
    from sqlalchemy import select

    from app.schema import users

    with get_engine(request).begin() as conn:
        all_users = (
            conn.execute(
                select(users.c.username, users.c.display_name)
                .where(users.c.is_disabled == False)  # noqa: E712
                .order_by(users.c.created_at)
            )
            .mappings()
            .all()
        )
    return templates.TemplateResponse(
        request,
        "guestbook_universe.html",
        {"me": current_user(request), "all_users": all_users},
    )


@router.get(
    "/u/{username}/guestbook", response_class=HTMLResponse, summary="View guestbook"
)
def guestbook_view(request: Request, username: str):
    with get_engine(request).begin() as conn:
        owner = get_user_by_username(conn, username)
        if not owner:
            raise HTTPException(404)
        entries = list_guestbook_entries(conn, owner["id"])
    me = current_user(request)
    is_owner = me and me["id"] == owner["id"]

    if wants_json(request):
        return json_response(
            GuestbookResponse(
                owner_username=owner["username"],
                entries=[
                    GuestbookEntry(
                        id=e["id"],
                        author_username=e["author_username"],
                        author_display_name=e["author_display_name"],
                        message=e["message"],
                        created_at=e.get("created_at"),
                    )
                    for e in entries
                ],
                can_post=me is not None,
            )
        )

    return templates.TemplateResponse(
        request,
        "guestbook.html",
        {
            "owner": owner,
            "entries": entries,
            "me": me,
            "is_owner": is_owner,
        },
    )


@router.post(
    "/u/{username}/guestbook",
    response_class=HTMLResponse,
    summary="Sign guestbook",
)
def guestbook_post(request: Request, username: str, message: str = Form(...)):
    me = current_user(request)
    if not me:
        raise HTTPException(403)
    with get_engine(request).begin() as conn:
        owner = get_user_by_username(conn, username)
        if not owner:
            raise HTTPException(404)
        create_guestbook_entry(conn, owner["id"], me["id"], message)

        # Notify guestbook owner (if different from poster)
        if owner["id"] != me["id"]:
            send_notification(
                conn,
                owner["id"],
                "New guestbook entry",
                f"{me['display_name']} signed your guestbook",
                f"/u/{username}/guestbook",
            )

        entries = list_guestbook_entries(conn, owner["id"])
    is_owner = me["id"] == owner["id"]
    if wants_json(request):
        return json_response(SuccessResponse(message="entry added"))
    if is_htmx(request):
        return templates.TemplateResponse(
            request,
            "fragments/guestbook_entries.html",
            {"owner": owner, "entries": entries, "me": me, "is_owner": is_owner},
        )
    return RedirectResponse(url=f"/u/{username}/guestbook", status_code=303)


@router.post("/u/{username}/guestbook/{entry_id}/delete", response_class=HTMLResponse)
def guestbook_delete(request: Request, username: str, entry_id: int):
    me = current_user(request)
    if not me:
        raise HTTPException(403)
    with get_engine(request).begin() as conn:
        owner = get_user_by_username(conn, username)
        if not owner or me["id"] != owner["id"]:
            raise HTTPException(403)
        delete_guestbook_entry(conn, entry_id, owner["id"])
        entries = list_guestbook_entries(conn, owner["id"])
    if wants_json(request):
        return json_response(SuccessResponse(message="entry deleted"))
    if is_htmx(request):
        return templates.TemplateResponse(
            request,
            "fragments/guestbook_entries.html",
            {"owner": owner, "entries": entries, "me": me, "is_owner": True},
        )
    return RedirectResponse(url=f"/u/{username}/guestbook", status_code=303)
