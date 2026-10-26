"""OIDC client for the central identity provider."""

import base64
import hashlib
import json
import os
import secrets
import time
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from joserfc import jwk, jwt


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def enabled():
    return os.environ.get("CENTRAL_AUTH_ENABLED") == "1"


def configuration():
    issuer = os.environ.get("OIDC_ISSUER", "https://auth.jackharrhy.dev").rstrip("/")
    client_id = os.environ.get("OIDC_CLIENT_ID", "")
    redirect_uri = os.environ.get(
        "OIDC_REDIRECT_URI", "https://4orm.harrhy.xyz/auth/callback"
    )
    if not client_id or urlparse(issuer).scheme != "https":
        raise ValueError("Central auth requires an HTTPS issuer and client ID")
    return issuer, client_id, redirect_uri


def provider_json(url, values=None):
    data = urlencode(values).encode() if values is not None else None
    headers = {"Content-Type": "application/x-www-form-urlencoded"} if data else {}
    with build_opener(_NoRedirect).open(
        Request(url, data=data, headers=headers), timeout=12
    ) as response:
        raw = response.read(1_048_577)
    if len(raw) > 1_048_576:
        raise ValueError("Identity provider response is too large")
    return json.loads(raw)


def discovery(issuer):
    document = provider_json(issuer + "/.well-known/openid-configuration")
    if document.get("issuer") != issuer:
        raise ValueError("Identity issuer mismatch")
    origin = urlparse(issuer)
    for name in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        endpoint = urlparse(document.get(name, ""))
        if (endpoint.scheme, endpoint.netloc) != (origin.scheme, origin.netloc):
            raise ValueError("Identity endpoint is outside the configured issuer")
    return document


def begin(session, next_kind=""):
    issuer, client_id, redirect_uri = configuration()
    document = discovery(issuer)
    verifier = secrets.token_urlsafe(48)
    state, nonce = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    session["oidc_transaction"] = {
        "state": state,
        "nonce": nonce,
        "verifier": verifier,
        "created": int(time.time()),
        "next": next_kind if next_kind in {"oauth", "register"} else "",
    }
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return (
        document["authorization_endpoint"]
        + "?"
        + urlencode(
            {
                "client_id": client_id,
                "response_type": "code",
                "scope": "openid profile",
                "redirect_uri": redirect_uri,
                "state": state,
                "nonce": nonce,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
    )


def validate_identity(id_token, keys, issuer, client_id, nonce):
    token = jwt.decode(id_token, jwk.KeySet.import_key_set(keys), algorithms=["RS256"])
    claims = token.claims
    if claims.get("iss") != issuer or claims.get("nonce") != nonce:
        raise ValueError("Identity issuer or nonce mismatch")
    if not isinstance(claims.get("sub"), str) or not claims["sub"]:
        raise ValueError("Identity subject is missing")
    jwt.JWTClaimsRegistry(
        iss={"essential": True, "value": issuer},
        aud={"essential": True, "value": client_id},
        exp={"essential": True},
        iat={"essential": True},
    ).validate(claims)
    audience = claims["aud"]
    needs_authorized_party = (
        isinstance(audience, list) and len(audience) > 1
    ) or "azp" in claims
    if needs_authorized_party and claims.get("azp") != client_id:
        raise ValueError("Identity authorized party mismatch")
    return claims


def complete(session, state, code):
    transaction = session.pop("oidc_transaction", None)
    if (
        not transaction
        or not isinstance(state, str)
        or not secrets.compare_digest(transaction["state"], state)
    ):
        raise ValueError("Sign-in state is invalid")
    if int(time.time()) - transaction["created"] > 300:
        raise ValueError("Sign-in request expired")
    if not code or len(code) > 4096:
        raise ValueError("Sign-in code is invalid")
    issuer, client_id, redirect_uri = configuration()
    document = discovery(issuer)
    result = provider_json(
        document["token_endpoint"],
        {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "redirect_uri": redirect_uri,
            "code_verifier": transaction["verifier"],
        },
    )
    claims = validate_identity(
        result["id_token"],
        provider_json(document["jwks_uri"]),
        issuer,
        client_id,
        transaction["nonce"],
    )
    return claims, transaction["next"]
