import re
from datetime import UTC, datetime
from email.utils import format_datetime
from html import escape
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select, update
from starlette.middleware.sessions import SessionMiddleware

from app.db import engine as default_engine
from app.queries.guestbook import (
    create_guestbook_entry,
    delete_guestbook_entry,
    list_guestbook_entries,
)
from app.queries.media import (
    create_media,
    delete_media_for_user,
    get_media_for_user,
    list_media_for_user,
    update_media_alt_text,
    update_media_storage_path,
)
from app.queries.pages import (
    create_page,
    delete_user_page,
    get_public_page,
    get_user_page,
    list_pages_for_user,
    list_public_pages_for_rss,
    list_public_pages_for_user,
    list_public_pages_for_user_rss,
    update_user_page,
)
from app.queries.users import (
    create_invite,
    create_user_with_invite,
    delete_invite,
    disable_invite,
    get_invite_tree,
    get_invites_for_user,
    get_user_by_id,
    get_user_by_username,
    list_profile_cards,
)
from app.rendering import build_raw_html, render_content
from app.schema import create_all, media, pages, profile_cards, users
from app.security import verify_password

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOADS_DIR = BASE_DIR / "uploads"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
USERNAME_RE = re.compile(r"^[a-z0-9_-]{3,32}$")
MAX_STORAGE_PER_USER = 500 * 1024 * 1024  # 500 MB
from contextlib import asynccontextmanager


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

    yield


app = FastAPI(title="4orm", lifespan=lifespan)
app.state.engine = default_engine
app.add_middleware(SessionMiddleware, secret_key="replace-this-dev-key")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/uploads", StaticFiles(directory=BASE_DIR / "uploads"), name="uploads")
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
import hashlib

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


def build_rss_feed(
    *, title: str, link: str, description: str, items: list[dict]
) -> str:
    entries = []
    for item in items:
        entries.append(
            "<item>"
            f"<title>{escape(item['title'])}</title>"
            f"<link>{escape(item['link'])}</link>"
            f"<guid>{escape(item['guid'])}</guid>"
            f"<pubDate>{_format_rfc2822(item.get('updated_at'))}</pubDate>"
            "</item>"
        )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0"><channel>'
        f"<title>{escape(title)}</title>"
        f"<link>{escape(link)}</link>"
        f"<description>{escape(description)}</description>"
        f"{''.join(entries)}"
        "</channel></rss>"
    )


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


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    with get_engine(request).begin() as conn:
        raw_cards = list_profile_cards(conn)
    cards = [
        {
            **card,
            "rendered_content": render_content(card["content"], card["content_format"]),
        }
        for card in raw_cards
    ]
    return templates.TemplateResponse(
        request, "home.html", {"cards": cards, "me": current_user(request)}
    )


@app.get("/register", response_class=HTMLResponse)
def register_get(request: Request, invite: str | None = None):
    return templates.TemplateResponse(
        request, "register.html", {"invite": invite, "error": None}
    )


