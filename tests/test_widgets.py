from sqlalchemy import insert, select, update

from app.schema import media, playlist_items, profile_cards, users
from app.security import hash_password


def _join_webring(test_engine, user_id):
    with test_engine.begin() as conn:
        conn.execute(update(users).where(users.c.id == user_id).values(in_webring=True))


def _create_user(test_engine, username, in_webring=False):
    with test_engine.begin() as conn:
        result = conn.execute(
            insert(users).values(
                username=username,
                password_hash=hash_password("pass"),
                display_name=username,
                in_webring=in_webring,
            )
        )
        uid = result.inserted_primary_key[0]
        conn.execute(
            insert(profile_cards).values(user_id=uid, headline=f"{username}'s page")
        )
    return uid


def _create_audio_media(test_engine, user_id, filename="song.mp3"):
    with test_engine.begin() as conn:
        result = conn.execute(
            insert(media).values(
                user_id=user_id,
                storage_path=f"testuser/{filename}",
                mime_type="audio/mpeg",
                size_bytes=1000,
            )
        )
    return result.inserted_primary_key[0]


def test_webring_widget_renders(client, seed_user, test_engine):
    _join_webring(test_engine, seed_user["id"])
    resp = client.get("/u/testuser/webring")
    assert resp.status_code == 200
    assert "4orm webring" in resp.text


def test_webring_prev_next(client, seed_user, test_engine):
    _create_user(test_engine, "alice", in_webring=True)
    _create_user(test_engine, "bob", in_webring=True)
    _create_user(test_engine, "charlie", in_webring=True)

    resp = client.get("/u/bob/webring")
    assert resp.status_code == 200
    assert "alice" in resp.text
    assert "charlie" in resp.text


def test_webring_random_redirects(client, seed_user, test_engine):
    _join_webring(test_engine, seed_user["id"])
    resp = client.get("/webring/random", follow_redirects=False)
    assert resp.status_code == 302


def test_webring_random_404_when_empty(client, seed_user, test_engine):
    # seed_user exists but is NOT in webring
    resp = client.get("/webring/random")
    assert resp.status_code == 404


def test_webring_non_member(client, seed_user, test_engine):
    # testuser is NOT in webring, widget should render but no prev/next links
    resp = client.get("/u/testuser/webring")
    assert resp.status_code == 200
    # The prev/next links use target="_parent" with user profile URLs
    # A non-member should have no neighbor links
    assert "← " not in resp.text


def test_status_widget_renders(client, seed_user, test_engine):
    with test_engine.begin() as conn:
        conn.execute(
            update(users)
            .where(users.c.id == seed_user["id"])
            .values(
                status_emoji="🎉",
                status_text="having fun",
            )
        )
    resp = client.get("/u/testuser/status")
    assert resp.status_code == 200
    assert "🎉" in resp.text
    assert "having fun" in resp.text


def test_status_widget_empty(client, seed_user, test_engine):
    resp = client.get("/u/testuser/status")
    assert resp.status_code == 200


def test_status_404(client, seed_user):
    resp = client.get("/u/nonexistent/status")
    assert resp.status_code == 404


def test_save_status(authed_client, seed_user, test_engine):
    resp = authed_client.post(
        "/settings/status",
        data={"status_emoji": "😎", "status_text": "coding away"},
    )
    assert resp.status_code == 200 or resp.status_code == 303

    with test_engine.begin() as conn:
        row = (
            conn.execute(
                select(users.c.status_emoji, users.c.status_text).where(
                    users.c.id == seed_user["id"]
                )
            )
            .mappings()
            .one()
        )
    assert row["status_emoji"] == "😎"
    assert row["status_text"] == "coding away"


