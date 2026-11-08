"""Exercise the real native CLI and central browser login without printing tokens."""

import argparse
import json
import os
import selectors
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import sync_playwright


def login_url(process):
    deadline = time.monotonic() + 30
    pending = b""
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ)
        while time.monotonic() < deadline:
            if selector.select(timeout=1):
                pending += os.read(process.stdout.fileno(), 65536)
                while b"\n" in pending:
                    line, pending = pending.split(b"\n", 1)
                    if line.startswith(b"https://auth.jackharrhy.dev/"):
                        return line.decode().strip()
                if process.poll() is not None:
                    break
    raise RuntimeError("CLI did not provide a central authorization URL")


def run(args):
    origin = args.origin.rstrip("/")
    parsed = urlparse(origin)
    if origin != "https://4orm.harrhy.xyz" and not (
        parsed.scheme == "http" and parsed.hostname == "127.0.0.1"
    ):
        raise ValueError("Acceptance requires live 4orm or an isolated loopback canary")
    checkpoint = json.loads(args.checkpoint.read_text())
    with tempfile.TemporaryDirectory(prefix="4orm-cli-acceptance-") as temporary:
        environment = dict(os.environ, XDG_CONFIG_HOME=temporary)
        environment["4ORM_URL"] = origin
        environment.pop("4ORM_TOKEN", None)
        process = subprocess.Popen(
            [str(args.binary.resolve()), "login"],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        try:
            authorization = login_url(process)
            query = parse_qs(urlparse(authorization).query)
            assert query["redirect_uri"] == ["http://localhost:4444/auth/cli/callback"]
            assert query["code_challenge_method"] == ["S256"]
            assert query["state"] and query["nonce"]
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch()
                context = browser.new_context()
                page = context.new_page()
                try:
                    page.goto(authorization)
                    page.locator("input[name=username]").fill(args.account)
                    page.locator("input[name=password]").fill(
                        checkpoint["user_" + args.account]["password"]
                    )
                    page.get_by_role("button", name="Sign in", exact=True).click()
                    page.wait_for_url("http://localhost:4444/auth/cli/callback?**")
                    assert process.wait(timeout=30) == 0
                    print("PASS: native PKCE, state, signed identity and nonce login")
                    config = Path(temporary) / "4orm/config.json"
                    credentials = json.loads(config.read_text())
                    assert credentials["issuer"] == "https://auth.jackharrhy.dev"
                    assert credentials["client_id"] == query["client_id"][0]

                    def command(*arguments):
                        result = subprocess.run(
                            [str(args.binary.resolve()), *arguments],
                            env=environment,
                            capture_output=True,
                            timeout=30,
                            check=False,
                        )
                        assert result.returncode == 0, (
                            "Authenticated CLI command failed"
                        )
                        return result.stdout

                    before = command("whoami")
                    assert before.strip(), "CLI did not resolve the existing identity"
                    command("page", "list")
                    command("media", "list")
                    print("PASS: real API profile, page listing and media listing")
                    credentials["access_token"] = (
                        "invalid-access-token-for-refresh-check"
                    )
                    config.write_text(json.dumps(credentials))
                    assert command("whoami") == before
                    refreshed = json.loads(config.read_text())
                    assert refreshed["access_token"] != credentials["access_token"]
                    print("PASS: central refresh restores the same local profile")
                    for kind in ("refresh_token", "access_token"):
                        response = context.request.post(
                            "https://auth.jackharrhy.dev/oauth/v2/revoke",
                            form={
                                "token": refreshed[kind],
                                "token_type_hint": kind,
                                "client_id": refreshed["client_id"],
                            },
                            max_redirects=0,
                        )
                        assert response.status == 200, "Token revocation failed"
                    revoked = context.request.get(
                        origin + "/api/v1/me",
                        headers={
                            "Authorization": "Bearer " + refreshed["access_token"]
                        },
                    )
                    assert revoked.status == 401, "Revoked token was accepted"
                    print("PASS: central revocation immediately blocks API access")
                finally:
                    page.goto("https://auth.jackharrhy.dev/account")
                    page.get_by_role("button", name="Sign out", exact=True).click()
                    context.close()
                    browser.close()

        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default="https://4orm.harrhy.xyz")
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--account", default="jack")
    try:
        run(parser.parse_args())
    except Exception:
        raise SystemExit(
            "FAIL: central CLI acceptance; credentials remain private"
        ) from None
