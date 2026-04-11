"""Shared dependencies for route modules.

This module holds templates, helpers, constants and filters that
multiple route files need.  It does NOT import from ``app.main``.
"""

import hashlib
import logging
import os
import re
import secrets
import sys
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from loguru import logger
from pydantic import BaseModel

# --- Loguru setup: intercept all stdlib logging ---


class _InterceptHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno
        frame, depth = logging.currentframe(), 2
        while frame and frame.f_code.co_filename == logging.__file__:
            frame = frame.f_back
            depth += 1
        logger.opt(depth=depth, exception=record.exc_info).log(
            level, record.getMessage()
        )


def setup_logging():
    """Replace stdlib logging with loguru for consistent output."""
    logger.remove()
    logger.add(sys.stderr, level="INFO")
    logging.basicConfig(handlers=[_InterceptHandler()], level=0, force=True)
    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logging.getLogger(name).handlers = []


setup_logging()

from app.queries.users import get_user_by_id  # noqa: E402

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOADS_DIR = BASE_DIR / "uploads"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_STORAGE_PER_USER = 500 * 1024 * 1024  # 500 MB
USERNAME_RE = re.compile(r"^[a-z0-9_-]{3,32}$")
USERNAME_INVALID_MSG = (
    "username must be 3-32 chars, lowercase letters, numbers, hyphens, or underscores"
)

_raw_vapid_key = os.environ.get("VAPID_PRIVATE_KEY", "").replace("\\n", "\n")
# pywebpush expects DER base64, not PEM. Strip headers and join lines.
VAPID_PRIVATE_KEY = "".join(
    line for line in _raw_vapid_key.strip().splitlines() if not line.startswith("-----")
)
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "")
VAPID_EMAIL = os.environ.get("VAPID_EMAIL", "mailto:me@jackharrhy.dev")

# ---------------------------------------------------------------------------
# CSRF helpers
# ---------------------------------------------------------------------------


def ensure_csrf_token(request: Request) -> str:
    """Get or create a CSRF token stored in the session."""
    try:
        session = request.session
    except AssertionError:
        return ""
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------


def _csrf_context_processor(request: Request) -> dict:
    """Inject csrf_token into every template context."""
    return {"csrf_token": ensure_csrf_token(request)}


templates = Jinja2Templates(
    directory=str(BASE_DIR / "templates"),
    context_processors=[_csrf_context_processor],
)


def unique_filename(directory: Path, filename: str) -> str:
    """Return a filename that doesn't collide with existing files in directory.

    Appends -2, -3, etc. to the stem if the name is taken.
    """
    path = directory / filename
    if not path.exists():
        return filename
    stem = Path(filename).stem
    ext = Path(filename).suffix
    i = 2
    while True:
        candidate = f"{stem}-{i}{ext}"
        if not (directory / candidate).exists():
            return candidate
        i += 1


def clean_filename(name: str) -> str:
    """Sanitize a filename for safe filesystem storage."""
    raw = Path(name or "file").name
    stem = Path(raw).stem or "file"
    suffix = Path(raw).suffix[:16].lower()
    safe_stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", stem).strip("-._") or "file"
    return f"{safe_stem}{suffix}"


def human_bytes(size: int | None) -> str:
    """Format byte count as human-readable string (e.g. 1.5 MB)."""
    if size is None:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024


def rename_user_media(
    conn, user_id: int, old_username: str, new_username: str, uploads_dir: Path
):
    """Rename all media files and DB paths when a user's username changes."""
    from sqlalchemy import select
    from sqlalchemy import update as sql_update

    from app.schema import media

    old_user_dir = uploads_dir / old_username
    new_user_dir = uploads_dir / new_username

    media_rows = (
        conn.execute(
            select(media.c.id, media.c.storage_path).where(media.c.user_id == user_id)
        )
        .mappings()
        .all()
    )

    for row in media_rows:
        old_storage = row["storage_path"]
        if not old_storage.startswith(f"{old_username}/"):
            continue
        filename = old_storage.split("/", 1)[1]
        src = uploads_dir / old_storage
        dst_filename = unique_filename(new_user_dir, filename)
        dst = new_user_dir / dst_filename
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.exists():
            src.rename(dst)
        conn.execute(
            sql_update(media)
            .where(media.c.id == row["id"])
            .values(storage_path=f"{new_username}/{dst_filename}")
        )

    # Clean up old directory if empty
    if old_user_dir.exists():
        import contextlib

        with contextlib.suppress(OSError):
            old_user_dir.rmdir()


templates.env.filters["human_bytes"] = human_bytes


