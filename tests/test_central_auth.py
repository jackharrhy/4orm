import time

import pytest
from joserfc import jwk, jwt
from joserfc.errors import JoseError
from sqlalchemy import insert

from app import oidc
from app.schema import external_identities


def test_oidc_token_requires_signature_issuer_audience_nonce_and_expiry():
    key = jwk.RSAKey.generate_key(2048)
    keys = {"keys": [key.as_dict(private=False)]}
    now = int(time.time())
    claims = {
        "iss": "https://auth.example",
        "sub": "subject",
        "aud": "client",
        "nonce": "nonce",
        "iat": now,
        "exp": now + 300,
    }

    def token(values, signer=key):
        return jwt.encode({"alg": "RS256"}, values, signer)

    assert (
        oidc.validate_identity(
            token(claims), keys, "https://auth.example", "client", "nonce"
        )["sub"]
        == "subject"
    )
    for changed in [
        {"iss": "https://other.example"},
        {"aud": "other"},
        {"nonce": "other"},
        {"exp": now - 60},
        {"iss": ["https://auth.example"]},
        {"sub": ["subject"]},
        {"aud": ["client", "other"]},
        {"azp": "other"},
    ]:
        with pytest.raises((ValueError, JoseError)):
            oidc.validate_identity(
                token(claims | changed), keys, "https://auth.example", "client", "nonce"
            )
    with pytest.raises((ValueError, JoseError)):
        oidc.validate_identity(
            token(claims, jwk.RSAKey.generate_key(2048)),
            keys,
            "https://auth.example",
            "client",
            "nonce",
        )


def test_oidc_transaction_is_one_use_and_checks_state_and_age(monkeypatch):
    monkeypatch.setattr(
        oidc,
        "configuration",
        lambda: (
            "https://auth.example",
            "client",
            "https://4orm.example/auth/callback",
        ),
    )
    calls = []
    monkeypatch.setattr(oidc, "provider_json", lambda *args: calls.append(args))
    transaction = {
        "state": "correct",
        "created": int(time.time()),
        "nonce": "nonce",
        "verifier": "verifier",
        "next": "",
    }
    session = {"oidc_transaction": transaction}

    with pytest.raises(ValueError, match="state is invalid"):
        oidc.complete(session, "wrong", "code")
    assert "oidc_transaction" not in session
    session = {"oidc_transaction": transaction | {"created": int(time.time()) - 301}}
    with pytest.raises(ValueError, match="expired"):
        oidc.complete(session, "correct", "code")
    assert not calls


def test_oidc_callback_only_links_by_explicit_subject(
    client, seed_user, test_engine, monkeypatch
):
    monkeypatch.setenv("OIDC_CLIENT_ID", "test-client")
    claims = {
        "iss": "https://auth.jackharrhy.dev",
        "sub": "different-subject",
        "preferred_username": seed_user["username"],
        "exp": int(time.time()) + 300,
    }
    monkeypatch.setattr(oidc, "complete", lambda *args: (claims, ""))
    response = client.get(
        "/auth/callback?state=state&code=code", follow_redirects=False
    )
    assert response.status_code == 403
    with test_engine.begin() as conn:
        conn.execute(
            insert(external_identities).values(
                issuer=claims["iss"], subject=claims["sub"], user_id=seed_user["id"]
            )
        )
    response = client.get(
        "/auth/callback?state=state&code=code", follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/u/testuser"
    assert client.get("/settings").status_code == 200


def test_browser_code_flow_uses_pkce_and_preserves_local_ownership(
    client, seed_user, test_engine, monkeypatch
):
    import base64
    import hashlib
    from urllib.parse import parse_qs, urlparse

    monkeypatch.setenv("OIDC_CLIENT_ID", "fourm-client")
    key = jwk.RSAKey.generate_key(2048)
    discovery = {
        "issuer": "https://auth.jackharrhy.dev",
        "authorization_endpoint": "https://auth.jackharrhy.dev/oauth/v2/authorize",
        "token_endpoint": "https://auth.jackharrhy.dev/oauth/v2/token",
        "jwks_uri": "https://auth.jackharrhy.dev/oauth/v2/keys",
    }
    authorization = {}

    def provider(url, values=None):
        if url.endswith("openid-configuration"):
            return discovery
        if url == discovery["jwks_uri"]:
            return {"keys": [key.as_dict(private=False)]}
        assert url == discovery["token_endpoint"]
        challenge = (
            base64.urlsafe_b64encode(
                hashlib.sha256(values["code_verifier"].encode()).digest()
            )
            .rstrip(b"=")
            .decode()
        )
        assert challenge == authorization["code_challenge"][0]
        assert values["redirect_uri"] == "https://4orm.harrhy.xyz/auth/callback"
        now = int(time.time())
        claims = {
            "iss": discovery["issuer"],
            "sub": "central-subject",
            "aud": "fourm-client",
            "nonce": authorization["nonce"][0],
            "iat": now,
            "exp": now + 300,
        }
        return {"id_token": jwt.encode({"alg": "RS256"}, claims, key)}

    monkeypatch.setattr(oidc, "provider_json", provider)
    with test_engine.begin() as conn:
        conn.execute(
            insert(external_identities).values(
                issuer=discovery["issuer"],
                subject="central-subject",
                user_id=seed_user["id"],
            )
        )
    response = client.get("/auth/start", follow_redirects=False)
    authorization.update(parse_qs(urlparse(response.headers["location"]).query))
    response = client.get(
        "/auth/callback",
        params={"state": authorization["state"][0], "code": "code"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/u/testuser"
    assert client.get("/settings").status_code == 200
    assert (
        client.get(
            "/auth/callback",
            params={"state": authorization["state"][0], "code": "code"},
            follow_redirects=False,
        ).status_code
        == 400
    )


def test_admin_recovery_uses_central_identity_management(
    client, seed_user, test_engine, monkeypatch
):
    from sqlalchemy import func, select, update

    from app.schema import password_reset_tokens, users

    monkeypatch.setenv("OIDC_CLIENT_ID", "test-client")
    response = client.get("/login/forgot-password", follow_redirects=False)
    assert response.headers["location"] == "https://auth.jackharrhy.dev/forgot-password"
    with test_engine.begin() as conn:
        conn.execute(
            update(users).where(users.c.id == seed_user["id"]).values(is_admin=True)
        )
        conn.execute(
            insert(external_identities).values(
                issuer="https://auth.jackharrhy.dev",
                subject="admin-subject",
                user_id=seed_user["id"],
            )
        )
    monkeypatch.setattr(
        oidc,
        "complete",
        lambda *args: (
            {
                "iss": "https://auth.jackharrhy.dev",
                "sub": "admin-subject",
                "exp": int(time.time()) + 300,
            },
            "",
        ),
    )
    client.get("/auth/callback?state=state&code=code", follow_redirects=False)
    response = client.post(
        f"/admin/users/{seed_user['id']}/identity", follow_redirects=False
    )
    assert response.status_code == 303
    assert (
        response.headers["location"]
        == "https://auth.jackharrhy.dev/manage/users/admin-subject"
    )
    with test_engine.begin() as conn:
        assert (
            conn.execute(
                select(func.count()).select_from(password_reset_tokens)
            ).scalar_one()
            == 0
        )


@pytest.mark.parametrize(
    "transaction",
    ["invalid", {"state": 1, "created": 1}, {"state": "state", "created": "invalid"}],
)
def test_malformed_signin_transaction_fails_closed_and_is_consumed(transaction):
    session = {"oidc_transaction": transaction}
    with pytest.raises(ValueError):
        oidc.complete(session, "state", "code")
    assert "oidc_transaction" not in session
