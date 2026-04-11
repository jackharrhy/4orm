"""Admin dashboard routes."""

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import func, select, update

import app.deps as deps
from app.deps import (
    _saved_or_redirect,
    get_engine,
    is_htmx,
    rename_user_media,
    require_admin,
    templates,
)
from app.queries.admin import delete_user_prune, delete_user_reparent
from app.queries.users import get_user_by_id
from app.schema import forum_posts, forum_threads, media, pages, profile_cards, users

router = APIRouter(tags=["admin"])


@router.get("/admin", response_class=HTMLResponse, summary="Admin dashboard")
def admin_dashboard(request: Request):
    me = require_admin(request)
    with get_engine(request).begin() as conn:
        all_users = (
            conn.execute(
                select(
                    users.c.id,
                    users.c.username,
                    users.c.display_name,
                    users.c.is_admin,
                    users.c.is_disabled,
                    users.c.created_at,
                ).order_by(users.c.created_at)
            )
            .mappings()
            .all()
        )

        storage_stats = (
            conn.execute(
                select(
                    users.c.id,
                    users.c.username,
                    func.count(media.c.id).label("file_count"),
                    func.coalesce(func.sum(media.c.size_bytes), 0).label("total_bytes"),
                )
                .select_from(users.outerjoin(media, users.c.id == media.c.user_id))
                .group_by(users.c.id)
            )
            .mappings()
            .all()
        )
        storage_by_user = {s["id"]: s for s in storage_stats}

        cards = (
            conn.execute(select(profile_cards).order_by(profile_cards.c.user_id))
            .mappings()
            .all()
        )
        cards_by_user = {c["user_id"]: c for c in cards}

        all_pages = (
            conn.execute(
                select(
                    pages.c.id,
                    pages.c.user_id,
                    users.c.username,
                    pages.c.slug,
                    pages.c.title,
                    pages.c.content,
                    pages.c.is_public,
                    pages.c.content_format,
                    pages.c.updated_at,
                )
                .select_from(pages.join(users, pages.c.user_id == users.c.id))
                .order_by(pages.c.updated_at.desc())
            )
            .mappings()
            .all()
        )

        all_threads = (
            conn.execute(
                select(
                    forum_threads.c.id,
                    forum_threads.c.title,
                    forum_threads.c.is_pinned,
                    forum_threads.c.is_locked,
                    forum_threads.c.reply_count,
                    forum_threads.c.created_at,
                    users.c.username.label("author_username"),
                )
                .select_from(
                    forum_threads.join(users, forum_threads.c.author_id == users.c.id)
                )
                .order_by(forum_threads.c.created_at.desc())
            )
            .mappings()
            .all()
        )

        recent_posts = (
            conn.execute(
                select(
                    forum_posts.c.id,
                    forum_posts.c.thread_id,
                    forum_posts.c.content,
                    forum_posts.c.content_format,
                    forum_posts.c.created_at,
                    forum_posts.c.is_edited,
                    users.c.username.label("author_username"),
                    forum_threads.c.title.label("thread_title"),
                )
                .select_from(
                    forum_posts.join(users, forum_posts.c.author_id == users.c.id).join(
                        forum_threads, forum_posts.c.thread_id == forum_threads.c.id
                    )
                )
                .order_by(forum_posts.c.created_at.desc())
                .limit(100)
            )
            .mappings()
            .all()
        )

    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "me": me,
            "all_users": all_users,
            "storage_by_user": storage_by_user,
            "cards_by_user": cards_by_user,
            "all_pages": all_pages,
            "all_threads": all_threads,
            "recent_posts": recent_posts,
        },
    )


