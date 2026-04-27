"""Authentication routes: login, register, logout."""

from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import update

from app.deps import (
    USERNAME_INVALID_MSG,
    USERNAME_RE,
    current_user,
    get_engine,
    json_response,
    templates,
    wants_json,
)
from app.models import AuthResponse, SuccessResponse
from app.queries.users import (
    create_user_with_invite,
    get_user_by_username,
    get_valid_password_reset_token,
    invalidate_user_password_reset_tokens,
    mark_password_reset_token_used,
)
from app.schema import users
from app.security import hash_password, verify_password

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
        if wants_json(request):
            return JSONResponse(
                {"ok": False, "error": USERNAME_INVALID_MSG}, status_code=400
            )
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
        if wants_json(request):
            return JSONResponse({"ok": False, "error": error}, status_code=400)
        return templates.TemplateResponse(
            request,
            "register.html",
            {"invite": invite_code, "error": error},
            status_code=400,
        )
    request.session["user_id"] = user["id"]
    if wants_json(request):
        return json_response(
            AuthResponse(
                username=user["username"],
                display_name=user["display_name"],
                redirect="/trust-agreement",
            )
        )
    return RedirectResponse(url="/trust-agreement", status_code=303)


def _pop_oauth_redirect(request: Request) -> str | None:
    """If login was triggered by an OAuth flow, reconstruct the authorize URL.

    The per-request params (state, code_challenge, etc.) are stashed in the
    session by ``/oauth/authorize``; the ``?next=oauth`` query param tells us
    to look for them.
    """
    oauth_params = request.session.pop("oauth_params", None)
    if not oauth_params:
        return None
    return f"/oauth/authorize?{urlencode(oauth_params)}"


@router.get("/login", response_class=HTMLResponse, summary="Login page")
def login_get(request: Request):
    next_kind = request.query_params.get("next", "")
    client_id = request.query_params.get("client_id", "")
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "error": None,
            "success": request.query_params.get("success"),
            "next": next_kind,
            "client_id": client_id,
        },
    )


@router.post("/login", response_class=HTMLResponse, summary="Authenticate user")
def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form(""),
    client_id: str = Form(""),
):
    with get_engine(request).begin() as conn:
        user = get_user_by_username(conn, username.strip())
    if not user or not verify_password(password, user["password_hash"]):
        if wants_json(request):
            return JSONResponse(
                {"ok": False, "error": "invalid credentials"}, status_code=400
            )
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "invalid credentials", "next": next, "client_id": client_id},
            status_code=400,
        )
    if user.get("is_disabled"):
        if wants_json(request):
            return JSONResponse(
                {"ok": False, "error": "this account has been disabled"},
                status_code=403,
            )
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "this account has been disabled", "next": next, "client_id": client_id},
            status_code=403,
        )
    request.session["user_id"] = user["id"]

    # Check for a pending OAuth flow
    redirect_to = None
    if next == "oauth":
        redirect_to = _pop_oauth_redirect(request)
    if not redirect_to:
        redirect_to = f"/u/{user['username']}"

    if wants_json(request):
        return json_response(
            AuthResponse(
                username=user["username"],
                display_name=user["display_name"],
                redirect=redirect_to,
            )
        )
    return RedirectResponse(url=redirect_to, status_code=303)


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
    if wants_json(request):
        return SuccessResponse(message="trust agreement accepted")
    return RedirectResponse(url=f"/u/{me['username']}", status_code=303)


@router.post("/logout", summary="Log out")
def logout(request: Request):
    request.session.clear()
    if wants_json(request):
        return SuccessResponse(message="logged out")
    return RedirectResponse(url="/", status_code=303)


@router.get("/login/forgot-password", response_class=HTMLResponse)
def forgot_password_get(request: Request, token: str = ""):
    if not token:
        return templates.TemplateResponse(
            request,
            "forgot_password.html",
            {
                "error": "invalid or expired reset link",
                "token": "",
                "success": None,
            },
            status_code=400,
        )

    with get_engine(request).begin() as conn:
        reset_row = get_valid_password_reset_token(conn, token)

    if not reset_row:
        return templates.TemplateResponse(
            request,
            "forgot_password.html",
            {
                "error": "invalid or expired reset link",
                "token": "",
                "success": None,
            },
            status_code=400,
        )

    return templates.TemplateResponse(
        request,
        "forgot_password.html",
        {"error": None, "token": token, "success": None},
    )


@router.post("/login/forgot-password", response_class=HTMLResponse)
def forgot_password_post(
    request: Request,
    token: str = Form(""),
    password: str = Form(""),
    password_confirm: str = Form(""),
):
    if not token:
        return templates.TemplateResponse(
            request,
            "forgot_password.html",
            {
                "error": "invalid or expired reset link",
                "token": "",
                "success": None,
            },
            status_code=400,
        )

    if not password or password != password_confirm:
        return templates.TemplateResponse(
            request,
            "forgot_password.html",
            {
                "error": "passwords do not match",
                "token": token,
                "success": None,
            },
            status_code=400,
        )

    with get_engine(request).begin() as conn:
        reset_row = get_valid_password_reset_token(conn, token)
        if not reset_row:
            return templates.TemplateResponse(
                request,
                "forgot_password.html",
                {
                    "error": "invalid or expired reset link",
                    "token": "",
                    "success": None,
                },
                status_code=400,
            )

        conn.execute(
            update(users)
            .where(users.c.id == reset_row["user_id"])
            .values(password_hash=hash_password(password))
        )
        mark_password_reset_token_used(conn, reset_row["id"])
        invalidate_user_password_reset_tokens(conn, reset_row["user_id"])

    return RedirectResponse(
        url="/login?success=password+updated%2C+you+can+log+in+now",
        status_code=303,
    )