@app.post("/register", response_class=HTMLResponse)
def register_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    invite_code: str = Form(...),
):
    with get_engine(request).begin() as conn:
        user, error = create_user_with_invite(
            conn,
            username=username.strip(),
            password=password,
            invite_code=invite_code.strip(),
        )
    if error:
        return templates.TemplateResponse(
            request,
            "register.html",
            {"invite": invite_code, "error": error},
            status_code=400,
        )
    request.session["user_id"] = user["id"]
    return RedirectResponse(url=f"/u/{user['username']}", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login", response_class=HTMLResponse)
def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    with get_engine(request).begin() as conn:
        user = get_user_by_username(conn, username.strip())
    if not user or not verify_password(password, user["password_hash"]):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Invalid credentials"},
            status_code=400,
        )
    request.session["user_id"] = user["id"]
    return RedirectResponse(url=f"/u/{user['username']}", status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


@app.get("/how-to", response_class=HTMLResponse)
def how_to(request: Request):
    return templates.TemplateResponse(
        request, "how_to.html", {"me": current_user(request)}
    )


@app.get("/u/{username}", response_class=HTMLResponse)
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

    template_name = "profile_simple.html" if layout == "simple" else "profile.html"
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


@app.get("/u/{username}/page/{slug}", response_class=HTMLResponse)
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

    template_name = "page_simple.html" if layout == "simple" else "page.html"
    return templates.TemplateResponse(
        request,
        template_name,
        {
            "page": page,
            "rendered_content": rendered_content,
            "me": current_user(request),
        },
    )


# --- Guestbook ---


@app.get("/u/{username}/guestbook", response_class=HTMLResponse)
def guestbook_view(request: Request, username: str):
    with get_engine(request).begin() as conn:
        owner = get_user_by_username(conn, username)
        if not owner:
            raise HTTPException(404)
        entries = list_guestbook_entries(conn, owner["id"])
    me = current_user(request)
    is_owner = me and me["id"] == owner["id"]
    return templates.TemplateResponse(
        request,
        "guestbook.html",
        {
            "owner": owner,
            "entries": entries,
            "me": me,
            "is_owner": is_owner,
        },
    )


@app.post("/u/{username}/guestbook", response_class=HTMLResponse)
def guestbook_post(request: Request, username: str, message: str = Form(...)):
    me = current_user(request)
    if not me:
        raise HTTPException(403)
    with get_engine(request).begin() as conn:
        owner = get_user_by_username(conn, username)
        if not owner:
            raise HTTPException(404)
        create_guestbook_entry(conn, owner["id"], me["id"], message)
        entries = list_guestbook_entries(conn, owner["id"])
    is_owner = me["id"] == owner["id"]
    if is_htmx(request):
        return templates.TemplateResponse(
            request,
            "fragments/guestbook_entries.html",
            {"owner": owner, "entries": entries, "me": me, "is_owner": is_owner},
        )
    return RedirectResponse(url=f"/u/{username}/guestbook", status_code=303)


@app.post("/u/{username}/guestbook/{entry_id}/delete", response_class=HTMLResponse)
def guestbook_delete(request: Request, username: str, entry_id: int):
    me = current_user(request)
    if not me:
        raise HTTPException(403)
    with get_engine(request).begin() as conn:
        owner = get_user_by_username(conn, username)
        if not owner or me["id"] != owner["id"]:
            raise HTTPException(403)
        delete_guestbook_entry(conn, entry_id, owner["id"])
        entries = list_guestbook_entries(conn, owner["id"])
    if is_htmx(request):
        return templates.TemplateResponse(
            request,
            "fragments/guestbook_entries.html",
            {"owner": owner, "entries": entries, "me": me, "is_owner": True},
        )
    return RedirectResponse(url=f"/u/{username}/guestbook", status_code=303)


@app.get("/feed.xml")
def global_feed(request: Request):
    with get_engine(request).begin() as conn:
        pages = list_public_pages_for_rss(conn, limit=100)

    site_url = str(request.base_url).rstrip("/")
    items = []
    for p in pages:
        link = f"{site_url}/u/{p['username']}/page/{p['slug']}"
        items.append(
            {
                "title": f"{p['display_name']}: {p['title']}",
                "link": link,
                "guid": f"{link}#{p['updated_at']}",
                "updated_at": p["updated_at"],
            }
        )

    xml = build_rss_feed(
        title="4orm updates",
        link=f"{site_url}/",
        description="Recent public page updates",
        items=items,
    )
    return Response(content=xml, media_type="application/rss+xml; charset=utf-8")


@app.get("/u/{username}/feed.xml")
def user_feed(request: Request, username: str):
    with get_engine(request).begin() as conn:
        profile = get_user_by_username(conn, username)
        if not profile:
            raise HTTPException(404)
        pages = list_public_pages_for_user_rss(conn, username, limit=100)

    site_url = str(request.base_url).rstrip("/")
    items = []
    for p in pages:
        link = f"{site_url}/u/{p['username']}/page/{p['slug']}"
        items.append(
            {
                "title": p["title"],
                "link": link,
                "guid": f"{link}#{p['updated_at']}",
                "updated_at": p["updated_at"],
            }
        )

    xml = build_rss_feed(
        title=f"4orm updates from {profile['display_name']}",
        link=f"{site_url}/u/{username}",
        description="Recent public page updates (published after 20 minutes of no edits)",
        items=items,
    )
    return Response(content=xml, media_type="application/rss+xml; charset=utf-8")


@app.get("/lineage", response_class=HTMLResponse)
def lineage(request: Request):
    with get_engine(request).begin() as conn:
        tree = get_invite_tree(conn)
    return templates.TemplateResponse(
        request,
        "lineage.html",
        {"tree": tree, "me": current_user(request)},
    )


@app.get("/settings", response_class=HTMLResponse)
def settings_get(request: Request):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with get_engine(request).begin() as conn:
        my_pages = list_pages_for_user(conn, me["id"])
        card_settings = (
            conn.execute(
                select(profile_cards).where(profile_cards.c.user_id == me["id"])
            )
            .mappings()
            .first()
        )
        media_items = list_media_for_user(conn, me["id"])
        my_invites = get_invites_for_user(conn, me["id"])
    return templates.TemplateResponse(
        request,
        "settings.html",
        {
            "me": me,
            "username": me["username"],
            "my_pages": my_pages,
            "card_settings": card_settings,
            "media_items": media_items,
            "my_invites": my_invites,
            "error": None,
        },
    )


@app.get("/settings/media", response_class=HTMLResponse)
def settings_media_get(request: Request):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with get_engine(request).begin() as conn:
        items = list_media_for_user(conn, me["id"])
        storage_used = conn.execute(
            select(func.coalesce(func.sum(media.c.size_bytes), 0)).where(
                media.c.user_id == me["id"]
            )
        ).scalar()
    storage_pct = (
        (storage_used / MAX_STORAGE_PER_USER * 100) if MAX_STORAGE_PER_USER else 0
    )
    return templates.TemplateResponse(
        request,
        "settings_media.html",
        {
            "me": me,
            "items": items,
            "storage_used": storage_used,
            "storage_limit": MAX_STORAGE_PER_USER,
            "storage_pct": storage_pct,
        },
    )


@app.post("/settings/media/upload")
async def settings_media_upload(
    request: Request, file: UploadFile = File(...), filename: str = Form("")
):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)

    username = me["username"]
    user_upload_dir = UPLOADS_DIR / username
    user_upload_dir.mkdir(parents=True, exist_ok=True)

    chosen_name = filename.strip() or (file.filename or "file")
    final_name = clean_filename(chosen_name)
    original_ext = Path(file.filename or "").suffix.lower()
    if original_ext and Path(final_name).suffix.lower() != original_ext:
        final_name = f"{Path(final_name).stem}{original_ext}"

    rel_path = f"{username}/{final_name}"
    disk_path = UPLOADS_DIR / rel_path

    # Avoid collisions by suffixing -2, -3, ...
    if disk_path.exists():
        base = Path(final_name).stem
        ext = Path(final_name).suffix
        i = 2
        while True:
            candidate = f"{base}-{i}{ext}"
            candidate_path = user_upload_dir / candidate
            if not candidate_path.exists():
                final_name = candidate
                rel_path = f"{username}/{final_name}"
                disk_path = candidate_path
                break
            i += 1

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        return RedirectResponse(url="/settings/media?error=too_big", status_code=303)

    # Check per-user storage limit
    with get_engine(request).begin() as conn:
        current_usage = conn.execute(
            select(func.coalesce(func.sum(media.c.size_bytes), 0)).where(
                media.c.user_id == me["id"]
            )
        ).scalar()
    if current_usage + len(content) > MAX_STORAGE_PER_USER:
        return RedirectResponse(
            url="/settings/media?error=storage_full", status_code=303
        )

    disk_path.write_bytes(content)

    with get_engine(request).begin() as conn:
        create_media(
            conn,
            user_id=me["id"],
            storage_path=rel_path,
            mime_type=file.content_type or "application/octet-stream",
            size_bytes=len(content),
        )
        if is_htmx(request):
            item = (
                conn.execute(select(media).where(media.c.storage_path == rel_path))
                .mappings()
                .first()
            )
            return templates.TemplateResponse(
                request, "fragments/media_card.html", {"item": item}
            )

    return RedirectResponse(url="/settings/media", status_code=303)


