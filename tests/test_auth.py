from app.queries.users import create_invite


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
