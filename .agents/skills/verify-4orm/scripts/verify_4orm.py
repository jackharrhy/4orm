#!/usr/bin/env python3
"""Run isolated real-browser verification for 4orm."""

# The helper is executable by path, so the repository root must be added before
# importing the application modules below.
# ruff: noqa: E402, I001

import argparse
import contextlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from alembic import command
from alembic.config import Config
from playwright.sync_api import sync_playwright
from sqlalchemy import create_engine, insert

from app.schema import metadata, pages, profile_cards, users
from app.security import hash_password


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--headed", action="store_true")
    return parser.parse_args()


def unused_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def wait_for_http(url: str, process: subprocess.Popen, timeout: float = 30) -> None:
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"4orm exited before readiness ({process.returncode})")
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception as error:  # readiness keeps the last concrete failure
            last_error = error
        time.sleep(0.15)
    raise RuntimeError(f"4orm did not become ready: {last_error}")


def seed_database(database_url: str) -> None:
    engine = create_engine(database_url)
    metadata.create_all(engine)
    alembic_config = Config(str(ROOT / "alembic.ini"))
    alembic_config.set_main_option("sqlalchemy.url", database_url)
    with engine.begin() as connection:
        alembic_config.attributes["connection"] = connection
        command.stamp(alembic_config, "head")
        user_id = connection.execute(
            insert(users).values(
                username="visualcheck",
                password_hash=hash_password("visualcheck-pass"),
                display_name="Visual Check",
                content="A small profile used only for browser verification.",
                has_accepted_trust=True,
                is_admin=True,
            )
        ).inserted_primary_key[0]
        connection.execute(
            insert(profile_cards).values(
                user_id=user_id,
                headline="Visual Check",
                content="Browser verification profile card.",
            )
        )
        connection.execute(
            insert(pages),
            [
                {
                    "user_id": user_id,
                    "slug": "first-page",
                    "title": "First page",
                    "content": "<p>First verification page.</p>",
                },
                {
                    "user_id": user_id,
                    "slug": "second-page",
                    "title": "Second page",
                    "content": "<p>Second verification page.</p>",
                },
            ],
        )
    engine.dispose()


