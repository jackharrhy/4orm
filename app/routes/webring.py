import random

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.deps import get_engine, templates
from app.queries.users import get_user_by_username
from app.queries.widgets import get_webring_members, get_webring_neighbors

router = APIRouter()


@router.get("/webring/random")
def webring_random(request: Request):
    with get_engine(request).begin() as conn:
        members = get_webring_members(conn)
    if not members:
        raise HTTPException(404)
    member = random.choice(members)
    return RedirectResponse(url=f"/u/{member['username']}", status_code=302)


@router.get("/u/{username}/webring", response_class=HTMLResponse)
def webring_widget(request: Request, username: str):
    with get_engine(request).begin() as conn:
        user = get_user_by_username(conn, username)
        if not user:
            raise HTTPException(404)
        prev_member, next_member = get_webring_neighbors(conn, username)
    return templates.TemplateResponse(
        request,
        "webring.html",
        {"username": username, "prev": prev_member, "next": next_member},
    )