def test_player_widget_renders(client, seed_user, test_engine):
    mid = _create_audio_media(test_engine, seed_user["id"], "cool_song.mp3")
    with test_engine.begin() as conn:
        conn.execute(
            insert(playlist_items).values(
                user_id=seed_user["id"],
                media_id=mid,
                position=0,
                title="Cool Song",
            )
        )

    resp = client.get("/u/testuser/player")
    assert resp.status_code == 200
    assert "Cool Song" in resp.text


def test_player_widget_empty(client, seed_user, test_engine):
    resp = client.get("/u/testuser/player")
    assert resp.status_code == 200
    assert "no tracks" in resp.text


def test_player_404(client, seed_user):
    resp = client.get("/u/nonexistent/player")
    assert resp.status_code == 404


def test_add_track_to_playlist(authed_client, seed_user, test_engine):
    mid = _create_audio_media(test_engine, seed_user["id"], "new_track.mp3")
    resp = authed_client.post(
        "/settings/player/add",
        data={"media_id": mid},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    with test_engine.begin() as conn:
        rows = conn.execute(
            select(playlist_items).where(playlist_items.c.user_id == seed_user["id"])
        ).fetchall()
    assert len(rows) == 1
    assert rows[0].media_id == mid


def test_remove_track_from_playlist(authed_client, seed_user, test_engine):
    mid = _create_audio_media(test_engine, seed_user["id"], "remove_me.mp3")
    with test_engine.begin() as conn:
        result = conn.execute(
            insert(playlist_items).values(
                user_id=seed_user["id"],
                media_id=mid,
                position=0,
            )
        )
        item_id = result.inserted_primary_key[0]

    resp = authed_client.post(
        f"/settings/player/{item_id}/remove",
        follow_redirects=False,
    )
    assert resp.status_code == 303

    with test_engine.begin() as conn:
        rows = conn.execute(
            select(playlist_items).where(playlist_items.c.user_id == seed_user["id"])
        ).fetchall()
    assert len(rows) == 0


def test_move_track(authed_client, seed_user, test_engine):
    mid1 = _create_audio_media(test_engine, seed_user["id"], "track_a.mp3")
    mid2 = _create_audio_media(test_engine, seed_user["id"], "track_b.mp3")
    with test_engine.begin() as conn:
        conn.execute(
            insert(playlist_items).values(
                user_id=seed_user["id"],
                media_id=mid1,
                position=0,
                title="Track A",
            )
        )
        res2 = conn.execute(
            insert(playlist_items).values(
                user_id=seed_user["id"],
                media_id=mid2,
                position=1,
                title="Track B",
            )
        )
        item_b_id = res2.inserted_primary_key[0]

    resp = authed_client.post(
        f"/settings/player/{item_b_id}/move",
        data={"direction": "up"},
        follow_redirects=False,
    )
    assert resp.status_code == 303

    with test_engine.begin() as conn:
        rows = (
            conn.execute(
                select(playlist_items.c.title, playlist_items.c.position)
                .where(playlist_items.c.user_id == seed_user["id"])
                .order_by(playlist_items.c.position)
            )
            .mappings()
            .all()
        )
    assert rows[0]["title"] == "Track B"
    assert rows[1]["title"] == "Track A"


def test_save_webring_toggle(authed_client, seed_user, test_engine):
    resp = authed_client.post(
        "/settings/webring",
        data={"in_webring": "on"},
    )
    assert resp.status_code == 200 or resp.status_code == 303

    with test_engine.begin() as conn:
        row = conn.execute(
            select(users.c.in_webring).where(users.c.id == seed_user["id"])
        ).one()
    assert row[0] is True or row[0] == 1


def test_save_player_css(authed_client, seed_user, test_engine):
    custom_css = "body { background: red; }"
    resp = authed_client.post(
        "/settings/player",
        data={"player_css": custom_css},
    )
    assert resp.status_code == 200 or resp.status_code == 303

    with test_engine.begin() as conn:
        row = conn.execute(
            select(users.c.player_css).where(users.c.id == seed_user["id"])
        ).one()
    assert row[0] == custom_css
