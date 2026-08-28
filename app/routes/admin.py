"""Admin dashboard routes."""

import random
import secrets

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy import Integer, func, insert, select, update

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
from app.queries.site import get_site_banner
from app.queries.users import create_password_reset_token, get_user_by_id
from app.schema import (
    forum_posts,
    forum_threads,
    media,
    oauth2_audit_events,
    oauth2_clients,
    oauth2_tokens,
    pages,
    profile_cards,
    site_settings,
    users,
)
from app.security import hash_client_secret

router = APIRouter(tags=["admin"])

_CARD_COLORS = (
    "#ffd6a5",
    "#fdffb6",
    "#caffbf",
    "#9bf6ff",
    "#a0c4ff",
    "#bdb2ff",
    "#ffc6ff",
    "#ffadad",
    "#d0f4de",
    "#fefae0",
    "#fbc4ab",
    "#cdeac0",
)


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
                    users.c.in_webring,
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
        site_banner = get_site_banner(conn)

        oauth_clients = (
            conn.execute(
                select(
                    oauth2_clients,
                    func.count(oauth2_tokens.c.id).label("token_count"),
                    func.sum(
                        func.cast(oauth2_tokens.c.revoked.is_(False), Integer)
                    ).label("active_token_count"),
                    func.max(oauth2_tokens.c.issued_at).label("last_token_issued_at"),
                )
                .select_from(
                    oauth2_clients.outerjoin(
                        oauth2_tokens,
                        oauth2_tokens.c.client_id == oauth2_clients.c.client_id,
                    )
                )
                .group_by(oauth2_clients.c.id)
                .order_by(oauth2_clients.c.client_name)
            )
            .mappings()
            .all()
        )

    scheduler = getattr(request.app.state, "backup_scheduler", None)
    backup_summary = None
    if scheduler:
        backups = scheduler.list_backups()
        total_size = sum(b["db_size"] for b in backups)
        backup_summary = {
            "count": len(backups),
            "total_size": total_size,
            "last": scheduler.last_result,
            "latest_name": backups[0]["name"] if backups else None,
        }

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
            "backup_summary": backup_summary,
            "site_banner_settings": site_banner,
            "oauth_clients": oauth_clients,
        },
    )


def _oauth_client_or_404(conn, client_id: str):
    client = (
        conn.execute(
            select(oauth2_clients).where(oauth2_clients.c.client_id == client_id)
        )
        .mappings()
        .first()
    )
    if not client:
        raise HTTPException(404, "OAuth client not found")
    return client


def _oauth_audit(conn, event_type: str, client_id: str, actor_id: int, detail=""):
    conn.execute(
        insert(oauth2_audit_events).values(
            event_type=event_type,
            client_id=client_id,
            actor_user_id=actor_id,
            detail=detail,
        )
    )


def _secret_response(request: Request, secret: str, client_id: str) -> HTMLResponse:
    response = templates.TemplateResponse(
        request,
        "fragments/oauth_client_secret.html",
        {"client_id": client_id, "client_secret": secret},
    )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response


@router.post("/admin/oauth/clients/{client_id}/secret/generate")
def admin_generate_oauth_secret(request: Request, client_id: str):
    me = require_admin(request)
    secret = secrets.token_urlsafe(48)
    with get_engine(request).begin() as conn:
        client = _oauth_client_or_404(conn, client_id)
        if client["token_endpoint_auth_method"] == "none":
            raise HTTPException(400, "Public clients do not use a client secret")
        if client["client_secret_hash"]:
            raise HTTPException(
                409, "This client already has a secret; rotate it instead"
            )
        conn.execute(
            update(oauth2_clients)
            .where(oauth2_clients.c.client_id == client_id)
            .values(
                client_secret_hash=hash_client_secret(secret), updated_at=func.now()
            )
        )
        _oauth_audit(conn, "client_secret_generated", client_id, me["id"])
    return _secret_response(request, secret, client_id)


@router.post("/admin/oauth/clients/{client_id}/secret/rotate")
def admin_rotate_oauth_secret(request: Request, client_id: str):
    me = require_admin(request)
    secret = secrets.token_urlsafe(48)
    with get_engine(request).begin() as conn:
        client = _oauth_client_or_404(conn, client_id)
        if not client["client_secret_hash"]:
            raise HTTPException(409, "Generate the first secret before rotating it")
        conn.execute(
            update(oauth2_clients)
            .where(oauth2_clients.c.client_id == client_id)
            .values(
                previous_client_secret_hash=client["client_secret_hash"],
                client_secret_hash=hash_client_secret(secret),
                secret_rotated_at=func.now(),
                updated_at=func.now(),
            )
        )
        _oauth_audit(conn, "client_secret_rotated", client_id, me["id"])
    return _secret_response(request, secret, client_id)


@router.post("/admin/oauth/clients/{client_id}/secret/finish-rotation")
def admin_finish_oauth_secret_rotation(request: Request, client_id: str):
    me = require_admin(request)
    with get_engine(request).begin() as conn:
        _oauth_client_or_404(conn, client_id)
        conn.execute(
            update(oauth2_clients)
            .where(oauth2_clients.c.client_id == client_id)
            .values(previous_client_secret_hash="", updated_at=func.now())
        )
        _oauth_audit(conn, "client_secret_rotation_finished", client_id, me["id"])
    return RedirectResponse("/admin#oauth-clients", status_code=303)


