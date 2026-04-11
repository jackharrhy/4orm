import contextlib
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.backup import BackupScheduler
from app.db import engine as default_engine
from app.deps import BASE_DIR, LoginRequired, current_user, get_engine, templates
from app.queries.forum import recent_forum_posts
from app.queries.users import list_profile_cards
from app.rendering import render_content, render_forum_post
from app.routes import (
    admin,
    auth,
    feeds,
    forum,
    guestbook,
    media,
    pages,
    push,
    settings,
    webring,
)
from app.schema import create_all


@asynccontextmanager
async def lifespan(application: FastAPI):
    from alembic.config import Config

    from alembic import command

    engine = application.state.engine
    alembic_cfg = Config("alembic.ini")

    with engine.connect() as conn:
        has_tables = conn.dialect.has_table(conn, "users")

    if not has_tables:
        create_all(engine)
        command.stamp(alembic_cfg, "head")
    else:
        command.upgrade(alembic_cfg, "head")

    backup_dir = BASE_DIR / "backups"
    backup_dir.mkdir(exist_ok=True)
    scheduler = BackupScheduler(
        db_path=BASE_DIR / "data" / "4orm.db",
        uploads_dir=BASE_DIR / "uploads",
        backup_dir=backup_dir,
    )
    application.state.backup_scheduler = scheduler
    scheduler.start()

    yield

    scheduler.stop()


_CSRF_EXEMPT_PATHS = {"/login"}


class CSRFMiddleware(BaseHTTPMiddleware):
    """Reject state-changing requests that lack a valid CSRF token."""

    async def dispatch(self, request: Request, call_next):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return await call_next(request)

        path = request.url.path
        if path in _CSRF_EXEMPT_PATHS or path.endswith("/feed.xml"):
            return await call_next(request)

        session_token = request.session.get("csrf_token")
        if not session_token:
            return PlainTextResponse("CSRF token missing", status_code=403)

        # Check header first (htmx / fetch)
        if request.headers.get("X-CSRF-Token") == session_token:
            return await call_next(request)

        return PlainTextResponse("CSRF token mismatch", status_code=403)


def _custom_operation_id(route: APIRoute) -> str:
    if route.tags:
        return f"{route.tags[0]}_{route.name}"
    return route.name


tags_metadata = [
    {
        "name": "auth",
        "description": "Authentication: login, register, logout, trust agreement",
    },
    {"name": "profiles", "description": "User profiles, pages, lineage tree"},
    {"name": "forum", "description": "Forum threads, posts, and moderation"},
    {
        "name": "settings",
        "description": "User settings: profile, CSS, HTML, card, widgets",
    },
    {"name": "media", "description": "Media library: upload, rename, delete"},
    {"name": "admin", "description": "Admin dashboard, user management, backups"},
    {
        "name": "widgets",
        "description": (
            "Embeddable widgets: guestbook, counter, status, player, webring"
        ),
    },
    {"name": "feeds", "description": "RSS feeds for pages and forum"},
    {"name": "push", "description": "Web Push notification subscriptions"},
    {"name": "export", "description": "Export user sites and full site snapshots"},
]

app = FastAPI(
    title="4orm",
    summary="a retro community platform",
    description=(
        "4orm is a retro-web community platform where users customize "
        "their profiles and pages with HTML, CSS, and JavaScript. "
        "Features include a forum with BBCode and Markdown support, "
        "embeddable widgets (guestbook, counter, music player, status, "
        "webring), an invite tree, media uploads, and push notifications."
    ),
    version="0.1.0",
    lifespan=lifespan,
    openapi_tags=tags_metadata,
    generate_unique_id_function=_custom_operation_id,
)


@app.exception_handler(LoginRequired)
async def _handle_login_required(_request, _exc):
    return RedirectResponse(url="/login", status_code=303)


app.state.engine = default_engine


# Middleware order: last added = outermost = runs first on request.
# SessionMiddleware must run before CSRFMiddleware so the session is
# available when we check the token.  Adding CSRF first, then Session
# means Session is outer and loads the session before CSRF executes.
app.add_middleware(CSRFMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SECRET_KEY", "dev-key-change-in-production"),
)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/uploads", StaticFiles(directory=BASE_DIR / "uploads"), name="uploads")

# Include all route modules
app.include_router(auth.router)
app.include_router(pages.router)
app.include_router(settings.router)
app.include_router(media.router)
app.include_router(admin.router)
app.include_router(guestbook.router)
app.include_router(feeds.router)
app.include_router(forum.router)
app.include_router(webring.router)
app.include_router(push.router)


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    """Serve the service worker from root scope."""
    from fastapi.responses import FileResponse

    return FileResponse(
        BASE_DIR / "static" / "sw.js",
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


ERROR_MESSAGES = {
    400: "bad request.",
    403: "you don't have permission to access this.",
    404: "this page doesn't exist.",
    500: "something broke. sorry about that.",
}


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    me = None
    with contextlib.suppress(Exception):
        me = current_user(request)
    message = ERROR_MESSAGES.get(exc.status_code, exc.detail)
    return templates.TemplateResponse(
        request,
        "error.html",
        {"status_code": exc.status_code, "message": message, "me": me},
        status_code=exc.status_code,
    )


@app.exception_handler(500)
async def internal_error_handler(request: Request, exc: Exception):
    me = None
    with contextlib.suppress(Exception):
        me = current_user(request)
    return templates.TemplateResponse(
        request,
        "error.html",
        {"status_code": 500, "message": ERROR_MESSAGES[500], "me": me},
        status_code=500,
    )


@app.get("/", response_class=HTMLResponse, summary="Homepage", tags=["profiles"])
def home(request: Request):
    with get_engine(request).begin() as conn:
        raw_cards = list_profile_cards(conn)
        raw_recent = recent_forum_posts(conn, hours=2, limit=5)
    cards = [
        {
            **card,
            "rendered_content": render_content(card["content"], card["content_format"]),
        }
        for card in raw_cards
    ]
    recent_posts = [
        {
            **post,
            "rendered_content": render_forum_post(
                post["content"], post["content_format"]
            ),
        }
        for post in raw_recent
    ]
    return templates.TemplateResponse(
        request,
        "home.html",
        {"cards": cards, "recent_posts": recent_posts, "me": current_user(request)},
    )
