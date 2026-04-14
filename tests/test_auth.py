from sqlalchemy import insert, select, update

from app.queries.users import create_invite
from app.schema import password_reset_tokens, users
from app.security import verify_password
from tests.conftest import promote_to_admin


def test_login_page_renders(client):
    r = client.get("/login")
    assert r.status_code == 200
    assert "login" in r.text.lower()


def test_register_page_renders(client):
    r = client.get("/register")
    assert r.status_code == 200
    assert "register" in r.text.lower()


def test_login_invalid_credentials(client, seed_user):
    r = client.post(
        "/login",
        data={"username": "testuser", "password": "wrong"},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "invalid credentials" in r.text


def test_login_success_redirects(client, seed_user):
    r = client.post(
        "/login",
        data={"username": "testuser", "password": "testpass"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "/u/testuser" in r.headers["location"]


def test_register_with_invite(client, test_engine, seed_user):
    with test_engine.begin() as conn:
        code = create_invite(conn, seed_user["id"], max_uses=1)

    r = client.post(
        "/register",
        data={"username": "newuser", "password": "newpass", "invite_code": code},
        follow_redirects=False,
    )
    assert r.status_code == 303

    # New user can log in
    r2 = client.post(
        "/login",
        data={"username": "newuser", "password": "newpass"},
        follow_redirects=False,
    )
    assert r2.status_code == 303


def test_register_invalid_invite(client, seed_user):
    r = client.post(
        "/register",
        data={"username": "newuser", "password": "newpass", "invite_code": "fake"},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "invalid" in r.text


def test_register_exhausted_invite(client, test_engine, seed_user):
    with test_engine.begin() as conn:
        code = create_invite(conn, seed_user["id"], max_uses=1)

    # Use the invite once
    client.post(
        "/register",
        data={"username": "first", "password": "pass", "invite_code": code},
    )

    # Second attempt should fail
    r = client.post(
        "/register",
        data={"username": "second", "password": "pass", "invite_code": code},
        follow_redirects=False,
    )
    assert r.status_code == 400


def test_logout(authed_client):
    r = authed_client.post("/logout", follow_redirects=False)
    assert r.status_code == 303

    # Settings should redirect to login now
    r2 = authed_client.get("/settings", follow_redirects=False)
    assert r2.status_code == 303
    assert "/login" in r2.headers["location"]


def test_forgot_password_rejects_invalid_token(client):
    r = client.get("/login/forgot-password?token=invalid")
    assert r.status_code == 400
    assert "invalid or expired reset link" in r.text


def test_forgot_password_resets_password(client, authed_client, test_engine, seed_user):
    with test_engine.begin() as conn:
        conn.execute(
            update(users).where(users.c.id == seed_user["id"]).values(is_admin=True)
        )

    r = authed_client.post(
        f"/admin/users/{seed_user['id']}/password-reset-link",
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert "data-url=" in r.text
    token = r.text.split("token=", 1)[1].split('"', 1)[0]

    r2 = client.post(
        "/login/forgot-password",
        data={
            "token": token,
            "password": "newpass123",
            "password_confirm": "newpass123",
        },
        follow_redirects=False,
    )
    assert r2.status_code == 303
    assert "/login?success=" in r2.headers["location"]

    with test_engine.begin() as conn:
        user = (
            conn.execute(select(users).where(users.c.id == seed_user["id"]))
            .mappings()
            .first()
        )
        assert verify_password("newpass123", user["password_hash"])
        row = (
            conn.execute(
                select(password_reset_tokens).where(
                    password_reset_tokens.c.user_id == seed_user["id"]
                )
            )
            .mappings()
            .first()
        )
        assert row["used_at"] is not None


def test_forgot_password_requires_matching_confirmation(
    client, authed_client, test_engine, seed_user
):
    with test_engine.begin() as conn:
        conn.execute(
            update(users).where(users.c.id == seed_user["id"]).values(is_admin=True)
        )

    r = authed_client.post(
        f"/admin/users/{seed_user['id']}/password-reset-link",
        headers={"HX-Request": "true"},
    )
    token = r.text.split("token=", 1)[1].split('"', 1)[0]

    r2 = client.post(
        "/login/forgot-password",
        data={"token": token, "password": "a", "password_confirm": "b"},
        follow_redirects=False,
    )
    assert r2.status_code == 400
    assert "passwords do not match" in r2.text


def test_forgot_password_rejects_expired_token(client, test_engine, seed_user):
    import hashlib
    from datetime import UTC, datetime, timedelta

    raw = "expired-token"
    with test_engine.begin() as conn:
        conn.execute(
            insert(password_reset_tokens).values(
                user_id=seed_user["id"],
                token_hash=hashlib.sha256(raw.encode("utf-8")).hexdigest(),
                expires_at=datetime.now(UTC) - timedelta(minutes=1),
                created_by_user_id=seed_user["id"],
            )
        )

    r = client.post(
        "/login/forgot-password",
        data={"token": raw, "password": "newpass", "password_confirm": "newpass"},
        follow_redirects=False,
    )
    assert r.status_code == 400
    assert "invalid or expired reset link" in r.text


def test_full_password_reset_flow(client, test_engine, seed_user):
    """End-to-end: register, login, get reset link, reset, login with new pw."""
    from app.queries.users import create_invite

    # 1. Create an invite and register a new user
    with test_engine.begin() as conn:
        code = create_invite(conn, seed_user["id"], max_uses=1)

    client.post(
        "/register",
        data={
            "username": "resetuser",
            "password": "original123",
            "invite_code": code,
        },
    )

    # 2. Login works with original password
    r = client.post(
        "/login",
        data={"username": "resetuser", "password": "original123"},
        follow_redirects=False,
    )
    assert r.status_code == 303, "login with original password should work"

    # 3. Login fails with wrong password
    r = client.post(
        "/login",
        data={"username": "resetuser", "password": "wrongpassword"},
        follow_redirects=False,
    )
    assert r.status_code == 400, "login with wrong password should fail"

    # 4. Admin creates a password reset link
    with test_engine.begin() as conn:
        promote_to_admin(conn, seed_user["id"])
        target = conn.execute(
            select(users.c.id).where(users.c.username == "resetuser")
        ).scalar()

    # Log in as admin
    client.post(
        "/login",
        data={"username": seed_user["username"], "password": seed_user["password"]},
    )

    r = client.post(
        f"/admin/users/{target}/password-reset-link",
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200, f"expected 200 got {r.status_code}"
    assert "data-url=" in r.text
    token = r.text.split("token=", 1)[1].split('"', 1)[0]

    # 5. Use the reset link to set a new password
    r = client.post(
        "/login/forgot-password",
        data={
            "token": token,
            "password": "newpassword456",
            "password_confirm": "newpassword456",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303, "password reset should redirect to login"

    # 6. Login fails with old password
    r = client.post(
        "/login",
        data={"username": "resetuser", "password": "original123"},
        follow_redirects=False,
    )
    assert r.status_code == 400, "old password should no longer work"

    # 7. Login succeeds with new password
    r = client.post(
        "/login",
        data={"username": "resetuser", "password": "newpassword456"},
        follow_redirects=False,
    )
    assert r.status_code == 303, "new password should work after reset"