def stop_process(process: subprocess.Popen | None) -> None:
    if not process or process.poll() is not None:
        return
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    args = parse_args()
    timestamp = datetime.now(UTC).isoformat().replace(":", "-").replace(".", "-")
    evidence = (
        args.evidence or ROOT / "artifacts/verification/4orm" / timestamp
    ).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    runtime = Path(tempfile.mkdtemp(prefix="4orm-verification-"))
    database_url = f"sqlite:///{runtime / '4orm.db'}"
    server_log_path = evidence / "server.log"
    report = {
        "startedAt": datetime.now(UTC).isoformat(),
        "status": "running",
        "evidence": str(evidence),
        "runtime": str(runtime),
        "flows": [],
    }
    console_events = []
    server = None
    browser = None

    def persist():
        (evidence / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        (evidence / "console.json").write_text(
            json.dumps(console_events, indent=2) + "\n"
        )

    def flow(name, operation):
        entry = {"name": name, "status": "running"}
        report["flows"].append(entry)
        try:
            entry["assertions"] = operation()
            entry["status"] = "passed"
        except Exception as error:
            entry["status"] = "failed"
            entry["error"] = str(error)
            raise
        finally:
            persist()

    try:
        seed_database(database_url)
        port = unused_port()
        base_url = f"http://127.0.0.1:{port}"
        report["baseUrl"] = base_url
        environment = {
            **os.environ,
            "DATABASE_URL": database_url,
            "FOURM_ENV": "test",
            "SECRET_KEY": "4orm-browser-verification-only",
            "SITE_URL": base_url,
            "UVICORN_RELOAD": "1",
        }
        with server_log_path.open("w") as server_log:
            server = subprocess.Popen(
                [
                    "uv",
                    "run",
                    "uvicorn",
                    "app.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=ROOT,
                env=environment,
                stdout=server_log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            report["serverPid"] = server.pid
            persist()
            wait_for_http(base_url, server)

            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=not args.headed)
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                page.on(
                    "console",
                    lambda message: (
                        console_events.append(
                            {"type": f"console:{message.type}", "text": message.text}
                        )
                        if message.type in {"warning", "error"}
                        else None
                    ),
                )
                page.on(
                    "pageerror",
                    lambda error: console_events.append(
                        {"type": "pageerror", "text": str(error)}
                    ),
                )

                def desktop_home():
                    page.goto(base_url, wait_until="domcontentloaded")
                    page.get_by_role("link", name="4orm", exact=True).wait_for()
                    chat = page.get_by_role("link", name="chat", exact=True).last
                    box = chat.bounding_box()
                    check(box is not None, "chat callout has no visible box")
                    center = box["x"] + box["width"] / 2
                    delta = abs(center - 640)
                    page.screenshot(
                        path=evidence / "01-home-desktop.png", full_page=True
                    )
                    check(delta <= 2, f"chat callout is {delta:.1f}px off center")
                    check(
                        page.evaluate(
                            "document.documentElement.scrollWidth <= innerWidth"
                        ),
                        "homepage has horizontal overflow",
                    )
                    return {"chatCenterDeltaPx": delta, "noHorizontalOverflow": True}

                flow("desktop homepage", desktop_home)

                def login_and_settings():
                    page.get_by_role("link", name="login", exact=True).click()
                    page.get_by_label("username").fill("visualcheck")
                    page.get_by_label("password").fill("visualcheck-pass")
                    page.get_by_role("button", name="enter", exact=True).click()
                    page.get_by_role("link", name="settings", exact=True).wait_for()
                    page.get_by_role("link", name="settings", exact=True).click()
                    page.get_by_role("heading", name="settings", exact=True).wait_for()
                    page.screenshot(
                        path=evidence / "02-settings-desktop.png", full_page=True
                    )
                    return ["logged in through visible form", "settings page visible"]

                flow("login and settings", login_and_settings)

                def page_management():
                    row = page.locator("#page-first-page")
                    edit_box = row.get_by_role(
                        "link", name="edit", exact=True
                    ).bounding_box()
                    delete_box = row.get_by_role(
                        "button", name="delete", exact=True
                    ).bounding_box()
                    check(edit_box and delete_box, "page controls are not both visible")
                    delta = abs(
                        (edit_box["y"] + edit_box["height"] / 2)
                        - (delete_box["y"] + delete_box["height"] / 2)
                    )
                    check(
                        delta <= 3, f"edit and delete controls differ by {delta:.1f}px"
                    )
                    return {"editDeleteVerticalDeltaPx": delta}

                flow("page management layout", page_management)

                def oauth_admin():
                    page.goto(
                        f"{base_url}/admin#oauth-clients",
                        wait_until="domcontentloaded",
                    )
                    panel = page.locator("#oauth-clients")
                    panel.get_by_role(
                        "heading", name="OAuth clients", exact=False
                    ).wait_for()
                    worldview = panel.locator("article").filter(
                        has_text="worldview-service"
                    )
                    worldview.get_by_role(
                        "button", name="generate secret", exact=True
                    ).click()
                    secret = worldview.locator(".fourm-secret-value")
                    secret.wait_for()
                    check(
                        len(secret.inner_text()) >= 48,
                        "generated secret is unexpectedly short",
                    )
                    page.screenshot(
                        path=evidence / "03-oauth-admin-desktop.png", full_page=True
                    )
                    check(
                        page.evaluate(
                            "document.documentElement.scrollWidth <= innerWidth"
                        ),
                        "OAuth admin has horizontal overflow",
                    )
                    return [
                        "OAuth clients panel visible",
                        "one-time secret result visible",
                        "no horizontal overflow",
                    ]

                flow("OAuth client administration", oauth_admin)

                def mobile_layouts():
                    page.set_viewport_size({"width": 390, "height": 844})
                    page.goto(base_url, wait_until="domcontentloaded")
                    check(
                        page.evaluate(
                            "document.documentElement.scrollWidth <= innerWidth"
                        ),
                        "mobile homepage has horizontal overflow",
                    )
                    page.screenshot(
                        path=evidence / "03-home-mobile.png", full_page=True
                    )
                    page.goto(f"{base_url}/settings", wait_until="domcontentloaded")
                    page.get_by_role("heading", name="settings", exact=True).wait_for()
                    check(
                        page.evaluate(
                            "document.documentElement.scrollWidth <= innerWidth"
                        ),
                        "mobile settings has horizontal overflow",
                    )
                    page.screenshot(
                        path=evidence / "04-settings-mobile.png", full_page=True
                    )
                    page.goto(
                        f"{base_url}/admin#oauth-clients",
                        wait_until="domcontentloaded",
                    )
                    check(
                        page.evaluate(
                            "document.documentElement.scrollWidth <= innerWidth"
                        ),
                        "mobile OAuth admin has horizontal overflow",
                    )
                    page.screenshot(
                        path=evidence / "05-oauth-admin-mobile.png", full_page=True
                    )
                    return [
                        "mobile homepage fits viewport",
                        "mobile settings fits viewport",
                        "mobile OAuth admin fits viewport",
                    ]

                flow("mobile layouts", mobile_layouts)
                unexpected = [
                    event
                    for event in console_events
                    if event["type"] in {"console:error", "pageerror"}
                ]
                check(not unexpected, f"browser emitted {len(unexpected)} error(s)")
                report["status"] = "passed"
                browser.close()
                browser = None
    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error)
        if browser:
            pages_open = [
                page for context in browser.contexts for page in context.pages
            ]
            if pages_open:
                with contextlib.suppress(Exception):
                    pages_open[-1].screenshot(
                        path=evidence / "failure.png", full_page=True
                    )
        return_code = 1
    else:
        return_code = 0
    finally:
        report["finishedAt"] = datetime.now(UTC).isoformat()
        persist()
        if browser:
            with contextlib.suppress(Exception):
                browser.close()
        stop_process(server)
        shutil.rmtree(runtime)
        print(f"{report['status'].upper()}: {evidence}")
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
