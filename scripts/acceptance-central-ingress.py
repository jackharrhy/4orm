"""Check public-client PKCE rejection at the actual central authorization ingress."""

import argparse
import json
import secrets
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

ISSUER = "https://auth.jackharrhy.dev"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def check_clients(clients):
    if not isinstance(clients, list) or not clients:
        raise ValueError("At least one protected public client is required")
    if any(
        not isinstance(client, dict)
        or not all(
            isinstance(client.get(key), str) and client[key]
            for key in ("label", "client_id", "redirect_uri")
        )
        for client in clients
    ) or len({client["client_id"] for client in clients}) != len(clients):
        raise ValueError("Client coverage must contain distinct complete registrations")
    opener = build_opener(NoRedirect)
    results = []
    for client in clients:
        base = [
            ("client_id", client["client_id"]),
            ("redirect_uri", client["redirect_uri"]),
            ("response_type", "code"),
            ("scope", "openid profile"),
            ("state", secrets.token_urlsafe(24)),
            ("nonce", secrets.token_urlsafe(24)),
        ]
        challenge = [("code_challenge", "a" * 43), ("code_challenge_method", "S256")]
        cases = [
            ("missing challenge", base),
            (
                "plain challenge",
                [
                    *base,
                    ("code_challenge", "a" * 43),
                    ("code_challenge_method", "plain"),
                ],
            ),
            (
                "short challenge",
                [*base, ("code_challenge", "short"), ("code_challenge_method", "S256")],
            ),
            ("duplicate challenge", base + challenge + [("code_challenge", "")]),
            ("duplicate client", base + challenge + [("client_id", "unrelated")]),
            ("request URI", base + challenge + [("request_uri", "urn:opaque:request")]),
        ]
        attempts = [
            (name, "/oauth/v2/authorize?" + urlencode(values), None)
            for name, values in cases
        ]
        attempts.extend(
            ("encoded path: " + path, path + "?" + urlencode(base), None)
            for path in (
                "/oauth/v2/%61uthorize",
                "/oauth%2Fv2%2Fauthorize",
                "/oauth//v2/authorize",
                "/oauth/v2/authorize/",
            )
        )
        attempts.append(
            ("POST missing challenge", "/oauth/v2/authorize", urlencode(base))
        )
        attempts.append(
            (
                "query/form duplicate challenge",
                "/oauth/v2/authorize?" + urlencode(base + challenge),
                urlencode({"code_challenge": ""}),
            )
        )
        for name, path, body in attempts:
            headers = (
                {"Content-Type": "application/x-www-form-urlencoded"} if body else {}
            )
            request = Request(
                ISSUER + path,
                data=body.encode() if body else None,
                headers=headers,
            )
            try:
                response = opener.open(request, timeout=20)
            except HTTPError as error:
                response = error
            with response:
                raw = response.read(32768)
                try:
                    value = json.loads(raw)
                except ValueError, UnicodeError:
                    value = None
                passed = response.status == 400 and value == {
                    "allowed": False,
                    "error": "invalid_request",
                }
                if name.startswith("encoded path:"):
                    passed = passed or response.status in {400, 404}
                results.append(
                    {
                        "client": client["label"],
                        "case": name,
                        "status": response.status,
                        "ingressRejected": passed,
                    }
                )
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clients", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    try:
        report = {
            "observedAt": datetime.now(UTC).isoformat(),
            "passed": False,
            "status": "running",
            "checks": [],
        }
        args.report.write_text(json.dumps(report, indent=2))
        results = check_clients(json.loads(args.clients.read_text()))
        passed = all(result["ingressRejected"] for result in results)
        args.report.write_text(
            json.dumps(
                report | {"passed": passed, "status": "complete", "checks": results},
                indent=2,
            )
        )
        print(
            f"{'PASS' if passed else 'FAIL'}: {len(results)} live PKCE ingress checks"
        )
        raise SystemExit(0 if passed else 1)
    except OSError, ValueError, KeyError:
        raise SystemExit("FAIL: central ingress acceptance unavailable") from None