@router.post("/admin/users/{user_id}/profile")
def admin_update_user_profile(
    request: Request,
    user_id: int,
    display_name: str = Form(""),
    content: str = Form(""),
    content_format: str = Form("html"),
    custom_css: str = Form(""),
    custom_html: str = Form(""),
    layout: str = Form("default"),
):
    require_admin(request)
    with get_engine(request).begin() as conn:
        exists = conn.execute(select(users.c.id).where(users.c.id == user_id)).first()
        if not exists:
            raise HTTPException(404)
        conn.execute(
            update(users)
            .where(users.c.id == user_id)
            .values(
                display_name=display_name,
                content=content,
                content_format=content_format,
                custom_css=custom_css,
                custom_html=custom_html,
                layout=layout,
            )
        )
    return _saved_or_redirect(request)


@router.post("/admin/users/{user_id}/card")
def admin_update_user_card(
    request: Request,
    user_id: int,
    headline: str = Form(""),
    content: str = Form(""),
    content_format: str = Form("markdown"),
    accent_color: str = Form("#00ffff"),
    border_style: str = Form("outset"),
    card_css: str = Form(""),
):
    require_admin(request)
    with get_engine(request).begin() as conn:
        card = conn.execute(
            select(profile_cards.c.user_id).where(profile_cards.c.user_id == user_id)
        ).first()
        if not card:
            raise HTTPException(404)
        conn.execute(
            update(profile_cards)
            .where(profile_cards.c.user_id == user_id)
            .values(
                headline=headline,
                content=content,
                content_format=content_format,
                accent_color=accent_color,
                border_style=border_style,
                card_css=card_css,
            )
        )
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/admin/pages/{page_id}")
def admin_update_page(
    request: Request,
    page_id: int,
    slug: str = Form(...),
    title: str = Form(...),
    content: str = Form(""),
    content_format: str = Form("html"),
    is_public: str | None = Form(None),
):
    require_admin(request)
    with get_engine(request).begin() as conn:
        page = (
            conn.execute(select(pages).where(pages.c.id == page_id)).mappings().first()
        )
        if not page:
            raise HTTPException(404)
        conn.execute(
            update(pages)
            .where(pages.c.id == page_id)
            .values(
                slug=slug.strip(),
                title=title.strip(),
                content=content,
                content_format=content_format,
                is_public=is_public == "on",
                updated_at=func.now(),
            )
        )
    return RedirectResponse(url="/admin", status_code=303)


@router.get("/admin/orphans", response_class=HTMLResponse)
def admin_scan_orphans(request: Request):
    """Scan for orphaned files/records and return an HTML fragment."""
    require_admin(request)
    with get_engine(request).begin() as conn:
        db_paths = set(
            row[0] for row in conn.execute(select(media.c.storage_path)).fetchall()
        )

    orphaned_files = []
    if deps.UPLOADS_DIR.exists():
        for user_dir in deps.UPLOADS_DIR.iterdir():
            if not user_dir.is_dir() or user_dir.name.startswith("."):
                continue
            for f in user_dir.iterdir():
                if f.is_file() and not f.name.startswith("."):
                    rel = f"{user_dir.name}/{f.name}"
                    if rel not in db_paths:
                        orphaned_files.append({"path": rel, "size": f.stat().st_size})

    orphaned_records = []
    for p in db_paths:
        if not (deps.UPLOADS_DIR / p).exists():
            orphaned_records.append(p)

    return templates.TemplateResponse(
        request,
        "admin_orphans.html",
        {
            "orphaned_files": sorted(orphaned_files, key=lambda x: x["path"]),
            "orphaned_records": sorted(orphaned_records),
        },
    )


@router.post("/admin/cleanup/files")
def admin_cleanup_files(request: Request):
    """Delete orphaned files from disk that have no DB record."""
    require_admin(request)
    with get_engine(request).begin() as conn:
        db_paths = set(
            row[0] for row in conn.execute(select(media.c.storage_path)).fetchall()
        )
    removed = 0
    if deps.UPLOADS_DIR.exists():
        for user_dir in deps.UPLOADS_DIR.iterdir():
            if not user_dir.is_dir() or user_dir.name.startswith("."):
                continue
            for f in user_dir.iterdir():
                if f.is_file() and not f.name.startswith("."):
                    rel = f"{user_dir.name}/{f.name}"
                    if rel not in db_paths:
                        f.unlink()
                        removed += 1
    if is_htmx(request):
        return HTMLResponse(f'<p class="ok">deleted {removed} orphaned file(s).</p>')
    return RedirectResponse(url=f"/admin?cleaned_files={removed}", status_code=303)


