import json
import runpy
import sqlite3
from pathlib import Path


def test_inventory_exports_policies_and_counts_without_credentials(tmp_path):
    inventory = runpy.run_path(
        str(Path(__file__).parents[1] / "scripts/inventory-oauth.py")
    )["inventory"]
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as conn:
        conn.executescript(
            """
            CREATE TABLE oauth2_clients (
                client_id TEXT, client_kind TEXT, registration_source TEXT,
                is_enabled INTEGER, redirect_uris TEXT, scope TEXT,
                allowed_resources TEXT, grant_types TEXT,
                token_endpoint_auth_method TEXT, client_secret_hash TEXT
            );
            INSERT INTO oauth2_clients VALUES (
                'cli', 'public', 'declarative', 1, 'http://localhost/callback',
                'profile', '', 'authorization_code refresh_token', 'none',
                'SECRET_HASH_MUST_NOT_EXPORT'
            );
            CREATE TABLE oauth2_tokens (
                client_id TEXT, revoked INTEGER, issued_at INTEGER,
                expires_in INTEGER, refresh_token TEXT, access_token TEXT
            );
            INSERT INTO oauth2_tokens VALUES (
                'cli', 0, 1, 60, 'PRIVATE_REFRESH', 'PRIVATE_ACCESS'
            );
            CREATE TABLE external_identities (user_id INTEGER, subject TEXT);
            INSERT INTO external_identities VALUES (42, 'PRIVATE_SUBJECT');
            """
        )
    before = database.read_bytes()
    report = inventory(database)
    encoded = json.dumps(report)
    for private in (
        "SECRET_HASH_MUST_NOT_EXPORT",
        "PRIVATE_REFRESH",
        "PRIVATE_ACCESS",
        "PRIVATE_SUBJECT",
    ):
        assert private not in encoded
    assert report["clients"][0]["tokens"]["active_access"] == 0
    assert report["clients"][0]["tokens"]["unrevoked_refresh"] == 1
    assert report["clients"][0]["acceptance_required"] is True
    assert report["identity_counts"] == {"links": 1, "linked_users": 1}
    assert database.read_bytes() == before
