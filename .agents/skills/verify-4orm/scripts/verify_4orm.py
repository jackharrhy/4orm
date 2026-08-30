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
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from alembic import command
from alembic.config import Config
from playwright.sync_api import sync_playwright
from sqlalchemy import create_engine, insert

from app.oauth_policy import ARTBIN_ADMIN_SCOPE, ARTBIN_MCP_RESOURCE
from app.schema import (
    metadata,
    oauth2_clients,
    oauth2_tokens,
    pages,
    profile_cards,
    users,
)
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
        connection.execute(
            insert(oauth2_clients).values(
                client_id="browser-mcp-client",
                client_name="Browser MCP client",
                client_kind="public",
                registration_source="dynamic",
                redirect_uris="http://127.0.0.1:43127/oauth/callback",
                scope=ARTBIN_ADMIN_SCOPE,
                allowed_resources=ARTBIN_MCP_RESOURCE,
                grant_types="authorization_code refresh_token",
                response_types="code",
                token_endpoint_auth_method="none",
                access_token_lifetime=600,
            )
        )
        connection.execute(
            insert(oauth2_tokens).values(
                client_id="worldview",
                user_id=user_id,
                principal_type="user",
                subject=str(user_id),
                grant_type="authorization_code",
                access_token="browser-verification-token-not-for-production",
                scope="openid profile",
                issued_at=int(time.time()),
                expires_in=3600,
            )
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

                def design_reference():
                    page.goto(f"{base_url}/design", wait_until="domcontentloaded")
                    page.get_by_role("heading", name="design", exact=True).wait_for()
                    page.get_by_role(
                        "heading", name="the restrictions", exact=True
                    ).wait_for()
                    check(
                        page.locator(".fourm-swatch").count() == 6,
                        "design reference does not show all six palette swatches",
                    )
                    check(
                        page.evaluate(
                            "document.documentElement.scrollWidth <= innerWidth"
                        ),
                        "desktop design reference has horizontal overflow",
                    )
                    primary = page.get_by_role(
                        "button", name="primary action", exact=True
                    )
                    primary.focus()
                    check(
                        primary.evaluate("el => getComputedStyle(el).outlineStyle")
                        != "none",
                        "design reference primary action has no focus outline",
                    )
                    page.screenshot(
                        path=evidence / "02-design-desktop.png", full_page=True
                    )
                    return [
                        "all design sections visible",
                        "six palette swatches visible",
                        "primary action has visible focus",
                        "no horizontal overflow",
                    ]

                flow("desktop design reference", design_reference)

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

                consent_url = f"{base_url}/oauth/authorize?{
                    urlencode(
                        {
                            'response_type': 'code',
                            'client_id': 'browser-mcp-client',
                            'redirect_uri': 'http://127.0.0.1:43127/oauth/callback',
                            'scope': ARTBIN_ADMIN_SCOPE,
                            'state': 'browser-verification',
                            'code_challenge': 'a' * 43,
                            'code_challenge_method': 'S256',
                            'resource': ARTBIN_MCP_RESOURCE,
                        }
                    )
                }"

                def consent_contrast(button, boundary_property):
                    return button.evaluate(
                        """(element, boundaryProperty) => {
                          const rgb = (value) => {
                            const parts = value.match(/[\\d.]+/g).map(Number);
                            return parts.slice(0, 3);
                          };
                          const luminance = (value) => {
                            const channels = rgb(value).map((channel) => {
                              const normalized = channel / 255;
                              return normalized <= 0.04045
                                ? normalized / 12.92
                                : Math.pow((normalized + 0.055) / 1.055, 2.4);
                            });
                            return 0.2126 * channels[0]
                              + 0.7152 * channels[1]
                              + 0.0722 * channels[2];
                          };
                          const ratio = (first, second) => {
                            const lighter = Math.max(
                              luminance(first), luminance(second)
                            );
                            const darker = Math.min(
                              luminance(first), luminance(second)
                            );
                            return (lighter + 0.05) / (darker + 0.05);
                          };
                          const style = getComputedStyle(element);
                          const body = getComputedStyle(document.body);
                          return {
                            text: ratio(style.color, style.backgroundColor),
                            boundary: ratio(
                              style[boundaryProperty], body.backgroundColor
                            ),
                          };
                        }""",
                        boundary_property,
                    )

                def oauth_consent():
                    page.goto(consent_url, wait_until="domcontentloaded")
                    page.get_by_role(
                        "heading", name="authorize app", exact=True
                    ).wait_for()
                    check(
                        page.locator('input[name="resource"]').input_value()
                        == ARTBIN_MCP_RESOURCE,
                        "consent form did not preserve the validated resource",
                    )
                    check(
                        page.locator('input[name="scope"]').input_value()
                        == ARTBIN_ADMIN_SCOPE,
                        "consent form did not preserve the validated scope",
                    )
                    consent_text = page.locator("main").inner_text()
                    check(
                        ARTBIN_MCP_RESOURCE in consent_text,
                        "validated resource is not visible on the consent screen",
                    )
                    check(
                        ARTBIN_ADMIN_SCOPE in consent_text,
                        "requested scope is not visible on the consent screen",
                    )
                    approve = page.get_by_role("button", name="approve", exact=True)
                    deny = page.get_by_role("button", name="deny", exact=True)
                    approve_contrast = consent_contrast(approve, "backgroundColor")
                    deny_contrast = consent_contrast(deny, "borderTopColor")
                    check(
                        approve_contrast["text"] >= 4.5,
                        "approve button text contrast is below 4.5:1",
                    )
                    check(
                        approve_contrast["boundary"] >= 3,
                        "approve button boundary contrast is below 3:1",
                    )
                    check(
                        deny_contrast["text"] >= 4.5,
                        "deny button text contrast is below 4.5:1",
                    )
                    check(
                        deny_contrast["boundary"] >= 3,
                        "deny button boundary contrast is below 3:1",
                    )
                    approve.focus()
                    check(
                        approve.evaluate("el => getComputedStyle(el).outlineStyle")
                        != "none",
                        "approve button has no visible focus outline",
                    )
                    page.screenshot(
                        path=evidence / "03-oauth-consent-desktop.png", full_page=True
                    )
                    return {
                        "approveTextContrast": approve_contrast["text"],
                        "approveBoundaryContrast": approve_contrast["boundary"],
                        "denyTextContrast": deny_contrast["text"],
                        "denyBoundaryContrast": deny_contrast["boundary"],
                        "visibleFocusOutline": True,
                        "resourceVisible": ARTBIN_MCP_RESOURCE,
                        "scopeVisible": ARTBIN_ADMIN_SCOPE,
                    }

                flow("OAuth authorization consent", oauth_consent)

                def page_management():
                    page.goto(f"{base_url}/settings", wait_until="domcontentloaded")
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
                    worldview_login = (
                        panel.locator("article")
                        .filter(has=page.locator("code", has_text="worldview"))
                        .filter(has_not_text="worldview-service")
                    )
                    worldview_login.get_by_text("token usage", exact=True).click()
                    worldview_login.get_by_text(
                        "Visual Check (@visualcheck)", exact=True
                    ).wait_for()
                    check(
                        "browser-verification-token" not in panel.inner_text(),
                        "raw access token is visible in OAuth administration",
                    )
                    dynamic_client = panel.locator("article").filter(
                        has_text="browser-mcp-client"
                    )
                    check(
                        "dynamic" in dynamic_client.inner_text(),
                        "dynamic OAuth registration source is not visible",
                    )
                    check(
                        ARTBIN_MCP_RESOURCE in dynamic_client.inner_text(),
                        "dynamic OAuth allowed resource is not visible",
                    )
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
                        path=evidence / "04-oauth-admin-desktop.png", full_page=True
                    )
                    check(
                        page.evaluate(
                            "document.documentElement.scrollWidth <= innerWidth"
                        ),
                        "OAuth admin has horizontal overflow",
                    )
                    return [
                        "OAuth clients panel visible",
                        "dynamic client provenance and resource visible",
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
                        path=evidence / "05-home-mobile.png", full_page=True
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
                        path=evidence / "06-settings-mobile.png", full_page=True
                    )
                    page.goto(consent_url, wait_until="domcontentloaded")
                    page.get_by_role("button", name="approve", exact=True).wait_for()
                    check(
                        page.evaluate(
                            "document.documentElement.scrollWidth <= innerWidth"
                        ),
                        "mobile OAuth consent has horizontal overflow",
                    )
                    page.screenshot(
                        path=evidence / "07-oauth-consent-mobile.png", full_page=True
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
                        path=evidence / "08-oauth-admin-mobile.png", full_page=True
                    )
                    page.goto(f"{base_url}/design", wait_until="domcontentloaded")
                    page.get_by_role("heading", name="design", exact=True).wait_for()
                    check(
                        page.evaluate(
                            "document.documentElement.scrollWidth <= innerWidth"
                        ),
                        "mobile design reference has horizontal overflow",
                    )
                    page.screenshot(
                        path=evidence / "09-design-mobile.png", full_page=True
                    )
                    return [
                        "mobile homepage fits viewport",
                        "mobile settings fits viewport",
                        "mobile OAuth consent fits viewport",
                        "mobile OAuth admin fits viewport",
                        "mobile design reference fits viewport",
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
