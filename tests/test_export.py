import io
import zipfile

from sqlalchemy import insert, update

import app.deps as deps
from app.schema import media, pages, profile_cards, users
from app.security import hash_password


def _extract_zip(response):
    """Extract a zip from a response and return a ZipFile."""
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    return zipfile.ZipFile(io.BytesIO(response.content))


def _make_admin(test_engine, user_id):
    with test_engine.begin() as conn:
        conn.execute(update(users).where(users.c.id == user_id).values(is_admin=True))


def _create_second_user(test_engine):
    with test_engine.begin() as conn:
        result = conn.execute(
            insert(users).values(
                username="other",
                password_hash=hash_password("pass"),
                display_name="Other",
            )
        )
        uid = result.inserted_primary_key[0]
        conn.execute(insert(profile_cards).values(user_id=uid, headline="other's page"))
    return {"id": uid, "username": "other", "password": "pass"}


# ---------------------------------------------------------------------------
# 1. test_export_contains_expected_files
# ---------------------------------------------------------------------------
def test_export_contains_expected_files(
    authed_client, test_engine, seed_user, tmp_path
):
    # Create a page
    with test_engine.begin() as conn:
        conn.execute(
            insert(pages).values(
                user_id=seed_user["id"],
                slug="mypage",
                title="My Page",
                content="<p>page</p>",
            )
        )
        # Create a media row
        conn.execute(
            insert(media).values(
                user_id=seed_user["id"],
                storage_path="testuser/pic.png",
                mime_type="image/png",
                size_bytes=4,
            )
        )

    # Create the file on disk
    (tmp_path / "testuser").mkdir()
    (tmp_path / "testuser" / "pic.png").write_bytes(b"fake")

    original = deps.UPLOADS_DIR
    deps.UPLOADS_DIR = tmp_path
    try:
        r = authed_client.get("/u/testuser/export")
        zf = _extract_zip(r)
        names = zf.namelist()
        assert "testuser-export/index.html" in names
        assert "testuser-export/style.css" in names
        assert "testuser-export/pages/mypage.html" in names
        assert "testuser-export/uploads/pic.png" in names
    finally:
        deps.UPLOADS_DIR = original


# ---------------------------------------------------------------------------
# 2. test_export_profile_renders
# ---------------------------------------------------------------------------
def test_export_profile_renders(authed_client, test_engine, seed_user):
    with test_engine.begin() as conn:
        conn.execute(
            update(users)
            .where(users.c.id == seed_user["id"])
            .values(display_name="Cool Person", content="<p>my bio</p>")
        )

    r = authed_client.get("/u/testuser/export")
    zf = _extract_zip(r)
    index = zf.read("testuser-export/index.html").decode()
    assert "Cool Person" in index
    assert "my bio" in index


# ---------------------------------------------------------------------------
# 3. test_export_page_renders
# ---------------------------------------------------------------------------
def test_export_page_renders(authed_client, test_engine, seed_user):
    with test_engine.begin() as conn:
        conn.execute(
            insert(pages).values(
                user_id=seed_user["id"],
                slug="about",
                title="About Me",
                content="<p>page body</p>",
            )
        )

    r = authed_client.get("/u/testuser/export")
    zf = _extract_zip(r)
    page_html = zf.read("testuser-export/pages/about.html").decode()
    assert "About Me" in page_html
    assert "page body" in page_html


# ---------------------------------------------------------------------------
# 4. test_export_markdown_rendered
# ---------------------------------------------------------------------------
def test_export_markdown_rendered(authed_client, test_engine, seed_user):
    with test_engine.begin() as conn:
        conn.execute(
            update(users)
            .where(users.c.id == seed_user["id"])
            .values(content_format="markdown", content="**bold**")
        )

    r = authed_client.get("/u/testuser/export")
    zf = _extract_zip(r)
    index = zf.read("testuser-export/index.html").decode()
    assert "<strong>bold</strong>" in index


# ---------------------------------------------------------------------------
# 5. test_export_custom_css_included
# ---------------------------------------------------------------------------
def test_export_custom_css_included(authed_client, test_engine, seed_user):
    with test_engine.begin() as conn:
        conn.execute(
            update(users)
            .where(users.c.id == seed_user["id"])
            .values(custom_css="body { color: hotpink; }")
        )

    r = authed_client.get("/u/testuser/export")
    zf = _extract_zip(r)
    index = zf.read("testuser-export/index.html").decode()
    assert "<style>" in index
    assert "body { color: hotpink; }" in index


# ---------------------------------------------------------------------------
# 6. test_export_custom_html_included
# ---------------------------------------------------------------------------
def test_export_custom_html_included(authed_client, test_engine, seed_user):
    with test_engine.begin() as conn:
        conn.execute(
            update(users)
            .where(users.c.id == seed_user["id"])
            .values(custom_html='<script>console.log("exported")</script>')
        )

    r = authed_client.get("/u/testuser/export")
    zf = _extract_zip(r)
    index = zf.read("testuser-export/index.html").decode()
    assert 'console.log("exported")' in index


