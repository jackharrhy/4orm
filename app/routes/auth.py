"""Member sessions, invitations and central account navigation."""

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import update

from app import oidc
from app.deps import current_user, get_engine, templates, wants_json
from app.models import SuccessResponse
from app.schema import users

router = APIRouter(tags=["auth"])


@router.get("/register", response_class=HTMLResponse, summary="Registration page")
def register_get(request: Request, invite: str | None = None):
    return templates.TemplateResponse(
        request, "register_central.html", {"invite": invite, "error": None}
    )


@router.get("/login", summary="Sign in through Jack Auth")
def login_get():
    return RedirectResponse("/auth/start", 303)


@router.get("/trust-agreement", response_class=HTMLResponse)
def trust_agreement_get(request: Request):
    me = current_user(request)
    if not me:
        return RedirectResponse("/login", 303)
    if me["has_accepted_trust"]:
        return RedirectResponse(f"/u/{me['username']}", 303)
    return templates.TemplateResponse(request, "trust_agreement.html", {"me": me})


@router.post("/trust-agreement")
def trust_agreement_post(request: Request, accept: str = Form(...)):
    me = current_user(request)
    if not me:
        return RedirectResponse("/login", 303)
    with get_engine(request).begin() as conn:
        conn.execute(
            update(users).where(users.c.id == me["id"]).values(has_accepted_trust=True)
        )
    if wants_json(request):
        return SuccessResponse(message="trust agreement accepted")
    return RedirectResponse(f"/u/{me['username']}", 303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    if wants_json(request):
        return SuccessResponse(message="logged out")
    return RedirectResponse("/", 303)


@router.get("/login/forgot-password")
def forgot_password_get():
    return RedirectResponse(oidc.configuration()[0] + "/forgot-password", 303)
