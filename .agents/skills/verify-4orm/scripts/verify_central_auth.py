#!/usr/bin/env python3
"""Verify 4orm using a disposable signed HTTPS identity provider and database."""

import argparse
import base64
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))

from alembic.config import Config  # noqa: E402
from oidc_fixture import CLIENT_ID, SUBJECT, provider  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402
from sqlalchemy import create_engine, insert  # noqa: E402

from alembic import command  # noqa: E402
from app.schema import (  # noqa: E402
    external_identities,
    metadata,
    pages,
    profile_cards,
    users,
)


def seed(database_url, issuer):
    engine = create_engine(database_url)
    metadata.create_all(engine)
    with engine.begin() as conn:
        config = Config(str(ROOT / "alembic.ini"))
        config.attributes["connection"] = conn
        command.stamp(config, "head")
        uid = conn.execute(
            insert(users).values(
                username="visualcheck",
                display_name="Visual Check",
                password_hash="unused-external-identity",
                has_accepted_trust=True,
                is_admin=True,
            )
        ).inserted_primary_key[0]
        conn.execute(
            insert(external_identities).values(
                user_id=uid,
                issuer=issuer,
                subject=SUBJECT,
            )
        )
        conn.execute(insert(profile_cards).values(user_id=uid, headline="Visual Check"))
        conn.execute(
            insert(pages),
            [
                {
                    "user_id": uid,
                    "slug": "first-page",
                    "title": "First page",
                    "content": "<p>First fixture page.</p>",
                },
                {
                    "user_id": uid,
                    "slug": "second-page",
                    "title": "Second page",
                    "content": "<p>Second fixture page.</p>",
                },
            ],
        )
    engine.dispose()


@contextmanager
def application(base_url, port, environment, log_path):
    with log_path.open("w") as log:
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
                "--no-access-log",
            ],
            cwd=ROOT,
            env=environment,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
        try:
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError("Isolated 4orm exited; inspect server.log")
                try:
                    with urlopen(base_url, timeout=1) as response:
                        assert response.status == 200
                    break
                except OSError:
                    time.sleep(0.1)
            else:
                raise RuntimeError("Isolated 4orm did not become ready")
            yield
        finally:
            if server.poll() is None:
                os.killpg(server.pid, signal.SIGTERM)
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(server.pid, signal.SIGKILL)
                    server.wait(timeout=5)


def verify_async_controls(page, width, base_url, evidence):
    page.goto(base_url + "/forum/new")
    page.get_by_role("heading", name="new thread", exact=True).wait_for()
    page.locator("#thread-content").fill("A stateful preview")
    page.get_by_role("button", name="preview", exact=True).click()
    preview = page.locator("#preview-thread-content")
    page.wait_for_function(
        "document.getElementById('preview-thread-content').dataset.state === 'success'"
    )
    assert preview.is_visible()
    assert "A stateful preview" in preview.inner_text()
    assert preview.get_attribute("aria-busy") == "false"
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
    )
    page.locator("#media-upload-file-thread-content").set_input_files(
        {"name": f"state-{width}.png", "mimeType": "image/png", "buffer": png}
    )
    page.locator("#media-picker-thread-content [data-upload-button]").click()
    page.wait_for_function(
        "document.getElementById('media-picker-thread-content')"
        ".dataset.state === 'success'"
    )
    assert (
        page.locator("#media-upload-status-thread-content").inner_text() == "Uploaded."
    )
    assert page.locator(
        "#media-picker-thread-content [data-upload-button]"
    ).is_enabled()
    selected = page.locator("#media-select-thread-content").input_value()
    uploaded = page.request.get(base_url + "/uploads/" + selected)
    assert uploaded.status == 200 and uploaded.body() == png
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    page.screenshot(path=evidence / f"async-controls-{width}.png", full_page=True)


