from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from app.db import engine
from app.queries.pages import create_page, get_public_page, list_public_pages_for_user
from app.queries.pages import get_user_page, list_pages_for_user, update_user_page
from app.queries.media import create_media, delete_media_for_user, get_media_for_user, list_media_for_user, update_media_alt_text
from app.queries.users import (
    create_invite,
    create_user_with_invite,
    get_user_by_id,
    get_user_by_username,
    lineage_for_user,
    list_inventory_cards,
)
from app.schema import create_all, inventory_cards, users
from app.security import verify_password
from sqlalchemy import select, update


BASE_DIR = Path(__file__).resolve().parent.parent
UPLOADS_DIR = BASE_DIR / "uploads"
app = FastAPI(title="4orm")
app.add_middleware(SessionMiddleware, secret_key="replace-this-dev-key")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.mount("/uploads", StaticFiles(directory=BASE_DIR / "uploads"), name="uploads")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


@app.on_event("startup")
def on_startup():
    create_all(engine)


def current_user(request: Request):
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    with engine.begin() as conn:
        return get_user_by_id(conn, user_id)


@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    with engine.begin() as conn:
        cards = list_inventory_cards(conn)
    return templates.TemplateResponse("home.html", {"request": request, "cards": cards, "me": current_user(request)})


@app.get("/inventory", response_class=HTMLResponse)
def inventory(request: Request):
    with engine.begin() as conn:
        cards = list_inventory_cards(conn)
    return templates.TemplateResponse("inventory.html", {"request": request, "cards": cards, "me": current_user(request)})


@app.get("/register", response_class=HTMLResponse)
def register_get(request: Request, invite: Optional[str] = None):
    return templates.TemplateResponse("register.html", {"request": request, "invite": invite, "error": None})


@app.post("/register", response_class=HTMLResponse)
def register_post(request: Request, username: str = Form(...), password: str = Form(...), invite_code: str = Form(...)):
    with engine.begin() as conn:
        user, error = create_user_with_invite(conn, username=username.strip(), password=password, invite_code=invite_code.strip())
    if error:
        return templates.TemplateResponse(
            "register.html", {"request": request, "invite": invite_code, "error": error}, status_code=400
        )
    request.session["user_id"] = user["id"]
    return RedirectResponse(url=f"/u/{user['username']}", status_code=303)


@app.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login", response_class=HTMLResponse)
def login_post(request: Request, username: str = Form(...), password: str = Form(...)):
    with engine.begin() as conn:
        user = get_user_by_username(conn, username.strip())
    if not user or not verify_password(password, user["password_hash"]):
        return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid credentials"}, status_code=400)
    request.session["user_id"] = user["id"]
    return RedirectResponse(url=f"/u/{user['username']}", status_code=303)


@app.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


@app.get("/u/{username}", response_class=HTMLResponse)
def profile(request: Request, username: str):
    with engine.begin() as conn:
        user = get_user_by_username(conn, username)
        if not user:
            raise HTTPException(404)
        pages = list_public_pages_for_user(conn, username)
    return templates.TemplateResponse("profile.html", {"request": request, "profile": user, "pages": pages, "me": current_user(request)})


@app.get("/u/{username}/page/{slug}", response_class=HTMLResponse)
def page_view(request: Request, username: str, slug: str):
    with engine.begin() as conn:
        page = get_public_page(conn, username, slug)
    if not page:
        raise HTTPException(404)
    return templates.TemplateResponse("page.html", {"request": request, "page": page, "me": current_user(request)})


@app.get("/lineage/{username}", response_class=HTMLResponse)
def lineage(request: Request, username: str):
    with engine.begin() as conn:
        chain = lineage_for_user(conn, username)
    if not chain:
        raise HTTPException(404)
    return templates.TemplateResponse("lineage.html", {"request": request, "chain": chain, "me": current_user(request)})


@app.get("/settings", response_class=HTMLResponse)
def settings_get(request: Request):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with engine.begin() as conn:
        my_pages = list_pages_for_user(conn, me["id"])
        card_settings = conn.execute(select(inventory_cards).where(inventory_cards.c.user_id == me["id"])).mappings().first()
        media_items = list_media_for_user(conn, me["id"])
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "me": me,
            "my_pages": my_pages,
            "card_settings": card_settings,
            "media_items": media_items,
            "error": None,
        },
    )


