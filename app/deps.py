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
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from loguru import logger

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


def clean_filename(name: str) -> str:
    raw = Path(name or "file").name
    stem = Path(raw).stem or "file"
    suffix = Path(raw).suffix[:16].lower()
    safe_stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", stem).strip("-._") or "file"
    return f"{safe_stem}{suffix}"


def human_bytes(size: int | None) -> str:
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


templates.env.filters["human_bytes"] = human_bytes

# Cache-busting hash for static assets
_css_path = BASE_DIR / "static" / "style.css"
_css_hash = (
    hashlib.md5(_css_path.read_bytes()).hexdigest()[:8] if _css_path.exists() else "0"
)
_cm_path = BASE_DIR / "static" / "codemirror-setup.js"
_cm_hash = (
    hashlib.md5(_cm_path.read_bytes()).hexdigest()[:8] if _cm_path.exists() else "0"
)
templates.env.globals["css_hash"] = _css_hash
templates.env.globals["cm_hash"] = _cm_hash
templates.env.globals["vapid_public_key"] = VAPID_PUBLIC_KEY

# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------


def get_engine(request: Request):
    return request.app.state.engine


def is_htmx(request: Request) -> bool:
    return request.headers.get("HX-Request") == "true"


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


def require_admin(request: Request):
    """Return the current user if they are an admin, otherwise raise 403."""
    me = current_user(request)
    if not me or not me["is_admin"]:
        raise HTTPException(403)
    return me


def _saved_or_redirect(request: Request, url: str = "/settings"):
    if is_htmx(request):
        return templates.TemplateResponse(request, "fragments/saved.html")
    return RedirectResponse(url=url, status_code=303)


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
