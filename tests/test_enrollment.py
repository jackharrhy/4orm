import time

import pytest
from sqlalchemy import insert, select, update

from app import enrollment
from app.queries.users import create_invite
from app.schema import auth_enrollments, external_identities, invites


def test_reservations_hold_capacity_and_expire(test_engine, seed_user):
    now = int(time.time())
    with test_engine.begin() as conn:
        code = create_invite(conn, seed_user["id"])
        reserved = enrollment.reserve(conn, code, now=now)
        assert (
            enrollment.reserve(conn, code, previous=reserved["id"], now=now)["id"]
            == reserved["id"]
        )
        with pytest.raises(ValueError):
            enrollment.reserve(conn, code, now=now)
        renewed = enrollment.reserve(conn, code, now=now + enrollment.LIFETIME + 1)
        assert renewed["id"] != reserved["id"]


def test_claim_requires_same_identity_and_redemption_is_idempotent(
    test_engine, seed_user
):
    with test_engine.begin() as conn:
        code = create_invite(conn, seed_user["id"])
        row = enrollment.reserve(conn, code)
        enrollment.claim(conn, row["id"], "central-person", "newperson", "New Person")
        with pytest.raises(ValueError):
            enrollment.claim(
                conn, row["id"], "different-person", "newperson", "Other Person"
            )
        user = enrollment.finish(
            conn, row["id"], "https://auth.jackharrhy.dev", "central-person"
        )
        assert user["invited_by_user_id"] == seed_user["id"]
        assert (
            conn.execute(
                select(invites.c.uses_count).where(invites.c.code == code)
            ).scalar_one()
            == 1
        )
        assert (
            enrollment.finish(
                conn, row["id"], "https://auth.jackharrhy.dev", "central-person"
            )["id"]
            == user["id"]
        )
        with pytest.raises(ValueError):
            enrollment.reserve(conn, code)


def test_existing_link_preserves_profile_and_does_not_consume_invite(
    test_engine, seed_user
):
    with test_engine.begin() as conn:
        conn.execute(
            insert(external_identities).values(
                issuer="https://auth.jackharrhy.dev",
                subject="central-person",
                user_id=seed_user["id"],
            )
        )
        code = create_invite(conn, seed_user["id"])
        row = enrollment.reserve(conn, code)
        enrollment.claim(
            conn, row["id"], "central-person", "changedname", "Changed Name"
        )
        user = enrollment.finish(
            conn, row["id"], "https://auth.jackharrhy.dev", "central-person"
        )
        assert user["id"] == seed_user["id"]
        assert user["username"] == seed_user["username"]
        assert (
            conn.execute(
                select(invites.c.uses_count).where(invites.c.code == code)
            ).scalar_one()
            == 0
        )


def test_revocation_and_expiry_prevent_claim_and_finish(test_engine, seed_user):
    with test_engine.begin() as conn:
        code = create_invite(conn, seed_user["id"])
        row = enrollment.reserve(conn, code)
        conn.execute(
            update(invites).where(invites.c.code == code).values(disabled=True)
        )
        with pytest.raises(ValueError):
            enrollment.claim(conn, row["id"], "person", "person", "Person")
        conn.execute(
            update(invites).where(invites.c.code == code).values(disabled=False)
        )
        conn.execute(
            update(auth_enrollments)
            .where(auth_enrollments.c.id == row["id"])
            .values(expires_at=1)
        )
        with pytest.raises(ValueError):
            enrollment.finish(conn, row["id"], "https://auth.jackharrhy.dev", "person")


def test_machine_endpoints_require_scoped_key(
    client, test_engine, seed_user, tmp_path, monkeypatch
):
    import json

    key = tmp_path / "integration.json"
    key.write_text(json.dumps({"token": "secret" * 10}))
    monkeypatch.setenv("CENTRAL_AUTH_ENROLLMENT_KEY_FILE", str(key))
    with test_engine.begin() as conn:
        code = create_invite(conn, seed_user["id"])
        row = enrollment.reserve(conn, code)
    path = "/internal/auth/enrollments/" + row["id"]
    assert client.get(path).status_code == 401
    headers = {"Authorization": "Bearer " + "secret" * 10}
    assert client.get(path, headers=headers).json()["requestId"] == row["id"]
    assert (
        client.post(
            path + "/claim",
            headers=headers,
            json={
                "subject": "person",
                "username": "person",
                "displayName": "Person",
                "role": "owner",
            },
        ).status_code
        == 422
    )
    assert (
        client.post(
            path + "/claim",
            headers=headers,
            json={"subject": "person", "username": "person", "displayName": "Person"},
        ).json()["subject"]
        == "person"
    )


