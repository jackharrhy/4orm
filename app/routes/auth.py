"""Authentication routes: login, register, logout."""

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import update

from app.deps import (
    USERNAME_INVALID_MSG,
    USERNAME_RE,
    current_user,
    get_engine,
    templates,
)
from app.queries.users import create_user_with_invite, get_user_by_username
from app.schema import users
from app.security import verify_password

router = APIRouter(tags=["auth"])


@router.get("/register", response_class=HTMLResponse, summary="Registration page")
def register_get(request: Request, invite: str | None = None):
    return templates.TemplateResponse(
        request, "register.html", {"invite": invite, "error": None}
    )


@router.post("/register", response_class=HTMLResponse, summary="Register a new account")
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
                "error": USERNAME_INVALID_MSG,
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
    return RedirectResponse(url="/trust-agreement", status_code=303)


@router.get("/login", response_class=HTMLResponse, summary="Login page")
def login_get(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login", response_class=HTMLResponse, summary="Authenticate user")
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


@router.get(
    "/trust-agreement", response_class=HTMLResponse, summary="Trust agreement page"
)
def trust_agreement_get(request: Request):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    if me.get("has_accepted_trust"):
        return RedirectResponse(url=f"/u/{me['username']}", status_code=303)
    return templates.TemplateResponse(request, "trust_agreement.html", {"me": me})


@router.post("/trust-agreement", summary="Accept trust agreement")
def trust_agreement_post(request: Request, accept: str = Form(...)):
    me = current_user(request)
    if not me:
        return RedirectResponse(url="/login", status_code=303)
    with get_engine(request).begin() as conn:
        conn.execute(
            update(users).where(users.c.id == me["id"]).values(has_accepted_trust=True)
        )
    return RedirectResponse(url=f"/u/{me['username']}", status_code=303)


@router.post("/logout", summary="Log out")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)
