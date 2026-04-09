"""Guestbook routes."""

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.deps import current_user, get_engine, is_htmx, templates
from app.push import send_notification
from app.queries.guestbook import (
    create_guestbook_entry,
    delete_guestbook_entry,
    list_guestbook_entries,
)
from app.queries.users import get_user_by_username

router = APIRouter()


@router.get("/u/{username}/guestbook", response_class=HTMLResponse)
def guestbook_view(request: Request, username: str):
    with get_engine(request).begin() as conn:
        owner = get_user_by_username(conn, username)
        if not owner:
            raise HTTPException(404)
        entries = list_guestbook_entries(conn, owner["id"])
    me = current_user(request)
    is_owner = me and me["id"] == owner["id"]
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


@router.post("/u/{username}/guestbook", response_class=HTMLResponse)
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
    if is_htmx(request):
        return templates.TemplateResponse(
            request,
            "fragments/guestbook_entries.html",
            {"owner": owner, "entries": entries, "me": me, "is_owner": True},
        )
    return RedirectResponse(url=f"/u/{username}/guestbook", status_code=303)