# ---------------------------------------------------------------------------
# 7. test_export_media_paths_rewritten_index
# ---------------------------------------------------------------------------
def test_export_media_paths_rewritten_index(
    authed_client, test_engine, seed_user, tmp_path
):
    with test_engine.begin() as conn:
        conn.execute(
            update(users)
            .where(users.c.id == seed_user["id"])
            .values(content='<img src="/uploads/testuser/pic.png">')
        )
        conn.execute(
            insert(media).values(
                user_id=seed_user["id"],
                storage_path="testuser/pic.png",
                mime_type="image/png",
                size_bytes=4,
            )
        )

    (tmp_path / "testuser").mkdir()
    (tmp_path / "testuser" / "pic.png").write_bytes(b"fake")

    original = deps.UPLOADS_DIR
    deps.UPLOADS_DIR = tmp_path
    try:
        r = authed_client.get("/u/testuser/export")
        zf = _extract_zip(r)
        index = zf.read("testuser-export/index.html").decode()
        # Should be rewritten to relative path
        assert "uploads/pic.png" in index
        # Should NOT contain the absolute server path
        assert "/uploads/testuser/" not in index
    finally:
        deps.UPLOADS_DIR = original


# ---------------------------------------------------------------------------
# 8. test_export_media_paths_rewritten_pages
# ---------------------------------------------------------------------------
def test_export_media_paths_rewritten_pages(
    authed_client, test_engine, seed_user, tmp_path
):
    with test_engine.begin() as conn:
        conn.execute(
            insert(pages).values(
                user_id=seed_user["id"],
                slug="gallery",
                title="Gallery",
                content='<img src="/uploads/testuser/pic.png">',
            )
        )
        conn.execute(
            insert(media).values(
                user_id=seed_user["id"],
                storage_path="testuser/pic.png",
                mime_type="image/png",
                size_bytes=4,
            )
        )

    (tmp_path / "testuser").mkdir()
    (tmp_path / "testuser" / "pic.png").write_bytes(b"fake")

    original = deps.UPLOADS_DIR
    deps.UPLOADS_DIR = tmp_path
    try:
        r = authed_client.get("/u/testuser/export")
        zf = _extract_zip(r)
        page_html = zf.read("testuser-export/pages/gallery.html").decode()
        # Pages are nested one level deeper, so paths should go up
        assert "../uploads/pic.png" in page_html
        assert "/uploads/testuser/" not in page_html
    finally:
        deps.UPLOADS_DIR = original


# ---------------------------------------------------------------------------
# 9. test_export_raw_layout
# ---------------------------------------------------------------------------
def test_export_raw_layout(authed_client, test_engine, seed_user):
    with test_engine.begin() as conn:
        conn.execute(
            update(users)
            .where(users.c.id == seed_user["id"])
            .values(layout="raw", content="<html><body>raw</body></html>")
        )

    r = authed_client.get("/u/testuser/export")
    zf = _extract_zip(r)
    index = zf.read("testuser-export/index.html").decode()
    assert "raw" in index
    assert "topbar" not in index


# ---------------------------------------------------------------------------
# 10. test_export_empty_user
# ---------------------------------------------------------------------------
def test_export_empty_user(authed_client, seed_user):
    r = authed_client.get("/u/testuser/export")
    zf = _extract_zip(r)
    names = zf.namelist()
    assert "testuser-export/index.html" in names
    assert "testuser-export/style.css" in names


# ---------------------------------------------------------------------------
# 11. test_export_auth_self
# ---------------------------------------------------------------------------
def test_export_auth_self(authed_client, seed_user):
    r = authed_client.get("/u/testuser/export")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# 12. test_export_auth_admin
# ---------------------------------------------------------------------------
def test_export_auth_admin(authed_client, test_engine, seed_user):
    other = _create_second_user(test_engine)
    _make_admin(test_engine, seed_user["id"])

    r = authed_client.get(f"/u/{other['username']}/export")
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# 13. test_export_auth_non_admin_other
# ---------------------------------------------------------------------------
def test_export_auth_non_admin_other(authed_client, test_engine, seed_user):
    other = _create_second_user(test_engine)

    r = authed_client.get(f"/u/{other['username']}/export")
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# 14. test_export_page_list_links
# ---------------------------------------------------------------------------
def test_export_page_list_links(authed_client, test_engine, seed_user):
    with test_engine.begin() as conn:
        conn.execute(
            insert(pages).values(
                user_id=seed_user["id"],
                slug="page1",
                title="Page One",
                content="<p>one</p>",
            )
        )
        conn.execute(
            insert(pages).values(
                user_id=seed_user["id"],
                slug="page2",
                title="Page Two",
                content="<p>two</p>",
            )
        )

    r = authed_client.get("/u/testuser/export")
    zf = _extract_zip(r)
    index = zf.read("testuser-export/index.html").decode()
    assert "pages/page1.html" in index
    assert "pages/page2.html" in index
