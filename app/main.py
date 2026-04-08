from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.db import engine as default_engine
from app.deps import BASE_DIR, current_user, get_engine, templates
from app.queries.users import list_profile_cards
from app.rendering import render_content
from app.routes import admin, auth, feeds, forum, guestbook, media, pages, settings
from app.schema import create_all


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

# Include all route modules
app.include_router(auth.router)
app.include_router(pages.router)
app.include_router(settings.router)
app.include_router(media.router)
app.include_router(admin.router)
app.include_router(guestbook.router)
app.include_router(feeds.router)
app.include_router(forum.router)


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