def _media_card_response(request: Request, me, media_id):
    with get_engine(request).begin() as conn:
        item = get_media_for_user(conn, me["id"], media_id)
    if item and is_htmx(request):
        return templates.TemplateResponse(
            request, "fragments/media_card.html", {"item": item}
        )
    return RedirectResponse(url="/settings/media", status_code=303)


@app.post("/settings/media/{media_id}/alt")
def settings_media_alt(request: Request, media_id: int, alt_text: str = Form("")):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with get_engine(request).begin() as conn:
        item = get_media_for_user(conn, me["id"], media_id)
        if not item:
            raise HTTPException(404)
        update_media_alt_text(conn, me["id"], media_id, alt_text)
    return _media_card_response(request, me, media_id)


@app.post("/settings/media/{media_id}/delete")
def settings_media_delete(request: Request, media_id: int):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with get_engine(request).begin() as conn:
        item = get_media_for_user(conn, me["id"], media_id)
        if not item:
            raise HTTPException(404)
        delete_media_for_user(conn, me["id"], media_id)
    disk_path = UPLOADS_DIR / item["storage_path"]
    if disk_path.exists():
        disk_path.unlink()
    if is_htmx(request):
        return HTMLResponse("")
    return RedirectResponse(url="/settings/media", status_code=303)