def test_member_invite_routes_signup_through_central_and_keeps_local_ownership(
    client, test_engine, seed_user, tmp_path, monkeypatch
):
    import base64
    import json
    from urllib.parse import parse_qs, urlparse

    from app import oidc

    key = tmp_path / "integration.json"
    key.write_text(json.dumps({"token": "secret" * 10}))
    monkeypatch.setenv("CENTRAL_AUTH_ENROLLMENT_KEY_FILE", str(key))
    monkeypatch.setenv("CENTRAL_AUTH_ENABLED", "1")
    monkeypatch.setenv("OIDC_CLIENT_ID", "fourm-client")
    with test_engine.begin() as conn:
        code = create_invite(conn, seed_user["id"])
    page = client.get("/register", params={"invite": code})
    assert 'action="/auth/register"' in page.text
    assert 'type="password"' not in page.text
    blocked = client.post(
        "/register",
        data={"username": "newperson", "password": "ignored", "invite_code": code},
    )
    assert blocked.status_code == 409
    response = client.post(
        "/auth/register", data={"invite_code": code}, follow_redirects=False
    )
    location = urlparse(response.headers["location"])
    assert location.netloc == "auth.jackharrhy.dev"
    assert location.path == "/enroll"
    encoded = parse_qs(location.query)["ticket"][0].split(".")[0]
    ticket = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    assert ticket["application"] == "fourm"
    with test_engine.begin() as conn:
        enrollment.claim(
            conn, ticket["requestId"], "new-subject", "newperson", "New Person"
        )
    claims = {
        "iss": "https://auth.jackharrhy.dev",
        "sub": "new-subject",
        "exp": int(time.time()) + 300,
    }
    monkeypatch.setattr(oidc, "complete", lambda *args: (claims, "register"))
    response = client.get(
        "/auth/callback?state=state&code=code", follow_redirects=False
    )
    assert response.headers["location"] == "/trust-agreement"
    assert client.get("/settings").status_code == 200
    with test_engine.begin() as conn:
        link = (
            conn.execute(
                select(external_identities).where(
                    external_identities.c.subject == "new-subject"
                )
            )
            .mappings()
            .one()
        )
        assert link["user_id"] != seed_user["id"]
        assert (
            conn.execute(
                select(invites.c.uses_count).where(invites.c.code == code)
            ).scalar_one()
            == 1
        )


def test_callback_cannot_spend_reservation_for_a_different_subject(
    client, test_engine, seed_user, tmp_path, monkeypatch
):
    import json

    from app import oidc

    key = tmp_path / "integration.json"
    key.write_text(json.dumps({"token": "secret" * 10}))
    monkeypatch.setenv("CENTRAL_AUTH_ENROLLMENT_KEY_FILE", str(key))
    monkeypatch.setenv("CENTRAL_AUTH_ENABLED", "1")
    monkeypatch.setenv("OIDC_CLIENT_ID", "fourm-client")
    with test_engine.begin() as conn:
        code = create_invite(conn, seed_user["id"])
    client.post("/auth/register", data={"invite_code": code}, follow_redirects=False)
    with test_engine.begin() as conn:
        row = conn.execute(select(auth_enrollments)).mappings().one()
        enrollment.claim(conn, row["id"], "expected", "newperson", "New Person")
    claims = {
        "iss": "https://auth.jackharrhy.dev",
        "sub": "unexpected",
        "exp": int(time.time()) + 300,
    }
    monkeypatch.setattr(oidc, "complete", lambda *args: (claims, "register"))
    response = client.get(
        "/auth/callback?state=state&code=code", follow_redirects=False
    )
    assert response.status_code == 403
    with test_engine.begin() as conn:
        assert (
            conn.execute(
                select(invites.c.uses_count).where(invites.c.code == code)
            ).scalar_one()
            == 0
        )
        assert conn.execute(select(auth_enrollments.c.consumed_at)).scalar_one() is None
