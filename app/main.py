import contextlib
import os
import random as _random
import time as _time
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from app.backup import BackupScheduler
from app.db import engine as default_engine
from app.deps import (
    BASE_DIR,
    LoginRequired,
    current_user,
    get_engine,
    json_response,
    templates,
    wants_json,
)
from app.models import ForumPostPreview, HomepageResponse, ProfileCard
from app.queries.forum import recent_forum_posts
from app.queries.users import list_profile_cards
from app.rendering import render_content, render_forum_post
from app.routes import (
    admin,
    auth,
    chat,
    feeds,
    forum,
    guestbook,
    media,
    oauth2,
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

    # Sync OAuth2 clients from config file
    from app.oauth2_clients_sync import sync_oauth2_clients

    oauth2_config = BASE_DIR / "oauth2_clients.toml"
    if not getattr(application.state, "testing", False):
        sync_oauth2_clients(engine, oauth2_config)

    # Only run backup scheduler in production (not during --reload dev)
    is_reload = os.environ.get("UVICORN_RELOAD", "") or any(
        "reload" in str(a) for a in __import__("sys").argv
    )
    if not is_reload:
        backup_dir = BASE_DIR / "backups"
        backup_dir.mkdir(exist_ok=True)
        scheduler = BackupScheduler(
            db_path=BASE_DIR / "data" / "4orm.db",
            uploads_dir=BASE_DIR / "uploads",
            backup_dir=backup_dir,
        )
        application.state.backup_scheduler = scheduler
        scheduler.start()
    else:
        application.state.backup_scheduler = None

    yield

    if application.state.backup_scheduler:
        application.state.backup_scheduler.stop()


_CSRF_EXEMPT_PATHS = {"/login", "/oauth/token"}
_TRUSTED_ORIGINS: set[str] = set()  # add full origins like "https://example.com"


class CSRFMiddleware(BaseHTTPMiddleware):
    """Reject cross-origin non-safe requests using Sec-Fetch-Site / Origin.

    Algorithm from https://words.filippo.io/csrf/ and Go 1.25 CrossOriginProtection:
    1. Allow safe methods (GET, HEAD, OPTIONS).
    2. Allow exempt paths (login, feeds).
    3. Allow trusted origins from the allowlist.
    4. If Sec-Fetch-Site is present: allow same-origin/none, reject everything else.
    5. If neither Sec-Fetch-Site nor Origin is present: allow (not a browser).
    6. If Origin host == Host header: allow (old browser / HTTP origin fallback).
    7. Reject.
    """

    async def dispatch(self, request: Request, call_next):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return await call_next(request)

        path = request.url.path
        if path in _CSRF_EXEMPT_PATHS or path.endswith("/feed.xml"):
            return await call_next(request)

        origin = request.headers.get("origin")
        sec_fetch_site = request.headers.get("sec-fetch-site")

        # Step 2: trusted origin allowlist
        if origin and origin in _TRUSTED_ORIGINS:
            return await call_next(request)

        # Step 3: Sec-Fetch-Site (reliable in all major browsers since 2023)
        if sec_fetch_site is not None:
            if sec_fetch_site in ("same-origin", "none"):
                return await call_next(request)
            return PlainTextResponse(
                "Forbidden: cross-origin request rejected", status_code=403
            )

        # Step 4: no browser headers at all — not a browser, allow
        if origin is None:
            return await call_next(request)

        # Step 5: Origin vs Host fallback (old browsers, HTTP origins)
        origin_host = urlparse(origin).netloc  # includes port if non-default
        host = request.headers.get("host", "")
        if origin_host == host:
            return await call_next(request)

        return PlainTextResponse(
            "Forbidden: origin does not match host", status_code=403
        )


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
app.include_router(chat.router)
app.include_router(pages.router)
app.include_router(settings.router)
app.include_router(media.router)
app.include_router(admin.router)
app.include_router(guestbook.router)
app.include_router(feeds.router)
app.include_router(forum.router)
app.include_router(webring.router)
app.include_router(push.router)
app.include_router(oauth2.router)


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
    message = ERROR_MESSAGES.get(exc.status_code, exc.detail)
    if wants_json(request):
        return JSONResponse(
            {"ok": False, "error": message, "status_code": exc.status_code},
            status_code=exc.status_code,
        )
    me = None
    with contextlib.suppress(Exception):
        me = current_user(request)
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

    if wants_json(request):
        return json_response(
            HomepageResponse(
                cards=[
                    ProfileCard(
                        username=c["username"],
                        headline=c.get("headline", ""),
                        content=c.get("content", ""),
                        content_format=c.get("content_format", "html"),
                        rendered_content=c.get("rendered_content", ""),
                        accent_color=c.get("accent_color", ""),
                        border_style=c.get("border_style", ""),
                        card_css=c.get("card_css", ""),
                    )
                    for c in cards
                ],
                recent_forum_posts=[
                    ForumPostPreview(
                        id=p["id"],
                        thread_id=p["thread_id"],
                        thread_title=p.get("thread_title", ""),
                        author_username=p["author_username"],
                        author_display_name=p.get("author_display_name", ""),
                        rendered_content=p.get("rendered_content", ""),
                        created_at=p.get("created_at"),
                    )
                    for p in recent_posts
                ],
            )
        )

    _CHAT_FONTS = [
        "monospace",
        "cursive",
        "fantasy",
        "serif",
        "Comic Sans MS, cursive",
    ]
    _CHAT_COLORS = [
        "#ff0000",
        "#00ff00",
        "#0000ff",
        "#ff00ff",
        "#ffff00",
        "#00ffff",
        "#ff6600",
        "#66ff33",
    ]
    _CHAT_BG = [
        "#000",
        "#111",
        "#220022",
        "#002200",
        "#000033",
        "#330000",
        "#1a1a2e",
    ]
    _CHAT_BORDERS = [
        "3px solid",
        "3px dashed",
        "3px double",
        "3px dotted",
        "3px outset",
        "3px ridge",
    ]
    seed = int(_time.time()) // 300
    rng = _random.Random(seed)
    chat_style = (
        f"font-family: {rng.choice(_CHAT_FONTS)}; "
        f"color: {rng.choice(_CHAT_COLORS)}; "
        f"background: {rng.choice(_CHAT_BG)}; "
        f"border: {rng.choice(_CHAT_BORDERS)} {rng.choice(_CHAT_COLORS)}; "
        f"padding: 6px 16px; text-decoration: none; display: inline-block;"
    )

    return templates.TemplateResponse(
        request,
        "home.html",
        {
            "cards": cards,
            "recent_posts": recent_posts,
            "me": current_user(request),
            "chat_style": chat_style,
        },
    )