@app.post("/settings/media/{media_id}/rename")
def settings_media_rename(request: Request, media_id: int, filename: str = Form(...)):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)

    username = me["username"]
    user_upload_dir = UPLOADS_DIR / username
    user_upload_dir.mkdir(parents=True, exist_ok=True)

    with get_engine(request).begin() as conn:
        item = get_media_for_user(conn, me["id"], media_id)
        if not item:
            raise HTTPException(404)

        new_name = clean_filename(filename)
        old_path = UPLOADS_DIR / item["storage_path"]
        old_ext = old_path.suffix.lower()
        if old_ext and Path(new_name).suffix.lower() != old_ext:
            new_name = f"{Path(new_name).stem}{old_ext}"

        new_path = user_upload_dir / new_name
        if new_path.exists() and new_path != old_path:
            base = Path(new_name).stem
            ext = Path(new_name).suffix
            i = 2
            while True:
                candidate = user_upload_dir / f"{base}-{i}{ext}"
                if not candidate.exists():
                    new_path = candidate
                    break
                i += 1

        if old_path.exists() and old_path != new_path:
            old_path.rename(new_path)

        rel_path = f"{username}/{new_path.name}"
        update_media_storage_path(conn, me["id"], media_id, rel_path)

    return _media_card_response(request, me, media_id)


def _saved_or_redirect(request: Request, url: str = "/settings"):
    if is_htmx(request):
        return templates.TemplateResponse(request, "fragments/saved.html")
    return RedirectResponse(url=url, status_code=303)