@router.post("/admin/oauth/clients/{client_id}/revoke-tokens")
def admin_revoke_oauth_tokens(request: Request, client_id: str):
    me = require_admin(request)
    with get_engine(request).begin() as conn:
        _oauth_client_or_404(conn, client_id)
        result = conn.execute(
            update(oauth2_tokens)
            .where(
                oauth2_tokens.c.client_id == client_id,
                oauth2_tokens.c.revoked.is_(False),
            )
            .values(revoked=True)
        )
        _oauth_audit(conn, "tokens_revoked", client_id, me["id"], str(result.rowcount))
    return RedirectResponse("/admin#oauth-clients", status_code=303)


@router.post("/admin/oauth/clients/{client_id}/toggle-enabled")
def admin_toggle_oauth_client(request: Request, client_id: str):
    me = require_admin(request)
    with get_engine(request).begin() as conn:
        client = _oauth_client_or_404(conn, client_id)
        enabled = not client["is_enabled"]
        conn.execute(
            update(oauth2_clients)
            .where(oauth2_clients.c.client_id == client_id)
            .values(
                is_enabled=enabled,
                disabled_at=None if enabled else func.now(),
                updated_at=func.now(),
            )
        )
        if not enabled:
            conn.execute(
                update(oauth2_tokens)
                .where(oauth2_tokens.c.client_id == client_id)
                .values(revoked=True)
            )
        _oauth_audit(
            conn,
            "client_enabled" if enabled else "client_disabled",
            client_id,
            me["id"],
        )
    return RedirectResponse("/admin#oauth-clients", status_code=303)


@router.post("/admin/site-banner")
def admin_update_site_banner(
    request: Request,
    banner_enabled: str = Form(""),
    banner_html: str = Form(""),
    banner_css: str = Form(""),
):
    require_admin(request)
    with get_engine(request).begin() as conn:
        existing = get_site_banner(conn)
        values = {
            "banner_enabled": bool(banner_enabled),
            "banner_html": banner_html,
            "banner_css": banner_css,
        }
        if existing:
            conn.execute(
                update(site_settings).where(site_settings.c.id == 1).values(**values)
            )
        else:
            conn.execute(insert(site_settings).values(id=1, **values))
    return RedirectResponse(url="/admin", status_code=303)


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


@router.post("/admin/cards/randomize-default-colors")
def admin_randomize_default_card_colors(request: Request):
    """Give cards still using the default cyan background a curated color."""
    require_admin(request)
    with get_engine(request).begin() as conn:
        card_ids = (
            conn.execute(
                select(profile_cards.c.user_id).where(
                    profile_cards.c.accent_color == "#00ffff"
                )
            )
            .scalars()
            .all()
        )

        colors = list(_CARD_COLORS)
        random.SystemRandom().shuffle(colors)
        for index, user_id in enumerate(card_ids):
            conn.execute(
                update(profile_cards)
                .where(profile_cards.c.user_id == user_id)
                .values(accent_color=colors[index % len(colors)])
            )

    return RedirectResponse(
        url=f"/admin?randomized_cards={len(card_ids)}", status_code=303
    )


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
                    users.c.in_webring,
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
            {"u": u, "stats": stats, "reset_url": None, "detail_open": True},
        )
    return RedirectResponse(url="/admin", status_code=303)


def _admin_user_row_response(request, conn, user_id, reset_url=None):
    """Refetch user + stats and return the admin row fragment or redirect."""
    u = (
        conn.execute(
            select(
                users.c.id,
                users.c.username,
                users.c.display_name,
                users.c.is_admin,
                users.c.is_disabled,
                users.c.in_webring,
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
            {
                "u": u,
                "stats": stats,
                "reset_url": reset_url,
                "detail_open": True,
            },
        )
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/admin/users/{user_id}/toggle-webring")
def admin_toggle_webring(
    request: Request,
    user_id: int,
    in_webring: str | None = Form(None),
):
    require_admin(request)
    with get_engine(request).begin() as conn:
        user = get_user_by_id(conn, user_id)
        if not user:
            raise HTTPException(404)
        conn.execute(
            update(users)
            .where(users.c.id == user_id)
            .values(in_webring=in_webring == "on")
        )
        return _admin_user_row_response(request, conn, user_id)


@router.post("/admin/users/{user_id}/password-reset-link")
def admin_create_password_reset_link(request: Request, user_id: int):
    me = require_admin(request)
    with get_engine(request).begin() as conn:
        user = get_user_by_id(conn, user_id)
        if not user:
            raise HTTPException(404)
        token = create_password_reset_token(
            conn,
            user_id=user_id,
            created_by_user_id=me["id"],
            ttl_minutes=20,
        )

        reset_url = f"{deps.SITE_URL}/login/forgot-password?token={token}"

        if is_htmx(request):
            stats = (
                conn.execute(
                    select(
                        func.count(media.c.id).label("file_count"),
                        func.coalesce(func.sum(media.c.size_bytes), 0).label(
                            "total_bytes"
                        ),
                    ).where(media.c.user_id == user_id)
                )
                .mappings()
                .first()
            )
            return templates.TemplateResponse(
                request,
                "fragments/admin_user_row.html",
                {
                    "u": user,
                    "stats": stats,
                    "reset_url": reset_url,
                    "detail_open": True,
                },
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
                '<tr><td colspan="8" class="error">invalid username</td></tr>',
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
                    '<tr><td colspan="8" class="error">username taken</td></tr>',
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
                    users.c.in_webring,
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
            {"u": u, "stats": stats, "reset_url": None, "detail_open": True},
        )
    return RedirectResponse(url="/admin", status_code=303)
