"""Tests for JSON API content negotiation.

Every non-admin GET and POST route should return JSON when the request
includes ``Accept: application/json``.  The CSRFTestClient does NOT add
this header automatically, so each call must include it explicitly.
"""

_JSON = {"Accept": "application/json"}


def _json_headers():
    """Fresh copy so _inject_csrf never mutates the shared dict."""
    return dict(_JSON)


def get_json(client, url):
    r = client.get(url, headers=_json_headers())
    assert r.status_code == 200, f"GET {url} returned {r.status_code}: {r.text[:200]}"
    return r.json()


def post_json(client, url, data=None):
    r = client.post(url, data=data or {}, headers=_json_headers())
    return r


# ---------------------------------------------------------------------------
# Profile & Pages
# ---------------------------------------------------------------------------


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
    # Create via JSON-accepting POST
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

    # View the page
    data = get_json(authed_client, f"/u/{seed_user['username']}/page/api-test")
    assert data["title"] == "API Test Page"
    assert data["rendered_content"] == "hello from api"
    assert data["content_format"] == "html"


# ---------------------------------------------------------------------------
# Forum
# ---------------------------------------------------------------------------


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
        {
            "title": "API Thread",
            "content": "thread body",
            "content_format": "bbcode",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["id"] is not None


def test_api_forum_reply(authed_client, seed_user, test_engine):
    from app.queries.forum import create_thread

    with test_engine.begin() as conn:
        tid = create_thread(conn, seed_user["id"], "Reply Thread", "body")
    r = post_json(
        authed_client,
        f"/forum/{tid}/reply",
        {
            "content": "a reply",
            "content_format": "bbcode",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------


def test_api_login(client, seed_user):
    r = post_json(
        client,
        "/login",
        {
            "username": "testuser",
            "password": "testpass",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "testuser"
    assert "redirect" in body


def test_api_login_fail(client, seed_user):
    r = post_json(
        client,
        "/login",
        {
            "username": "testuser",
            "password": "wrong",
        },
    )
    assert r.status_code == 400
    body = r.json()
    assert body["ok"] is False


def test_api_logout(authed_client):
    r = post_json(authed_client, "/logout")
    assert r.status_code == 200
    assert r.json()["ok"] is True


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Lineage
# ---------------------------------------------------------------------------


def test_api_lineage(client, seed_user):
    data = get_json(client, "/lineage")
    assert "tree" in data
    assert isinstance(data["tree"], list)


# ---------------------------------------------------------------------------
# Media
# ---------------------------------------------------------------------------


def test_api_media_list(authed_client):
    data = get_json(authed_client, "/settings/media")
    assert "items" in data
    assert "storage_used" in data
    assert "storage_limit" in data


# ---------------------------------------------------------------------------
# HTML still works
# ---------------------------------------------------------------------------


def test_html_still_works(client, seed_user):
    """Requests without Accept: application/json still get HTML."""
    r = client.get(f"/u/{seed_user['username']}")
    assert r.status_code == 200
    assert "<html" in r.text or "<!doctype" in r.text.lower() or "panel" in r.text
