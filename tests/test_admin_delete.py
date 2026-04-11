"""Tests for admin user deletion (reparent and prune modes)."""

from sqlalchemy import insert, select

from app.schema import guestbook_entries, media, pages, users
from tests.conftest import login_as, make_admin_user, make_test_user


def _user_exists(conn, user_id):
    return (
        conn.execute(select(users.c.id).where(users.c.id == user_id)).first()
        is not None
    )


# --- Reparent tests ---


def test_reparent_basic(client, test_engine):
    """Deleting a user reparents their children to the deleted user's parent."""
    with test_engine.begin() as conn:
        admin_id = make_admin_user(conn, "admin")
        parent_id = make_test_user(conn, "parent", invited_by=admin_id)
        child_id = make_test_user(conn, "child", invited_by=parent_id)
        grandchild_id = make_test_user(conn, "grandchild", invited_by=child_id)

    login_as(client, "admin")

    r = client.post(
        f"/admin/users/{child_id}/delete",
        data={"mode": "reparent"},
        follow_redirects=False,
    )
    assert r.status_code == 303

    with test_engine.begin() as conn:
        assert not _user_exists(conn, child_id)
        # Grandchild should now point to parent (child's parent)
        gc = conn.execute(
            select(users.c.invited_by_user_id).where(users.c.id == grandchild_id)
        ).scalar()
        assert gc == parent_id


def test_reparent_root_user(client, test_engine):
    """Deleting a user with no parent reparents children to NULL."""
    with test_engine.begin() as conn:
        make_admin_user(conn, "admin")
        target_id = make_test_user(conn, "target")  # no parent
        child_id = make_test_user(conn, "child", invited_by=target_id)

    login_as(client, "admin")
    client.post(f"/admin/users/{target_id}/delete", data={"mode": "reparent"})

    with test_engine.begin() as conn:
        assert not _user_exists(conn, target_id)
        gc = conn.execute(
            select(users.c.invited_by_user_id).where(users.c.id == child_id)
        ).scalar()
        assert gc is None


def test_reparent_cleans_up_pages(client, test_engine):
    """Deleting a user removes their pages."""
    with test_engine.begin() as conn:
        make_admin_user(conn, "admin")
        target_id = make_test_user(conn, "target")
        conn.execute(
            insert(pages).values(
                user_id=target_id, slug="hello", title="Hello", content="hi"
            )
        )

    login_as(client, "admin")
    client.post(f"/admin/users/{target_id}/delete", data={"mode": "reparent"})

    with test_engine.begin() as conn:
        page_count = conn.execute(
            select(pages.c.id).where(pages.c.user_id == target_id)
        ).first()
        assert page_count is None


def test_reparent_cleans_up_media_files(client, test_engine, tmp_path):
    """Deleting a user removes their media files from disk."""
    import app.deps

    # Point UPLOADS_DIR to tmp_path for this test
    original_uploads = app.deps.UPLOADS_DIR
    app.deps.UPLOADS_DIR = tmp_path

    user_dir = tmp_path / "target"
    user_dir.mkdir()
    (user_dir / "test.png").write_bytes(b"fake image")

    with test_engine.begin() as conn:
        make_admin_user(conn, "admin")
        target_id = make_test_user(conn, "target")
        conn.execute(
            insert(media).values(
                user_id=target_id,
                storage_path="target/test.png",
                mime_type="image/png",
                size_bytes=10,
            )
        )

    login_as(client, "admin")
    client.post(f"/admin/users/{target_id}/delete", data={"mode": "reparent"})

    assert not (user_dir / "test.png").exists()

    app.deps.UPLOADS_DIR = original_uploads


def test_reparent_cleans_up_guestbook(client, test_engine):
    """Deleting a user removes their guestbook entries."""
    with test_engine.begin() as conn:
        admin_id = make_admin_user(conn, "admin")
        target_id = make_test_user(conn, "target")
        conn.execute(
            insert(guestbook_entries).values(
                user_id=target_id, author_id=admin_id, message="hello"
            )
        )

    login_as(client, "admin")
    client.post(f"/admin/users/{target_id}/delete", data={"mode": "reparent"})

    with test_engine.begin() as conn:
        entries = conn.execute(
            select(guestbook_entries.c.id).where(
                guestbook_entries.c.user_id == target_id
            )
        ).first()
        assert entries is None


# --- Prune tests ---


def test_prune_deletes_subtree(client, test_engine):
    """Pruning deletes the user and all their invitees recursively."""
    with test_engine.begin() as conn:
        admin_id = make_admin_user(conn, "admin")
        bad_id = make_test_user(conn, "bad", invited_by=admin_id)
        spam1_id = make_test_user(conn, "spam1", invited_by=bad_id)
        spam2_id = make_test_user(conn, "spam2", invited_by=bad_id)
        deep_id = make_test_user(conn, "deep", invited_by=spam1_id)

    login_as(client, "admin")

    r = client.post(
        f"/admin/users/{bad_id}/delete",
        data={"mode": "prune"},
        follow_redirects=False,
    )
    assert r.status_code == 303

    with test_engine.begin() as conn:
        assert not _user_exists(conn, bad_id)
        assert not _user_exists(conn, spam1_id)
        assert not _user_exists(conn, spam2_id)
        assert not _user_exists(conn, deep_id)
        # Admin should still exist
        assert _user_exists(conn, admin_id)