@app.post("/settings/profile")
def settings_profile(
    request: Request,
    display_name: str = Form(""),
    content: str = Form(""),
    content_format: str = Form("html"),
    layout: str = Form("default"),
):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with get_engine(request).begin() as conn:
        conn.execute(
            update(users)
            .where(users.c.id == me["id"])
            .values(
                display_name=display_name,
                content=content,
                content_format=content_format,
                layout=layout,
            )
        )
    return _saved_or_redirect(request)


@app.post("/settings/username")
def settings_username(request: Request, username: str = Form(...)):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)

    new_username = username.strip().lower()
    if not USERNAME_RE.match(new_username):
        if is_htmx(request):
            return HTMLResponse(
                '<span class="error">Username must be 3-32 chars using a-z, 0-9, - or _</span>',
                status_code=400,
            )
        return RedirectResponse(url="/settings?error=invalid_username", status_code=303)

    if new_username == me["username"]:
        return _saved_or_redirect(request)

    uploads_root = UPLOADS_DIR
    old_username = me["username"]
    old_user_dir = uploads_root / old_username
    new_user_dir = uploads_root / new_username

    with get_engine(request).begin() as conn:
        existing = conn.execute(
            select(users.c.id).where(users.c.username == new_username)
        ).first()
        if existing:
            if is_htmx(request):
                return HTMLResponse(
                    '<span class="error">That username is already taken</span>',
                    status_code=400,
                )
            return RedirectResponse(url="/settings?error=username_taken", status_code=303)

        media_rows = (
            conn.execute(
                select(media.c.id, media.c.storage_path).where(media.c.user_id == me["id"])
            )
            .mappings()
            .all()
        )

        for row in media_rows:
            old_storage = row["storage_path"]
            if not old_storage.startswith(f"{old_username}/"):
                continue

            filename = old_storage.split("/", 1)[1]
            src = uploads_root / old_storage
            dst = new_user_dir / filename
            dst.parent.mkdir(parents=True, exist_ok=True)

            if src.exists():
                if dst.exists() and dst != src:
                    base = Path(filename).stem
                    ext = Path(filename).suffix
                    n = 2
                    while True:
                        candidate = dst.parent / f"{base}-{n}{ext}"
                        if not candidate.exists():
                            dst = candidate
                            break
                        n += 1
                src.rename(dst)

            new_storage = f"{new_username}/{dst.name}"
            conn.execute(
                update(media)
                .where(media.c.id == row["id"], media.c.user_id == me["id"])
                .values(storage_path=new_storage)
            )

        conn.execute(
            update(users).where(users.c.id == me["id"]).values(username=new_username)
        )

    if old_user_dir.exists() and old_user_dir != new_user_dir:
        try:
            old_user_dir.rmdir()
        except OSError:
            pass

    return _saved_or_redirect(request, url="/settings?saved=username")


@app.post("/settings/css")
def settings_css(request: Request, custom_css: str = Form("")):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with get_engine(request).begin() as conn:
        conn.execute(
            update(users).where(users.c.id == me["id"]).values(custom_css=custom_css)
        )
    return _saved_or_redirect(request)


@app.post("/settings/html")
def settings_html(request: Request, custom_html: str = Form("")):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with get_engine(request).begin() as conn:
        conn.execute(
            update(users).where(users.c.id == me["id"]).values(custom_html=custom_html)
        )
    return _saved_or_redirect(request)


@app.post("/settings/guestbook")
def settings_guestbook(
    request: Request,
    guestbook_css: str = Form(""),
    guestbook_html: str = Form(""),
):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with get_engine(request).begin() as conn:
        conn.execute(
            update(users)
            .where(users.c.id == me["id"])
            .values(guestbook_css=guestbook_css, guestbook_html=guestbook_html)
        )
    return _saved_or_redirect(request)


