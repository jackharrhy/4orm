"""Webring routes."""

import random

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.deps import get_engine, json_response, templates, wants_json
from app.models import WebringNeighbor, WebringResponse
from app.queries.users import get_user_by_username
from app.queries.widgets import get_webring_members, get_webring_neighbors

router = APIRouter(tags=["widgets"])


@router.get("/webring/random", summary="Random webring member")
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

    if wants_json(request):
        return json_response(
            WebringResponse(
                username=username,
                prev=WebringNeighbor(
                    username=prev_member["username"],
                    display_name=prev_member["display_name"],
                )
                if prev_member
                else None,
                next=WebringNeighbor(
                    username=next_member["username"],
                    display_name=next_member["display_name"],
                )
                if next_member
                else None,
            )
        )

    return templates.TemplateResponse(
        request,
        "webring.html",
        {"username": username, "prev": prev_member, "next": next_member},
    )