def test_prune_htmx_returns_count(client, test_engine):
    """Prune via htmx returns the count of deleted users."""
    with test_engine.begin() as conn:
        admin_id = make_admin_user(conn, "admin")
        bad_id = make_test_user(conn, "bad", invited_by=admin_id)
        make_test_user(conn, "spam1", invited_by=bad_id)
        make_test_user(conn, "spam2", invited_by=bad_id)

    login_as(client, "admin")

    r = client.post(
        f"/admin/users/{bad_id}/delete",
        data={"mode": "prune"},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert "deleted 3 user(s)" in r.text


def test_prune_cleans_up_media(client, test_engine, tmp_path):
    """Pruning cleans up media files for all users in the subtree."""
    import app.deps

    original_uploads = app.deps.UPLOADS_DIR
    app.deps.UPLOADS_DIR = tmp_path

    for name in ["bad", "spam"]:
        d = tmp_path / name
        d.mkdir()
        (d / "file.png").write_bytes(b"data")

    with test_engine.begin() as conn:
        admin_id = make_admin_user(conn, "admin")
        bad_id = make_test_user(conn, "bad", invited_by=admin_id)
        spam_id = make_test_user(conn, "spam", invited_by=bad_id)
        conn.execute(
            insert(media).values(
                user_id=bad_id,
                storage_path="bad/file.png",
                mime_type="image/png",
                size_bytes=4,
            )
        )
        conn.execute(
            insert(media).values(
                user_id=spam_id,
                storage_path="spam/file.png",
                mime_type="image/png",
                size_bytes=4,
            )
        )

    login_as(client, "admin")
    client.post(f"/admin/users/{bad_id}/delete", data={"mode": "prune"})

    assert not (tmp_path / "bad" / "file.png").exists()
    assert not (tmp_path / "spam" / "file.png").exists()

    app.deps.UPLOADS_DIR = original_uploads


# --- Guard tests ---


def test_cannot_delete_self(client, test_engine):
    """Admin cannot delete themselves."""
    with test_engine.begin() as conn:
        admin_id = make_admin_user(conn, "admin")

    login_as(client, "admin")

    r = client.post(
        f"/admin/users/{admin_id}/delete",
        data={"mode": "reparent"},
    )
    assert r.status_code == 400


def test_admin_rename_user(client, test_engine):
    """Admin can rename a user."""
    with test_engine.begin() as conn:
        admin_id = make_admin_user(conn, "admin")
        target_id = make_test_user(conn, "badname", invited_by=admin_id)

    login_as(client, "admin")

    r = client.post(
        f"/admin/users/{target_id}/rename",
        data={"new_username": "goodname"},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert "goodname" in r.text

    with test_engine.begin() as conn:
        user = conn.execute(
            select(users.c.username).where(users.c.id == target_id)
        ).scalar()
        assert user == "goodname"


def test_admin_rename_display_name_only(client, test_engine):
    """Admin can change just the display name without renaming the user."""
    with test_engine.begin() as conn:
        make_admin_user(conn, "admin")
        target_id = make_test_user(conn, "target")

    login_as(client, "admin")

    r = client.post(
        f"/admin/users/{target_id}/rename",
        data={"new_username": "target", "new_display_name": "Better Name"},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 200
    assert "Better Name" in r.text

    with test_engine.begin() as conn:
        dn = conn.execute(
            select(users.c.display_name).where(users.c.id == target_id)
        ).scalar()
        assert dn == "Better Name"


def test_admin_rename_taken(client, test_engine):
    """Admin cannot rename to an existing username."""
    with test_engine.begin() as conn:
        make_admin_user(conn, "admin")
        make_test_user(conn, "existing")
        target_id = make_test_user(conn, "target")

    login_as(client, "admin")

    r = client.post(
        f"/admin/users/{target_id}/rename",
        data={"new_username": "existing"},
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 400
    assert "taken" in r.text.lower()


def test_admin_rename_invalid(client, test_engine):
    """Admin cannot rename to an invalid username."""
    with test_engine.begin() as conn:
        make_admin_user(conn, "admin")
        target_id = make_test_user(conn, "target")

    login_as(client, "admin")

    r = client.post(
        f"/admin/users/{target_id}/rename",
        data={"new_username": "ab"},  # too short
        headers={"HX-Request": "true"},
    )
    assert r.status_code == 400


def test_non_admin_cannot_delete(client, test_engine):
    """Non-admin users cannot delete anyone."""
    with test_engine.begin() as conn:
        make_test_user(conn, "regular")
        target_id = make_test_user(conn, "target")

    login_as(client, "regular")

    r = client.post(
        f"/admin/users/{target_id}/delete",
        data={"mode": "reparent"},
    )
    assert r.status_code == 403
