"""Shared dependencies for route modules.

This module holds templates, helpers, constants and filters that
multiple route files need.  It does NOT import from ``app.main``.
"""

import hashlib
import re
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.queries.users import get_user_by_id

# ---------------------------------------------------------------------------
# Paths & constants
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOADS_DIR = BASE_DIR / "uploads"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_STORAGE_PER_USER = 500 * 1024 * 1024  # 500 MB
USERNAME_RE = re.compile(r"^[a-z0-9_-]{3,32}$")

# ---------------------------------------------------------------------------
# Templates
# ---------------------------------------------------------------------------

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


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
        return get_user_by_id(conn, user_id)


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
