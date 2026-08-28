"""Tests for JSON API content negotiation and the stable v1 API."""

import time
from pathlib import Path

from sqlalchemy import insert

from app.schema import oauth2_clients, oauth2_tokens

_JSON = {"Accept": "application/json"}


def _json_headers():
    return dict(_JSON)


def get_json(client, url):
    r = client.get(url, headers=_json_headers())
    assert r.status_code == 200, f"GET {url} returned {r.status_code}: {r.text[:200]}"
    return r.json()


def post_json(client, url, data=None):
    return client.post(url, data=data or {}, headers=_json_headers())


def test_api_homepage(client, seed_user):
    data = get_json(client, "/")
    assert "cards" in data
    assert "recent_forum_posts" in data
    assert isinstance(data["cards"], list)


def test_api_profile(client, seed_user):
    data = get_json(client, f"/u/{seed_user['username']}")
    assert data["username"] == "testuser"
    assert "display_name" in data
    assert "rendered_content" in data
    assert "pages" in data


def test_api_profile_404(client):
    r = client.get("/u/nonexistent", headers=_json_headers())
    assert r.status_code == 404


def test_api_create_page_and_view(authed_client, seed_user):
    r = post_json(
        authed_client,
        "/settings/pages",
        {
            "slug": "api-test",
            "title": "API Test Page",
            "content": "hello from api",
            "content_format": "html",
            "layout": "default",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["slug"] == "api-test"
    data = get_json(authed_client, f"/u/{seed_user['username']}/page/api-test")
    assert data["title"] == "API Test Page"
    assert data["rendered_content"] == "hello from api"
    assert data["content_format"] == "html"


def test_api_forum_list(client, seed_user, test_engine):
    from app.queries.forum import create_thread

    with test_engine.begin() as conn:
        create_thread(conn, seed_user["id"], "Test Thread", "body")
    data = get_json(client, "/forum")
    assert "threads" in data
    assert data["total"] >= 1
    assert data["threads"][0]["title"] == "Test Thread"


def test_api_forum_thread(client, seed_user, test_engine):
    from app.queries.forum import create_thread

    with test_engine.begin() as conn:
        tid = create_thread(conn, seed_user["id"], "Detail Thread", "first post")
    data = get_json(client, f"/forum/{tid}")
    assert data["title"] == "Detail Thread"
    assert len(data["posts"]) >= 1
    assert data["posts"][0]["rendered_content"]


def test_api_forum_create_thread(authed_client, seed_user):
    r = post_json(
        authed_client,
        "/forum/new",
        {"title": "API Thread", "content": "thread body", "content_format": "bbcode"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["id"] is not None


def test_api_forum_reply(authed_client, seed_user, test_engine):
    from app.queries.forum import create_thread

    with test_engine.begin() as conn:
        tid = create_thread(conn, seed_user["id"], "Reply Thread", "body")
    r = post_json(
        authed_client,
        f"/forum/{tid}/reply",
        {"content": "a reply", "content_format": "bbcode"},
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_api_login(client, seed_user):
    r = post_json(client, "/login", {"username": "testuser", "password": "testpass"})
    assert r.status_code == 200
    assert r.json()["username"] == "testuser"
    assert "redirect" in r.json()


def test_api_login_fail(client, seed_user):
    r = post_json(client, "/login", {"username": "testuser", "password": "wrong"})
    assert r.status_code == 400
    assert r.json()["ok"] is False


def test_api_logout(authed_client):
    r = post_json(authed_client, "/logout")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_api_settings(authed_client):
    data = get_json(authed_client, "/settings")
    assert data["username"] == "testuser"
    assert "custom_css" in data
    assert "invites" in data
    assert "pages" in data


def test_api_save_profile(authed_client):
    r = post_json(
        authed_client,
        "/settings/profile",
        {
            "display_name": "API User",
            "content": "api content",
            "content_format": "html",
            "layout": "default",
        },
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_api_save_css(authed_client):
    r = post_json(authed_client, "/settings/css", {"custom_css": "body{color:red}"})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_api_counter(client, seed_user):
    data = get_json(client, f"/u/{seed_user['username']}/counter")
    assert data["username"] == "testuser"
    assert "total_views" in data


def test_api_status(client, seed_user):
    data = get_json(client, f"/u/{seed_user['username']}/status")
    assert data["username"] == "testuser"
    assert "status_emoji" in data


def test_api_player(client, seed_user):
    data = get_json(client, f"/u/{seed_user['username']}/player")
    assert data["username"] == "testuser"
    assert "tracks" in data


def test_api_guestbook(client, seed_user):
    data = get_json(client, f"/u/{seed_user['username']}/guestbook")
    assert data["owner_username"] == "testuser"
    assert "entries" in data


def test_api_webring(client, seed_user):
    data = get_json(client, f"/u/{seed_user['username']}/webring")
    assert data["username"] == "testuser"


def test_api_lineage(client, seed_user):
    data = get_json(client, "/lineage")
    assert "tree" in data
    assert isinstance(data["tree"], list)


def test_api_media_list(authed_client):
    data = get_json(authed_client, "/settings/media")
    assert "items" in data
    assert "storage_used" in data
    assert "storage_limit" in data


def test_html_still_works(client, seed_user):
    r = client.get(f"/u/{seed_user['username']}")
    assert r.status_code == 200
    assert "<html" in r.text or "<!doctype" in r.text.lower() or "panel" in r.text


def api_token(test_engine, seed_user):
    token = "test-access-token"
    with test_engine.begin() as conn:
        conn.execute(
            insert(oauth2_clients).values(
                client_id="test",
                client_name="Test API client",
                token_endpoint_auth_method="none",
            )
        )
        conn.execute(
            insert(oauth2_tokens).values(
                client_id="test",
                user_id=seed_user["id"],
                access_token=token,
                issued_at=int(time.time()),
                expires_in=3600,
                scope="openid profile",
            )
        )
    return token


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_api_v1_requires_bearer_token(client):
    response = client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.json() == {
        "error": {"code": "unauthorized", "message": "missing or invalid bearer token"}
    }


def test_api_v1_pages_are_idempotent(client, test_engine, seed_user):
    token = api_token(test_engine, seed_user)
    headers = {**auth_headers(token), "Accept": "application/json"}
    payload = {
        "title": "About me",
        "content": "<h1>Hello</h1>",
        "content_format": "html",
    }
    first = client.put("/api/v1/pages/about", json=payload, headers=headers)
    second = client.put(
        "/api/v1/pages/about",
        json={**payload, "content": "updated"},
        headers=headers,
    )
    assert first.status_code == 200
    assert first.json()["slug"] == "about"
    assert second.status_code == 200
    assert second.json()["content"] == "updated"
    listed = client.get("/api/v1/pages", headers=headers)
    assert [page["slug"] for page in listed.json()["pages"]] == ["about"]


def test_api_v1_page_delete(client, test_engine, seed_user):
    token = api_token(test_engine, seed_user)
    headers = auth_headers(token)
    client.put("/api/v1/pages/remove-me", json={"title": "Remove me"}, headers=headers)
    response = client.delete("/api/v1/pages/remove-me", headers=headers)
    missing = client.get("/api/v1/pages/remove-me", headers=headers)
    assert response.status_code == 200
    assert missing.status_code == 404


def test_api_v1_media_upload_sanitizes_filename(client, test_engine, seed_user):
    token = api_token(test_engine, seed_user)
    response = client.post(
        "/api/v1/media",
        files={"file": ("../avatar image.PNG", b"image data", "image/png")},
        headers=auth_headers(token),
    )
    assert response.status_code == 200
    storage_path = response.json()["storage_path"]
    assert storage_path.startswith("testuser/avatar-image")
    assert storage_path.endswith(".png")
    Path("uploads", storage_path).unlink(missing_ok=True)


def test_api_v1_media_list_and_delete(client, test_engine, seed_user):
    token = api_token(test_engine, seed_user)
    headers = auth_headers(token)
    uploaded = client.post(
        "/api/v1/media",
        files={"file": ("notes.txt", b"media content", "text/plain")},
        headers=headers,
    )
    assert uploaded.status_code == 200
    item = uploaded.json()

    listed = client.get("/api/v1/media", headers=headers)
    assert listed.status_code == 200
    assert [entry["id"] for entry in listed.json()["items"]] == [item["id"]]
    assert listed.json()["storage_used"] == len(b"media content")

    deleted = client.delete(f"/api/v1/media/{item['id']}", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["message"] == "media deleted"
    assert not Path("uploads", item["storage_path"]).exists()

    missing = client.delete(f"/api/v1/media/{item['id']}", headers=headers)
    assert missing.status_code == 404
