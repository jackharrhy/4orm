"""Public page routes: profiles, pages, lineage, how-to, counter."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

import app.deps as deps
from app.deps import current_user, get_engine, templates
from app.export import build_export_zip
from app.queries.counter import get_total_views, increment_counter
from app.queries.pages import get_public_page, list_public_pages_for_user
from app.queries.users import get_invite_tree, get_user_by_username
from app.rendering import build_raw_html, render_content

router = APIRouter()


@router.get("/how-to", response_class=HTMLResponse)
def how_to(request: Request):
    return templates.TemplateResponse(
        request, "how_to.html", {"me": current_user(request)}
    )


@router.get("/u/{username}", response_class=HTMLResponse)
def profile(request: Request, username: str):
    with get_engine(request).begin() as conn:
        user = get_user_by_username(conn, username)
        if not user:
            raise HTTPException(404)
        pages = list_public_pages_for_user(conn, username)

    rendered_content = render_content(user["content"], user["content_format"])
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


@router.get("/u/{username}/page/{slug}", response_class=HTMLResponse)
def page_view(request: Request, username: str, slug: str):
    with get_engine(request).begin() as conn:
        page = get_public_page(conn, username, slug)
    if not page:
        raise HTTPException(404)

    rendered_content = render_content(page["content"], page["content_format"])
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


@router.get("/u/{username}/counter", response_class=HTMLResponse)
def counter_view(request: Request, username: str):
    with get_engine(request).begin() as conn:
        owner = get_user_by_username(conn, username)
        if not owner:
            raise HTTPException(404)
        increment_counter(conn, owner["id"])
        total_views = get_total_views(conn, owner["id"])

    return templates.TemplateResponse(
        request,
        "counter.html",
        {"owner": owner, "total_views": total_views, "me": current_user(request)},
    )


@router.get("/lineage", response_class=HTMLResponse)
def lineage(request: Request):
    with get_engine(request).begin() as conn:
        tree = get_invite_tree(conn)
    return templates.TemplateResponse(
        request,
        "lineage.html",
        {"tree": tree, "me": current_user(request)},
    )


@router.get("/u/{username}/export")
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
