"""Authentication routes: login, register, logout."""

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.deps import USERNAME_RE, get_engine, templates
from app.queries.users import create_user_with_invite, get_user_by_username
from app.security import verify_password

router = APIRouter()


@router.get("/register", response_class=HTMLResponse)
def register_get(request: Request, invite: str | None = None):
    return templates.TemplateResponse(
        request, "register.html", {"invite": invite, "error": None}
    )


@router.post("/register", response_class=HTMLResponse)
def register_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    invite_code: str = Form(...),
):
    cleaned_username = username.strip().lower()
    if not USERNAME_RE.match(cleaned_username):
        return templates.TemplateResponse(
            request,
            "register.html",
            {
                "invite": invite_code,
                "error": "Username must be 3-32 characters, lowercase letters, numbers, hyphens, or underscores",
            },
            status_code=400,
        )
    with get_engine(request).begin() as conn:
        user, error = create_user_with_invite(
            conn,
            username=cleaned_username,
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


@router.get("/login", response_class=HTMLResponse)
def login_get(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login", response_class=HTMLResponse)
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
    if user.get("is_disabled"):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "This account has been disabled"},
            status_code=403,
        )
    request.session["user_id"] = user["id"]
    return RedirectResponse(url=f"/u/{user['username']}", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)
