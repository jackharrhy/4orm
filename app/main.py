import re
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, update
from starlette.middleware.sessions import SessionMiddleware

from app.db import engine as default_engine
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
    get_public_page,
    get_user_page,
    list_pages_for_user,
    list_public_pages_for_user,
    update_user_page,
)
from app.queries.users import (
    create_invite,
    create_user_with_invite,
    disable_invite,
    get_invite_tree,
    get_invites_for_user,
    get_user_by_id,
    get_user_by_username,
    list_profile_cards,
)
from app.rendering import render_content
from app.schema import create_all, profile_cards, users
from app.security import verify_password

BASE_DIR = Path(__file__).resolve().parent.parent
UPLOADS_DIR = BASE_DIR / "uploads"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
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


def get_engine(request: Request):
    return request.app.state.engine


def current_user(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    with get_engine(request).begin() as conn:
        return get_user_by_id(conn, user_id)


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


@app.get("/u/{username}", response_class=HTMLResponse)
def profile(request: Request, username: str):
    with get_engine(request).begin() as conn:
        user = get_user_by_username(conn, username)
        if not user:
            raise HTTPException(404)
        pages = list_public_pages_for_user(conn, username)
    rendered_content = render_content(user["content"], user["content_format"])
    return templates.TemplateResponse(
        request,
        "profile.html",
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
    return templates.TemplateResponse(
        request,
        "page.html",
        {
            "page": page,
            "rendered_content": rendered_content,
            "me": current_user(request),
        },
    )


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
    return templates.TemplateResponse(
        request, "settings_media.html", {"me": me, "items": items}
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

    disk_path.write_bytes(content)

    with get_engine(request).begin() as conn:
        create_media(
            conn,
            user_id=me["id"],
            storage_path=rel_path,
            mime_type=file.content_type or "application/octet-stream",
            size_bytes=len(content),
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
    return RedirectResponse(url="/settings/media", status_code=303)


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

    return RedirectResponse(url="/settings/media", status_code=303)


@app.post("/settings/profile")
def settings_profile(
    request: Request,
    display_name: str = Form(""),
    content: str = Form(""),
    content_format: str = Form("html"),
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
            )
        )
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/css")
def settings_css(request: Request, custom_css: str = Form("")):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with get_engine(request).begin() as conn:
        conn.execute(
            update(users).where(users.c.id == me["id"]).values(custom_css=custom_css)
        )
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/html")
def settings_html(request: Request, custom_html: str = Form("")):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with get_engine(request).begin() as conn:
        conn.execute(
            update(users).where(users.c.id == me["id"]).values(custom_html=custom_html)
        )
    return RedirectResponse(url="/settings", status_code=303)


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
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/invites")
def settings_invites(request: Request, max_uses: int = Form(1)):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)

    with get_engine(request).begin() as conn:
        code = create_invite(conn, me["id"], max_uses=max(1, min(50, max_uses)))
    return RedirectResponse(url=f"/settings?new_invite={code}", status_code=303)


@app.post("/settings/invites/{invite_id}/delete")
def settings_invite_delete(request: Request, invite_id: int):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with get_engine(request).begin() as conn:
        disable_invite(conn, invite_id, me["id"])
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/pages")
def settings_pages(
    request: Request,
    slug: str = Form(...),
    title: str = Form(...),
    content: str = Form(""),
    content_format: str = Form("html"),
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
                is_public=True,
            )
    except IntegrityError:
        return RedirectResponse(url="/settings?error=slug_taken", status_code=303)

    return RedirectResponse(
        url=f"/u/{me['username']}/page/{slug.strip()}", status_code=303
    )


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
            is_public=is_public == "on",
        )

    return RedirectResponse(
        url=f"/u/{me['username']}/page/{cleaned_slug}", status_code=303
    )
