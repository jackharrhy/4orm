"""Loopback-only signed OIDC provider for disposable browser verification."""

import base64
import hashlib
import html
import json
import secrets
import ssl
import subprocess
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

from joserfc import jwk, jwt

CLIENT_ID = "browser-verification"
SUBJECT = "browser-verification-member"


@contextmanager
def provider(runtime, redirect_uri):
    certificate, private_key = runtime / "issuer.pem", runtime / "issuer-key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(private_key),
            "-out",
            str(certificate),
            "-days",
            "1",
            "-subj",
            "/CN=127.0.0.1",
            "-addext",
            "subjectAltName=IP:127.0.0.1",
        ],
        check=True,
        capture_output=True,
    )
    private_key.chmod(0o600)
    key = jwk.RSAKey.generate_key(2048)
    transactions, codes = {}, {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def send(self, status, value, content_type="application/json"):
            body = (
                json.dumps(value).encode()
                if content_type == "application/json"
                else value.encode()
            )
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == "/.well-known/openid-configuration":
                self.send(
                    200,
                    {
                        "issuer": issuer,
                        "authorization_endpoint": issuer + "/authorize",
                        "token_endpoint": issuer + "/token",
                        "jwks_uri": issuer + "/jwks",
                    },
                )
            elif url.path == "/jwks":
                self.send(200, {"keys": [key.as_dict(private=False)]})
            elif url.path == "/authorize":
                params = parse_qs(url.query)
                if any(len(values) != 1 for values in params.values()):
                    self.send(400, {"error": "duplicate_parameter"})
                    return
                values = {name: items[0] for name, items in params.items()}
                if (
                    values.get("client_id") != CLIENT_ID
                    or values.get("redirect_uri") != redirect_uri
                    or values.get("response_type") != "code"
                    or values.get("code_challenge_method") != "S256"
                    or len(values.get("code_challenge", "")) != 43
                    or not values.get("state")
                    or not values.get("nonce")
                ):
                    self.send(400, {"error": "invalid_request"})
                    return
                transaction = secrets.token_urlsafe(24)
                transactions[transaction] = values
                self.send(
                    200,
                    "<!doctype html><title>Test identity provider</title>"
                    "<h1>Test identity provider</h1>"
                    '<form method="post" action="/approve">'
                    '<input type="hidden" name="transaction" '
                    f'value="{html.escape(transaction)}">'
                    '<label>username<input name="username" '
                    'autocomplete="username"></label>'
                    '<label>password<input name="password" type="password" '
                    'autocomplete="current-password"></label>'
                    "<button>Sign in</button></form>",
                    "text/html; charset=utf-8",
                )
            else:
                self.send(404, {"error": "not_found"})

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 8192:
                self.send(400, {"error": "invalid_body"})
                return
            params = parse_qs(self.rfile.read(length).decode())
            if any(len(values) != 1 for values in params.values()):
                self.send(400, {"error": "duplicate_parameter"})
                return
            values = {name: items[0] for name, items in params.items()}
            if self.path == "/approve":
                transaction = transactions.pop(values.get("transaction"), None)
                if (
                    not transaction
                    or values.get("username") != "visualcheck"
                    or values.get("password") != "visualcheck-pass"
                ):
                    self.send(401, {"error": "invalid_credentials"})
                    return
                code = secrets.token_urlsafe(24)
                codes[code] = transaction
                self.send_response(303)
                self.send_header(
                    "Location",
                    redirect_uri
                    + "?"
                    + urlencode({"state": transaction["state"], "code": code}),
                )
                self.end_headers()
            elif self.path == "/token":
                transaction = codes.pop(values.get("code"), None)
                challenge = (
                    base64.urlsafe_b64encode(
                        hashlib.sha256(
                            values.get("code_verifier", "").encode()
                        ).digest()
                    )
                    .decode()
                    .rstrip("=")
                )
                if (
                    not transaction
                    or values.get("grant_type") != "authorization_code"
                    or values.get("client_id") != CLIENT_ID
                    or values.get("redirect_uri") != redirect_uri
                    or challenge != transaction["code_challenge"]
                ):
                    self.send(400, {"error": "invalid_grant"})
                    return
                now = int(time.time())
                signed = jwt.encode(
                    {"alg": "RS256"},
                    {
                        "iss": issuer,
                        "sub": SUBJECT,
                        "aud": CLIENT_ID,
                        "nonce": transaction["nonce"],
                        "iat": now,
                        "exp": now + 300,
                    },
                    key,
                )
                self.send(200, {"id_token": signed, "token_type": "Bearer"})
            else:
                self.send(404, {"error": "not_found"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    issuer = f"https://127.0.0.1:{server.server_port}"
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certificate, private_key)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield issuer, certificate
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
