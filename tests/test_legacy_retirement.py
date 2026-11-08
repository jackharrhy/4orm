"""Guard irreversible issuer retirement while retaining data and audit rows."""

import json
import runpy
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine, insert

from app.schema import metadata, oauth2_clients, oauth2_tokens, profile_cards, users

module = runpy.run_path(
    str(Path(__file__).parents[1] / "scripts/retire-legacy-oauth.py")
)


@pytest.fixture
def retirement(tmp_path, monkeypatch):
    database = tmp_path / "live.db"
    engine = create_engine("sqlite:///" + str(database))
    metadata.create_all(engine)
    with engine.begin() as conn:
        uid = conn.execute(
            insert(users).values(
                username="member",
                display_name="Member",
                password_hash="historical-unused-hash",
            )
        ).inserted_primary_key[0]
        conn.execute(insert(profile_cards).values(user_id=uid, headline="Preserved"))
        conn.execute(
            insert(oauth2_clients).values(client_id="legacy", client_name="Legacy")
        )
        conn.execute(
            insert(oauth2_tokens).values(
                client_id="legacy",
                user_id=uid,
                access_token="PRIVATE_OLD_BEARER",
                refresh_token="PRIVATE_OLD_REFRESH",
                issued_at=0,
                expires_in=1,
            )
        )
    engine.dispose()
    backup = tmp_path / "saved.db"
    with sqlite3.connect(database) as conn, sqlite3.connect(backup) as target:
        conn.backup(target)
    reviewed = tmp_path / "review.json"
    reviewed.write_text(json.dumps(module["inventory"](database)))
    acceptance = tmp_path / "acceptance.json"
    acceptance.write_text(
        json.dumps({"allConsumerClassesAccepted": True, "legacyClientIds": ["legacy"]})
    )
    monkeypatch.setitem(
        module["retire"].__globals__, "verify_origin", lambda origin: None
    )
    return (
        database,
        reviewed,
        acceptance,
        backup,
        tmp_path / "receipt.json",
        "https://4orm.harrhy.xyz",
    )


def test_retirement_preserves_users_content_rows_and_backup(retirement):
    database, _, _, backup, receipt, _ = retirement
    before = backup.read_bytes()
    result = module["retire"](*retirement)
    assert result["status"] == "committed"
    assert result["disabledClients"] == result["revokedTokens"] == 1
    with sqlite3.connect(database) as conn:
        assert conn.execute("select is_enabled from oauth2_clients").fetchone() == (0,)
        assert conn.execute("select revoked from oauth2_tokens").fetchone() == (1,)
        assert conn.execute("select count(*) from users").fetchone() == (1,)
        assert conn.execute("select headline from profile_cards").fetchone() == (
            "Preserved",
        )
        assert conn.execute(
            "select count(*) from oauth2_audit_events "
            "where event_type='legacy_issuer_retired'"
        ).fetchone() == (1,)
    assert backup.read_bytes() == before
    assert receipt.stat().st_mode & 0o777 == 0o600
    assert "PRIVATE_OLD" not in receipt.read_text()
    with pytest.raises(ValueError, match="already recorded"):
        module["retire"](*retirement)


def test_retirement_rejects_new_unreviewed_client_without_mutation(retirement):
    database = retirement[0]
    with sqlite3.connect(database) as conn:
        conn.execute(
            "insert into oauth2_clients(client_id,client_name) "
            "values('new-client','Unknown')"
        )
    before = database.read_bytes()
    with pytest.raises(ValueError, match="inventory changed"):
        module["retire"](*retirement)
    assert database.read_bytes() == before
    assert not retirement[4].exists()


def test_retirement_rejects_unaccepted_consumers_and_stale_backup(retirement):
    database, _, acceptance, _, receipt, _ = retirement
    original = acceptance.read_text()
    acceptance.write_text("{}")
    with pytest.raises(ValueError, match="incomplete"):
        module["retire"](*retirement)
    acceptance.write_text(original)
    with sqlite3.connect(database) as conn:
        conn.execute("update profile_cards set headline='New content'")
    with pytest.raises(ValueError, match="Backup is not current"):
        module["retire"](*retirement)
    assert not receipt.exists()


def test_retirement_requires_removed_live_token_endpoint(monkeypatch):
    from urllib.error import HTTPError

    def old_token_endpoint(request, **kwargs):
        url = request if isinstance(request, str) else request.full_url
        status = 400 if url.endswith("/oauth/token") else 404
        raise HTTPError(url, status, "fixture", {}, None)

    monkeypatch.setitem(
        module["verify_origin"].__globals__, "urlopen", old_token_endpoint
    )
    with pytest.raises(ValueError, match="POST /oauth/token"):
        module["verify_origin"]("https://4orm.harrhy.xyz")