@router.post("/admin/cleanup/records")
def admin_cleanup_records(request: Request):
    """Delete orphaned DB records whose files are missing from disk."""
    require_admin(request)
    removed = 0
    with get_engine(request).begin() as conn:
        all_paths = conn.execute(select(media.c.id, media.c.storage_path)).fetchall()
        for media_id, path in all_paths:
            if not (deps.UPLOADS_DIR / path).exists():
                conn.execute(media.delete().where(media.c.id == media_id))
                removed += 1
    if is_htmx(request):
        return HTMLResponse(f'<p class="ok">deleted {removed} orphaned record(s).</p>')
    return RedirectResponse(url=f"/admin?cleaned_records={removed}", status_code=303)


@router.post("/admin/users/{user_id}/toggle-admin")
def admin_toggle_admin(request: Request, user_id: int):
    require_admin(request)
    with get_engine(request).begin() as conn:
        user = get_user_by_id(conn, user_id)
        if not user:
            raise HTTPException(404)
        new_val = not user["is_admin"]
        conn.execute(
            update(users).where(users.c.id == user_id).values(is_admin=new_val)
        )
        # Refetch for the response
        u = (
            conn.execute(
                select(
                    users.c.id,
                    users.c.username,
                    users.c.display_name,
                    users.c.is_admin,
                    users.c.is_disabled,
                    users.c.created_at,
                ).where(users.c.id == user_id)
            )
            .mappings()
            .first()
        )
        stats = (
            conn.execute(
                select(
                    func.count(media.c.id).label("file_count"),
                    func.coalesce(func.sum(media.c.size_bytes), 0).label("total_bytes"),
                ).where(media.c.user_id == user_id)
            )
            .mappings()
            .first()
        )

    if is_htmx(request):
        return templates.TemplateResponse(
            request,
            "fragments/admin_user_row.html",
            {"u": u, "stats": stats},
        )
    return RedirectResponse(url="/admin", status_code=303)


def _admin_user_row_response(request, conn, user_id):
    """Refetch user + stats and return the admin row fragment or redirect."""
    u = (
        conn.execute(
            select(
                users.c.id,
                users.c.username,
                users.c.display_name,
                users.c.is_admin,
                users.c.is_disabled,
                users.c.created_at,
            ).where(users.c.id == user_id)
        )
        .mappings()
        .first()
    )
    stats = (
        conn.execute(
            select(
                func.count(media.c.id).label("file_count"),
                func.coalesce(func.sum(media.c.size_bytes), 0).label("total_bytes"),
            ).where(media.c.user_id == user_id)
        )
        .mappings()
        .first()
    )
    if is_htmx(request):
        return templates.TemplateResponse(
            request,
            "fragments/admin_user_row.html",
            {"u": u, "stats": stats},
        )
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/admin/users/{user_id}/rename")
def admin_rename_user(
    request: Request,
    user_id: int,
    new_username: str = Form(...),
    new_display_name: str = Form(""),
):
    require_admin(request)
    new_username = new_username.strip().lower()
    if not deps.USERNAME_RE.match(new_username):
        if is_htmx(request):
            return HTMLResponse(
                '<tr><td colspan="8" class="error">Invalid username</td></tr>',
                status_code=400,
            )
        return RedirectResponse(url="/admin", status_code=303)

    with get_engine(request).begin() as conn:
        user = get_user_by_id(conn, user_id)
        if not user:
            raise HTTPException(404)

        old_username = user["username"]

        # Always save display name if provided
        if new_display_name.strip():
            conn.execute(
                update(users)
                .where(users.c.id == user_id)
                .values(display_name=new_display_name.strip())
            )

        if old_username == new_username:
            return _admin_user_row_response(request, conn, user_id)

        # Check if taken
        existing = conn.execute(
            select(users.c.id).where(users.c.username == new_username)
        ).first()
        if existing:
            if is_htmx(request):
                return HTMLResponse(
                    '<tr><td colspan="8" class="error">Username taken</td></tr>',
                    status_code=400,
                )
            return RedirectResponse(url="/admin", status_code=303)

        rename_user_media(conn, user_id, old_username, new_username, deps.UPLOADS_DIR)

        conn.execute(
            update(users).where(users.c.id == user_id).values(username=new_username)
        )

    with get_engine(request).begin() as conn:
        return _admin_user_row_response(request, conn, user_id)


