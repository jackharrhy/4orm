"""Public page routes: profiles, pages, lineage, how-to, counter, status, player."""

import time as _time
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

import app.deps as deps
from app.deps import current_user, get_engine, json_response, templates, wants_json
from app.export import build_export_zip
from app.models import (
    CounterResponse,
    LineageNode,
    LineageResponse,
    PageDetail,
    PageSummary,
    PlayerResponse,
    PlayerTrack,
    ProfileResponse,
    StatusResponse,
)
from app.queries.counter import get_total_views, increment_counter
from app.queries.pages import get_public_page, list_public_pages_for_user
from app.queries.users import get_invite_tree, get_user_by_username
from app.queries.widgets import get_playlist
from app.rendering import build_raw_html, render_content

router = APIRouter(tags=["profiles"])


@router.get("/how-to", response_class=HTMLResponse, summary="How-to guide")
def how_to(request: Request):
    return templates.TemplateResponse(
        request, "how_to.html", {"me": current_user(request)}
    )


@router.get("/u/{username}", response_class=HTMLResponse, summary="User profile")
def profile(request: Request, username: str):
    with get_engine(request).begin() as conn:
        user = get_user_by_username(conn, username)
        if not user:
            raise HTTPException(404)
        pages = list_public_pages_for_user(conn, username)

    rendered_content = render_content(user["content"], user["content_format"])

    if wants_json(request):
        return json_response(
            ProfileResponse(
                username=user["username"],
                display_name=user["display_name"],
                content=user["content"] or "",
                content_format=user["content_format"] or "html",
                rendered_content=rendered_content,
                custom_css=user["custom_css"] or "",
                custom_html=user["custom_html"] or "",
                layout=user.get("layout") or "default",
                pages=[
                    PageSummary(
                        slug=p["slug"],
                        title=p["title"],
                        is_public=p["is_public"],
                        layout=p.get("layout", "default"),
                        created_at=p.get("created_at"),
                        updated_at=p.get("updated_at"),
                    )
                    for p in pages
                ],
            )
        )

    layout = user.get("layout", "default")

    if layout == "raw":
        data = {
            "username": user["username"],
            "display_name": user["display_name"],
            "pages": [{"slug": p["slug"], "title": p["title"]} for p in pages],
            "lineage_url": f"/lineage#user-{user['username']}",
        }
        return HTMLResponse(
            build_raw_html(
                rendered_content,
                custom_css=user["custom_css"],
                custom_html=user["custom_html"],
                data=data,
            )
        )

    if layout == "simple":
        template_name = "profile_simple.html"
    elif layout == "cssonly":
        template_name = "profile_cssonly.html"
    else:
        template_name = "profile.html"
    return templates.TemplateResponse(
        request,
        template_name,
        {
            "profile": user,
            "rendered_content": rendered_content,
            "pages": pages,
            "me": current_user(request),
        },
    )


@router.get(
    "/u/{username}/page/{slug}", response_class=HTMLResponse, summary="View a user page"
)
def page_view(request: Request, username: str, slug: str):
    with get_engine(request).begin() as conn:
        page = get_public_page(conn, username, slug)
    if not page:
        raise HTTPException(404)

    rendered_content = render_content(page["content"], page["content_format"])

    if wants_json(request):
        return json_response(
            PageDetail(
                slug=page.get("slug", slug),
                title=page["title"],
                content=page["content"] or "",
                content_format=page["content_format"] or "html",
                rendered_content=rendered_content,
                layout=page.get("layout") or "default",
                is_public=page.get("is_public", True),
                username=page["username"],
                display_name=page["display_name"],
                custom_css=page.get("custom_css") or "",
                custom_html=page.get("custom_html") or "",
            )
        )

    layout = page.get("layout", "default")

    if layout == "raw":
        return HTMLResponse(
            build_raw_html(
                rendered_content,
                custom_css=page["custom_css"],
                custom_html=page["custom_html"],
            )
        )

    if layout == "simple":
        template_name = "page_simple.html"
    elif layout == "cssonly":
        template_name = "page_cssonly.html"
    else:
        template_name = "page.html"
    return templates.TemplateResponse(
        request,
        template_name,
        {
            "page": page,
            "rendered_content": rendered_content,
            "me": current_user(request),
        },
    )


_counter_seen: dict[str, float] = {}  # "ip:username" -> last_seen timestamp
_COUNTER_COOLDOWN = 60  # seconds per IP per user