@app.get("/settings/media", response_class=HTMLResponse)
def settings_media_get(request: Request):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with engine.begin() as conn:
        items = list_media_for_user(conn, me["id"])
    return templates.TemplateResponse("settings_media.html", {"request": request, "me": me, "items": items})


@app.post("/settings/media/upload")
async def settings_media_upload(request: Request, files: list[UploadFile] = File(...)):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)

    user_upload_dir = UPLOADS_DIR / str(me["id"])
    user_upload_dir.mkdir(parents=True, exist_ok=True)

    with engine.begin() as conn:
        for f in files:
            suffix = Path(f.filename or "").suffix[:16]
            filename = f"{uuid4().hex}{suffix}"
            rel_path = f"{me['id']}/{filename}"
            disk_path = UPLOADS_DIR / rel_path
            content = await f.read()
            disk_path.write_bytes(content)
            create_media(
                conn,
                user_id=me["id"],
                storage_path=rel_path,
                mime_type=f.content_type or "application/octet-stream",
                size_bytes=len(content),
            )

    return RedirectResponse(url="/settings/media", status_code=303)


@app.post("/settings/media/{media_id}/alt")
def settings_media_alt(request: Request, media_id: int, alt_text: str = Form("")):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with engine.begin() as conn:
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
    with engine.begin() as conn:
        item = get_media_for_user(conn, me["id"], media_id)
        if not item:
            raise HTTPException(404)
        delete_media_for_user(conn, me["id"], media_id)
    disk_path = UPLOADS_DIR / item["storage_path"]
    if disk_path.exists():
        disk_path.unlink()
    return RedirectResponse(url="/settings/media", status_code=303)


@app.post("/settings/profile")
def settings_profile(request: Request, display_name: str = Form(""), bio: str = Form("")):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with engine.begin() as conn:
        conn.execute(update(users).where(users.c.id == me["id"]).values(display_name=display_name, bio=bio))
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/css")
def settings_css(request: Request, custom_css: str = Form("")):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with engine.begin() as conn:
        conn.execute(update(users).where(users.c.id == me["id"]).values(custom_css=custom_css))
    return RedirectResponse(url="/settings", status_code=303)


@app.post("/settings/card")
def settings_card(
    request: Request,
    headline: str = Form(""),
    subhead: str = Form(""),
    accent_color: str = Form("#00ffff"),
    border_style: str = Form("outset"),
    card_css: str = Form(""),
):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)

    with engine.begin() as conn:
        conn.execute(
            update(inventory_cards)
            .where(inventory_cards.c.user_id == me["id"])
            .values(
                headline=headline,
                subhead=subhead,
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

    with engine.begin() as conn:
        code = create_invite(conn, me["id"], max_uses=max(1, min(50, max_uses)))
    return RedirectResponse(url=f"/settings?new_invite={code}", status_code=303)


@app.post("/settings/pages")
def settings_pages(request: Request, slug: str = Form(...), title: str = Form(...), content_html: str = Form("")):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)

    with engine.begin() as conn:
        create_page(conn, user_id=me["id"], slug=slug.strip(), title=title.strip(), content_html=content_html, is_public=True)

    return RedirectResponse(url=f"/u/{me['username']}/page/{slug.strip()}", status_code=303)


@app.get("/settings/pages/{slug}/edit", response_class=HTMLResponse)
def settings_pages_edit_get(request: Request, slug: str):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)

    with engine.begin() as conn:
        page = get_user_page(conn, me["id"], slug)
        media_items = list_media_for_user(conn, me["id"])

    if not page:
        raise HTTPException(404)

    return templates.TemplateResponse(
        "edit_page.html",
        {"request": request, "me": me, "page": page, "media_items": media_items, "error": None},
    )


@app.post("/settings/pages/{slug}/edit")
def settings_pages_edit_post(
    request: Request,
    slug: str,
    new_slug: str = Form(...),
    title: str = Form(...),
    content_html: str = Form(""),
    is_public: Optional[str] = Form(None),
):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)

    cleaned_slug = new_slug.strip()
    with engine.begin() as conn:
        page = get_user_page(conn, me["id"], slug)
        if not page:
            raise HTTPException(404)
        update_user_page(
            conn,
            me["id"],
            slug,
            slug=cleaned_slug,
            title=title.strip(),
            content_html=content_html,
            is_public=is_public == "on",
        )

    return RedirectResponse(url=f"/u/{me['username']}/page/{cleaned_slug}", status_code=303)