@router.get("/admin/export", summary="Export full site as zip", tags=["export"])
def admin_full_export(request: Request):
    """Export the entire 4orm site as a zip."""
    require_admin(request)
    from app.export import build_full_site_export_zip

    with get_engine(request).begin() as conn:
        zip_bytes = build_full_site_export_zip(
            conn=conn,
            uploads_dir=deps.UPLOADS_DIR,
            style_css_path=deps.BASE_DIR / "static" / "style.css",
            site_url="https://4orm.harrhy.xyz",
            templates_dir=deps.BASE_DIR / "templates",
        )
    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="4orm-export.zip"'},
    )


@router.post("/admin/users/{user_id}/delete")
def admin_delete_user(request: Request, user_id: int, mode: str = Form("reparent")):
    me = require_admin(request)
    if me["id"] == user_id:
        raise HTTPException(400)
    with get_engine(request).begin() as conn:
        user = get_user_by_id(conn, user_id)
        if not user:
            raise HTTPException(404)
        if mode == "prune":
            count = delete_user_prune(conn, user_id, deps.UPLOADS_DIR)
        else:
            delete_user_reparent(conn, user_id, deps.UPLOADS_DIR)
            count = 1
    if is_htmx(request):
        return HTMLResponse(f"<tr><td colspan='8'>deleted {count} user(s)</td></tr>")
    return RedirectResponse(url="/admin", status_code=303)


@router.get("/admin/backups", response_class=HTMLResponse)
def admin_list_backups(request: Request):
    require_admin(request)
    scheduler = request.app.state.backup_scheduler
    backups = scheduler.list_backups() if scheduler else []
    last = scheduler.last_result if scheduler else None
    return templates.TemplateResponse(
        request,
        "fragments/admin_backups.html",
        {"backups": backups, "last": last},
    )


@router.post("/admin/backups/run")
def admin_run_backup(request: Request):
    require_admin(request)
    scheduler = request.app.state.backup_scheduler
    if scheduler:
        result = scheduler.run_now()
        if is_htmx(request):
            status = (
                f"backup complete: {result['timestamp']}"
                if not result.get("error")
                else f"error: {result['error']}"
            )
            return HTMLResponse(f'<p class="ok">{status}</p>')
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/admin/users/{user_id}/toggle-disabled")
def admin_toggle_disabled(request: Request, user_id: int):
    require_admin(request)
    with get_engine(request).begin() as conn:
        user = get_user_by_id(conn, user_id)
        if not user:
            raise HTTPException(404)
        new_val = not bool(user["is_disabled"])
        conn.execute(
            update(users).where(users.c.id == user_id).values(is_disabled=new_val)
        )
        u = (
            conn.execute(
                select(
                    users.c.id,
                    users.c.username,
                    users.c.display_name,
                    users.c.is_admin,
                    users.c.is_disabled,
                    users.c.created_at,
                ).where(users.c.id == user_id)
            )
            .mappings()
            .first()
        )
        stats = (
            conn.execute(
                select(
                    func.count(media.c.id).label("file_count"),
                    func.coalesce(func.sum(media.c.size_bytes), 0).label("total_bytes"),
                ).where(media.c.user_id == user_id)
            )
            .mappings()
            .first()
        )

    if is_htmx(request):
        return templates.TemplateResponse(
            request,
            "fragments/admin_user_row.html",
            {"u": u, "stats": stats},
        )
    return RedirectResponse(url="/admin", status_code=303)