@router.get(
    "/u/{username}/counter",
    response_class=HTMLResponse,
    summary="Hit counter widget",
    tags=["widgets"],
)
def counter_view(request: Request, username: str):
    with get_engine(request).begin() as conn:
        owner = get_user_by_username(conn, username)
        if not owner:
            raise HTTPException(404)

        # Rate limit: one count per IP per user per cooldown period
        should_increment = True
        if not getattr(request.app.state, "testing", False):
            client_ip = request.client.host if request.client else "unknown"
            cache_key = f"{client_ip}:{username}"
            now = _time.monotonic()
            last = _counter_seen.get(cache_key, 0)
            if now - last < _COUNTER_COOLDOWN:
                should_increment = False
            else:
                _counter_seen[cache_key] = now

        if should_increment:
            increment_counter(conn, owner["id"])

        total_views = get_total_views(conn, owner["id"])

    if wants_json(request):
        return json_response(
            CounterResponse(username=username, total_views=total_views)
        )

    return templates.TemplateResponse(
        request,
        "counter.html",
        {"owner": owner, "total_views": total_views, "me": current_user(request)},
    )


@router.get("/lineage", response_class=HTMLResponse, summary="Invite tree")
def lineage(request: Request):
    with get_engine(request).begin() as conn:
        tree = get_invite_tree(conn)

    if wants_json(request):

        def node_to_dict(n):
            return LineageNode(
                username=n["username"],
                display_name=n["display_name"],
                children=[node_to_dict(c) for c in n.get("children", [])],
            )

        return json_response(LineageResponse(tree=[node_to_dict(r) for r in tree]))

    return templates.TemplateResponse(
        request,
        "lineage.html",
        {"tree": tree, "me": current_user(request)},
    )


@router.get("/u/{username}/export", summary="Export user site as zip", tags=["export"])
def export_site(request: Request, username: str):
    me = current_user(request)
    with get_engine(request).begin() as conn:
        user = get_user_by_username(conn, username)
        if not user:
            raise HTTPException(404)
        if not me or (me["id"] != user["id"] and not me.get("is_admin")):
            raise HTTPException(403)
        zip_bytes = build_export_zip(
            conn=conn,
            username=username,
            uploads_dir=deps.UPLOADS_DIR,
            style_css_path=deps.BASE_DIR / "static" / "style.css",
            site_url="https://4orm.harrhy.xyz",
            templates_dir=deps.BASE_DIR / "templates",
        )
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{username}-export.zip"'
        },
    )


@router.get(
    "/u/{username}/status",
    response_class=HTMLResponse,
    summary="Status widget",
    tags=["widgets"],
)
def status_widget(request: Request, username: str):
    with get_engine(request).begin() as conn:
        user = get_user_by_username(conn, username)
        if not user:
            raise HTTPException(404)

    relative_time = ""
    updated = user.get("status_updated_at")
    if updated:
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=UTC)
        delta = datetime.now(UTC) - updated
        seconds = int(delta.total_seconds())
        if seconds < 60:
            relative_time = "just now"
        elif seconds < 3600:
            relative_time = f"{seconds // 60}m ago"
        elif seconds < 86400:
            relative_time = f"{seconds // 3600}h ago"
        else:
            relative_time = f"{seconds // 86400}d ago"

    if wants_json(request):
        return json_response(
            StatusResponse(
                username=username,
                status_emoji=user.get("status_emoji") or "",
                status_text=user.get("status_text") or "",
                relative_time=relative_time,
            )
        )

    return templates.TemplateResponse(
        request,
        "status.html",
        {"owner": user, "relative_time": relative_time},
    )


@router.get(
    "/u/{username}/player",
    response_class=HTMLResponse,
    summary="Music player widget",
    tags=["widgets"],
)
def player_widget(request: Request, username: str):
    with get_engine(request).begin() as conn:
        user = get_user_by_username(conn, username)
        if not user:
            raise HTTPException(404)
        tracks = get_playlist(conn, user["id"])

    if wants_json(request):
        return json_response(
            PlayerResponse(
                username=username,
                tracks=[
                    PlayerTrack(
                        id=t["id"],
                        title=t.get("title"),
                        storage_path=t["storage_path"],
                        mime_type=t.get("mime_type", ""),
                    )
                    for t in tracks
                ],
            )
        )

    return templates.TemplateResponse(
        request,
        "player.html",
        {"owner": user, "tracks": tracks},
    )