def verify_viewport(browser, width, base_url, evidence, events):
    context = browser.new_context(
        viewport={"width": width, "height": 900},
        ignore_https_errors=True,
    )
    try:
        page = context.new_page()
        page.on(
            "pageerror",
            lambda error: events.append({"type": "pageerror", "message": str(error)}),
        )
        page.on(
            "console",
            lambda message: (
                events.append({"type": message.type, "message": message.text})
                if message.type in {"warning", "error"}
                else None
            ),
        )
        no_overflow = "document.documentElement.scrollWidth <= innerWidth"
        page.goto(base_url)
        assert "4orm" in page.title().lower()
        assert page.evaluate(no_overflow)
        page.screenshot(path=evidence / f"home-{width}.png", full_page=True)
        page.get_by_role("link", name="login", exact=True).click()
        page.get_by_role("heading", name="Test identity provider").wait_for()
        page.get_by_label("username").fill("visualcheck")
        page.get_by_label("password").fill("visualcheck-pass")
        page.get_by_role("button", name="Sign in", exact=True).click()
        page.wait_for_url(base_url + "/u/visualcheck")
        page.get_by_role("link", name="settings", exact=True).click()
        page.get_by_role("heading", name="settings", exact=True).wait_for()
        assert page.evaluate(no_overflow)
        rows = page.locator("#pages-section li")
        assert rows.count() == 2
        for row in rows.all():
            edit = row.get_by_role("link", name="edit", exact=True).bounding_box()
            delete = row.get_by_role("button", name="delete", exact=True).bounding_box()
            assert edit and delete and abs(edit["y"] - delete["y"]) < 4
        page.screenshot(path=evidence / f"settings-{width}.png", full_page=True)
        verify_async_controls(page, width, base_url, evidence)
        page.goto(base_url + "/admin")
        page.get_by_role("heading", name="admin", exact=True).wait_for()
        assert page.locator("#oauth-clients").count() == 0
        assert page.locator('a[href="/admin/oauth"]').count() == 0
        page.locator("#user-row-1 > summary").click()
        assert page.get_by_role(
            "button", name="manage Jack Auth", exact=True
        ).is_visible()
        assert page.evaluate(no_overflow)
        page.screenshot(path=evidence / f"admin-{width}.png", full_page=True)
        invalid_url = base_url + "/auth/callback?state=invalid&code=invalid"
        assert context.request.get(invalid_url).status == 400
        return {
            "width": width,
            "signedOidcLogin": True,
            "settings": True,
            "actualPreviewAndUpload": True,
            "pageActionsAligned": True,
            "centralIdentityAdmin": True,
            "issuerAdminRemoved": True,
            "invalidStateRejected": True,
            "noHorizontalOverflow": True,
        }
    finally:
        context.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    evidence = (
        args.evidence or ROOT / "artifacts/verification/central" / stamp
    ).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    report = {"status": "running", "isolated": True, "flows": []}
    events = []
    try:
        with tempfile.TemporaryDirectory(prefix="4orm-central-verification-") as temp:
            runtime = Path(temp)
            (runtime / "uploads").mkdir()
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            base_url = f"http://127.0.0.1:{port}"
            with provider(runtime, base_url + "/auth/callback") as (
                issuer,
                certificate,
            ):
                database_url = f"sqlite:///{runtime / '4orm.db'}"
                seed(database_url, issuer)
                env = {
                    **os.environ,
                    "DATABASE_URL": database_url,
                    "FOURM_UPLOADS_DIR": str(runtime / "uploads"),
                    "FOURM_ENV": "test",
                    "SECRET_KEY": "isolated-central-browser-verification-only",
                    "SITE_URL": base_url,
                    "UVICORN_RELOAD": "1",
                    "OIDC_ISSUER": issuer,
                    "OIDC_CLIENT_ID": CLIENT_ID,
                    "OIDC_REDIRECT_URI": base_url + "/auth/callback",
                    "SSL_CERT_FILE": str(certificate),
                }
                with (
                    application(base_url, port, env, evidence / "server.log"),
                    sync_playwright() as playwright,
                ):
                    browser = playwright.chromium.launch()
                    try:
                        for width in (1280, 390):
                            report["flows"].append(
                                verify_viewport(
                                    browser, width, base_url, evidence, events
                                )
                            )
                    finally:
                        browser.close()
        assert not events, "Browser errors; inspect console.json"
        report["status"] = "passed"
        print(f"PASSED: {evidence}")
        return 0
    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error)
        print(f"FAILED: {evidence}")
        return 1
    finally:
        (evidence / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        (evidence / "console.json").write_text(json.dumps(events, indent=2) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
