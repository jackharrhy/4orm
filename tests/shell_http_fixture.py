"""Loopback-only real provider fixture; never imports a production database.

Started by newport-shell-remix/tests/oauth-http.test.ts. Only identity/client
seed data is synthetic: login, consent, grants, PKCE, tokens and revocation run
through the production application. No pre-issued grants or owner tokens.
"""

import os
import socket
from contextlib import asynccontextmanager

os.environ["FOURM_ENV"] = "test"
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SITE_URL"] = "https://4orm.harrhy.xyz"

import uvicorn
from loguru import logger
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.main import app
from app.schema import metadata
from tests.conftest import make_admin_user, make_test_user
from tests.test_oauth2_artbin_mcp import _seed_user_and_introspector

engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
metadata.create_all(engine)
_seed_user_and_introspector(engine)
with engine.begin() as conn:
    owner = make_admin_user(conn, "harrhy")
    make_test_user(conn, "nonowner")


@asynccontextmanager
async def lifespan(application):
    application.state.engine = engine
    yield
    engine.dispose()


app.router.lifespan_context = lifespan
logger.remove()  # no request URLs, cookies, codes or tokens in test output
sock = socket.socket()
sock.bind(("127.0.0.1", 0))
sock.listen(128)
print(f"FIXTURE_READY {sock.getsockname()[1]} {owner}", flush=True)
uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False)).run(
    sockets=[sock]
)
