import io
import zipfile

from sqlalchemy import insert, update

import app.deps as deps
from app.queries.forum import create_reply, create_thread
from app.schema import media, pages, users
from tests.conftest import make_test_user, promote_to_admin


def _extract_zip(response):
    """Extract a zip from a response and return a ZipFile."""
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    return zipfile.ZipFile(io.BytesIO(response.content))


def _make_admin(test_engine, user_id):
    with test_engine.begin() as conn:
        promote_to_admin(conn, user_id)


def _create_second_user(test_engine):
    with test_engine.begin() as conn:
        uid = make_test_user(conn, "other")
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


# ===========================================================================
# Full site export tests (/admin/export)
# ===========================================================================


# ---------------------------------------------------------------------------
# 15. test_full_export_requires_admin
# ---------------------------------------------------------------------------
def test_full_export_requires_admin(authed_client):
    r = authed_client.get("/admin/export")
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# 16. test_full_export_contains_all_users
# ---------------------------------------------------------------------------
def test_full_export_contains_all_users(authed_client, test_engine, seed_user):
    _make_admin(test_engine, seed_user["id"])
    _create_second_user(test_engine)
    r = authed_client.get("/admin/export")
    zf = _extract_zip(r)
    names = zf.namelist()
    assert "4orm-export/users/testuser/index.html" in names
    assert "4orm-export/users/other/index.html" in names
    assert "4orm-export/style.css" in names


# ---------------------------------------------------------------------------
# 17. test_full_export_contains_pages
# ---------------------------------------------------------------------------
def test_full_export_contains_pages(authed_client, test_engine, seed_user):
    _make_admin(test_engine, seed_user["id"])
    with test_engine.begin() as conn:
        conn.execute(
            insert(pages).values(
                user_id=seed_user["id"],
                slug="mypage",
                title="My Page",
                content="page content",
                content_format="html",
            )
        )
    r = authed_client.get("/admin/export")
    zf = _extract_zip(r)
    assert "4orm-export/users/testuser/pages/mypage.html" in zf.namelist()
    page_html = zf.read("4orm-export/users/testuser/pages/mypage.html").decode()
    assert "page content" in page_html
    assert "My Page" in page_html


# ---------------------------------------------------------------------------
# 18. test_full_export_contains_forum
# ---------------------------------------------------------------------------
def test_full_export_contains_forum(authed_client, test_engine, seed_user):
    _make_admin(test_engine, seed_user["id"])
    with test_engine.begin() as conn:
        thread_id = create_thread(conn, seed_user["id"], "Test Thread", "thread body")
        create_reply(conn, thread_id, seed_user["id"], "a reply")
    r = authed_client.get("/admin/export")
    zf = _extract_zip(r)
    names = zf.namelist()
    assert "4orm-export/forum/index.html" in names
    assert f"4orm-export/forum/{thread_id}.html" in names
    # Check thread page content
    thread_html = zf.read(f"4orm-export/forum/{thread_id}.html").decode()
    assert "Test Thread" in thread_html
    assert "thread body" in thread_html
    assert "a reply" in thread_html
    # Check forum index
    forum_idx = zf.read("4orm-export/forum/index.html").decode()
    assert "Test Thread" in forum_idx


# ---------------------------------------------------------------------------
# 19. test_full_export_contains_media
# ---------------------------------------------------------------------------
def test_full_export_contains_media(authed_client, test_engine, seed_user, tmp_path):
    _make_admin(test_engine, seed_user["id"])
    user_dir = tmp_path / "testuser"
    user_dir.mkdir()
    (user_dir / "pic.png").write_bytes(b"fake image data")
    with test_engine.begin() as conn:
        conn.execute(
            insert(media).values(
                user_id=seed_user["id"],
                storage_path="testuser/pic.png",
                mime_type="image/png",
                size_bytes=15,
            )
        )
    original = deps.UPLOADS_DIR
    deps.UPLOADS_DIR = tmp_path
    try:
        r = authed_client.get("/admin/export")
        zf = _extract_zip(r)
        assert "4orm-export/users/testuser/uploads/pic.png" in zf.namelist()
        assert (
            zf.read("4orm-export/users/testuser/uploads/pic.png") == b"fake image data"
        )
    finally:
        deps.UPLOADS_DIR = original


# ---------------------------------------------------------------------------
# 20. test_full_export_empty_site
# ---------------------------------------------------------------------------
def test_full_export_empty_site(authed_client, test_engine, seed_user):
    _make_admin(test_engine, seed_user["id"])
    r = authed_client.get("/admin/export")
    zf = _extract_zip(r)
    names = zf.namelist()
    assert "4orm-export/style.css" in names
    assert "4orm-export/users/testuser/index.html" in names
    # No forum directory since no threads
    assert not any("forum/" in n for n in names)