@app.post("/settings/card")
def settings_card(
    request: Request,
    headline: str = Form(""),
    content: str = Form(""),
    content_format: str = Form("html"),
    accent_color: str = Form("#00ffff"),
    border_style: str = Form("outset"),
    card_css: str = Form(""),
):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)

    with get_engine(request).begin() as conn:
        conn.execute(
            update(profile_cards)
            .where(profile_cards.c.user_id == me["id"])
            .values(
                headline=headline,
                content=content,
                content_format=content_format,
                accent_color=accent_color,
                border_style=border_style,
                card_css=card_css,
            )
        )
    return _saved_or_redirect(request)


def _invites_fragment(request: Request, me):
    with get_engine(request).begin() as conn:
        my_invites = get_invites_for_user(conn, me["id"])
    return templates.TemplateResponse(
        request, "fragments/invites.html", {"my_invites": my_invites}
    )


@app.post("/settings/invites")
def settings_invites(request: Request, max_uses: int = Form(1)):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)

    with get_engine(request).begin() as conn:
        code = create_invite(conn, me["id"], max_uses=max(1, min(50, max_uses)))

    if is_htmx(request):
        return _invites_fragment(request, me)
    return RedirectResponse(url=f"/settings?new_invite={code}", status_code=303)


@app.post("/settings/invites/{invite_id}/disable")
def settings_invite_disable(request: Request, invite_id: int):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with get_engine(request).begin() as conn:
        disable_invite(conn, invite_id, me["id"])

    if is_htmx(request):
        return _invites_fragment(request, me)
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/invites/{invite_id}/delete")
def settings_invite_delete(request: Request, invite_id: int):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with get_engine(request).begin() as conn:
        delete_invite(conn, invite_id, me["id"])

    if is_htmx(request):
        return _invites_fragment(request, me)
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/pages")
def settings_pages(
    request: Request,
    slug: str = Form(...),
    title: str = Form(...),
    content: str = Form(""),
    content_format: str = Form("html"),
    layout: str = Form("default"),
):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)

    from sqlalchemy.exc import IntegrityError

    try:
        with get_engine(request).begin() as conn:
            create_page(
                conn,
                user_id=me["id"],
                slug=slug.strip(),
                title=title.strip(),
                content=content,
                content_format=content_format,
                layout=layout,
                is_public=True,
            )
    except IntegrityError:
        return RedirectResponse(url="/settings?error=slug_taken", status_code=303)

    return RedirectResponse(
        url=f"/u/{me['username']}/page/{slug.strip()}", status_code=303
    )


@app.post("/settings/pages/{slug}/delete")
def settings_page_delete(request: Request, slug: str):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with get_engine(request).begin() as conn:
        delete_user_page(conn, me["id"], slug)
        if is_htmx(request):
            my_pages = list_pages_for_user(conn, me["id"])
            return templates.TemplateResponse(
                request,
                "fragments/pages_list.html",
                {"my_pages": my_pages, "username": me["username"]},
            )
    return RedirectResponse(url="/settings", status_code=303)


@app.get("/settings/pages/{slug}/edit", response_class=HTMLResponse)
def settings_pages_edit_get(request: Request, slug: str):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)

    with get_engine(request).begin() as conn:
        page = get_user_page(conn, me["id"], slug)
        media_items = list_media_for_user(conn, me["id"])

    if not page:
        raise HTTPException(404)

    return templates.TemplateResponse(
        request,
        "edit_page.html",
        {
            "me": me,
            "page": page,
            "media_items": media_items,
            "error": None,
        },
    )


@app.post("/settings/pages/{slug}/edit")
def settings_pages_edit_post(
    request: Request,
    slug: str,
    new_slug: str = Form(...),
    title: str = Form(...),
    content: str = Form(""),
    content_format: str = Form("html"),
    layout: str = Form("default"),
    is_public: str | None = Form(None),
):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)

    cleaned_slug = new_slug.strip()
    with get_engine(request).begin() as conn:
        page = get_user_page(conn, me["id"], slug)
        if not page:
            raise HTTPException(404)
        update_user_page(
            conn,
            me["id"],
            slug,
            slug=cleaned_slug,
            title=title.strip(),
            content=content,
            content_format=content_format,
            layout=layout,
            is_public=is_public == "on",
        )

    return RedirectResponse(
        url=f"/u/{me['username']}/page/{cleaned_slug}", status_code=303
    )