def localtime(dt, fmt="full"):
    """Render a datetime as a <time> tag for client-side conversion.

    fmt: 'full' (date+time), 'date' (date only),
    'time' (time only), 'relative' (relative time)
    """
    if not dt:
        return ""
    from markupsafe import Markup

    iso = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    fallback = dt.strftime("%Y-%m-%d %H:%M")
    if fmt == "date":
        fallback = dt.strftime("%Y-%m-%d")
    elif fmt == "time":
        fallback = dt.strftime("%H:%M")
    return Markup(f'<time datetime="{iso}" data-fmt="{fmt}">{fallback}</time>')


templates.env.filters["localtime"] = localtime


def preview_text(html: str, length: int = 200) -> str:
    """Convert rendered HTML to a clean preview string for forum activity.

    Replaces media tags with emoji placeholders, preserves line breaks,
    then strips remaining tags and truncates.
    """
    import re

    s = html
    s = re.sub(r"<img[^>]*>", " 🖼️ ", s)
    s = re.sub(r"<video[^>]*>.*?</video>", " 🎬 ", s, flags=re.DOTALL)
    s = re.sub(r"<audio[^>]*>.*?</audio>", " 🎵 ", s, flags=re.DOTALL)
    s = re.sub(r"<iframe[^>]*>.*?</iframe>", " 📺 ", s, flags=re.DOTALL)
    s = re.sub(r"<br\s*/?>", "\n", s)
    s = re.sub(r"</p>\s*<p[^>]*>", "\n\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = s.strip()
    if len(s) > length:
        s = s[:length].rsplit(" ", 1)[0] + "..."
    return s


templates.env.filters["preview_text"] = preview_text

# Cache-busting hash for static assets
_css_path = BASE_DIR / "static" / "style.css"
_css_hash = (
    hashlib.md5(_css_path.read_bytes()).hexdigest()[:8] if _css_path.exists() else "0"
)
_app_path = BASE_DIR / "static" / "app.js"
_app_hash = (
    hashlib.md5(_app_path.read_bytes()).hexdigest()[:8] if _app_path.exists() else "0"
)
_cm_path = BASE_DIR / "static" / "codemirror.js"
_cm_hash = (
    hashlib.md5(_cm_path.read_bytes()).hexdigest()[:8] if _cm_path.exists() else "0"
)
templates.env.globals["css_hash"] = _css_hash
templates.env.globals["app_hash"] = _app_hash
templates.env.globals["cm_hash"] = _cm_hash
templates.env.globals["vapid_public_key"] = VAPID_PUBLIC_KEY

# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------


def get_engine(request: Request):
    return request.app.state.engine


def is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


def wants_json(request: Request) -> bool:
    """Check if the client prefers JSON over HTML."""
    accept = request.headers.get("accept", "")
    return "application/json" in accept and "text/html" not in accept


def json_response(model: BaseModel, status_code: int = 200) -> JSONResponse:
    """Wrap a Pydantic model in a JSONResponse.

    Routes that declare ``response_class=HTMLResponse`` cannot return a
    Pydantic model directly — FastAPI/Starlette will try to ``.encode()``
    the dict as HTML and crash.  Use this helper instead.
    """
    return JSONResponse(model.model_dump(mode="json"), status_code=status_code)


def current_user(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    with get_engine(request).begin() as conn:
        user = get_user_by_id(conn, user_id)
    if user and user.get("is_disabled"):
        # Clear session for disabled users
        request.session.clear()
        return None
    return user


def require_user(request: Request):
    """Return the current user or redirect to login."""
    me = current_user(request)
    if not me:
        return None, RedirectResponse(url="/login", status_code=303)
    return me, None


def require_user_dep(request: Request):
    """Dependency-style user guard for FastAPI route params."""
    me = current_user(request)
    if not me:
        raise LoginRequired()
    return me


class LoginRequired(Exception):
    pass


def require_admin(request: Request):
    """Return the current user if they are an admin, otherwise raise 403."""
    me = current_user(request)
    if not me or not me["is_admin"]:
        raise HTTPException(403)
    return me


def _saved_or_redirect(request: Request, url: str = "/settings"):
    """Return appropriate response after a settings save."""
    if wants_json(request):
        from app.models import SuccessResponse

        return SuccessResponse()
    if is_htmx(request):
        return templates.TemplateResponse(request, "fragments/saved.html")
    return RedirectResponse(url=url, status_code=303)


def _error_or_redirect(request: Request, message: str, url: str):
    if is_htmx(request):
        return (
            templates.TemplateResponse(
                request,
                "fragments/error_message.html",
                {"message": message},
                status_code=400,
            ),
            True,
        )
    return RedirectResponse(url=url, status_code=303), True


def _format_rfc2822(dt) -> str:
    if dt is None:
        dt = datetime.now(UTC)
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            dt = datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return format_datetime(dt)