# --- Admin ---


@app.get("/admin", response_class=HTMLResponse)
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

    return templates.TemplateResponse(
        request,
        "admin.html",
        {
            "me": me,
            "all_users": all_users,
            "storage_by_user": storage_by_user,
            "cards_by_user": cards_by_user,
            "all_pages": all_pages,
        },
    )


@app.post("/admin/users/{user_id}/profile")
def admin_update_user_profile(
    request: Request,
    user_id: int,
    display_name: str = Form(""),
    content: str = Form(""),
    content_format: str = Form("markdown"),
    custom_css: str = Form(""),
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
            )
        )
    return RedirectResponse(url="/admin", status_code=303)


@app.post("/admin/users/{user_id}/card")
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


@app.post("/admin/pages/{page_id}")
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
        page = conn.execute(select(pages).where(pages.c.id == page_id)).mappings().first()
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


@app.get("/admin/orphans", response_class=HTMLResponse)
def admin_scan_orphans(request: Request):
    """Scan for orphaned files/records and return an HTML fragment."""
    require_admin(request)
    with get_engine(request).begin() as conn:
        db_paths = set(
            row[0] for row in conn.execute(select(media.c.storage_path)).fetchall()
        )

    orphaned_files = []
    if UPLOADS_DIR.exists():
        for user_dir in UPLOADS_DIR.iterdir():
            if not user_dir.is_dir() or user_dir.name.startswith("."):
                continue
            for f in user_dir.iterdir():
                if f.is_file() and not f.name.startswith("."):
                    rel = f"{user_dir.name}/{f.name}"
                    if rel not in db_paths:
                        orphaned_files.append({"path": rel, "size": f.stat().st_size})

    orphaned_records = []
    for p in db_paths:
        if not (UPLOADS_DIR / p).exists():
            orphaned_records.append(p)

    return templates.TemplateResponse(
        request,
        "admin_orphans.html",
        {
            "orphaned_files": sorted(orphaned_files, key=lambda x: x["path"]),
            "orphaned_records": sorted(orphaned_records),
        },
    )


@app.post("/admin/cleanup/files")
def admin_cleanup_files(request: Request):
    """Delete orphaned files from disk that have no DB record."""
    require_admin(request)
    with get_engine(request).begin() as conn:
        db_paths = set(
            row[0] for row in conn.execute(select(media.c.storage_path)).fetchall()
        )
    removed = 0
    if UPLOADS_DIR.exists():
        for user_dir in UPLOADS_DIR.iterdir():
            if not user_dir.is_dir() or user_dir.name.startswith("."):
                continue
            for f in user_dir.iterdir():
                if f.is_file() and not f.name.startswith("."):
                    rel = f"{user_dir.name}/{f.name}"
                    if rel not in db_paths:
                        f.unlink()
                        removed += 1
    return RedirectResponse(url=f"/admin?cleaned_files={removed}", status_code=303)


@app.post("/admin/cleanup/records")
def admin_cleanup_records(request: Request):
    """Delete orphaned DB records whose files are missing from disk."""
    require_admin(request)
    removed = 0
    with get_engine(request).begin() as conn:
        all_paths = conn.execute(select(media.c.id, media.c.storage_path)).fetchall()
        for media_id, path in all_paths:
            if not (UPLOADS_DIR / path).exists():
                conn.execute(media.delete().where(media.c.id == media_id))
                removed += 1
    return RedirectResponse(url=f"/admin?cleaned_records={removed}", status_code=303)


@app.post("/admin/users/{user_id}/toggle-admin")
def admin_toggle_admin(request: Request, user_id: int):
    me = require_admin(request)
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
