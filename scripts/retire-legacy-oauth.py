"""Retire historical issuer credentials after reviewed consumer/live acceptance."""

import argparse
import hashlib
import json
import os
import runpy
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

inventory = runpy.run_path(str(Path(__file__).with_name("inventory-oauth.py")))[
    "inventory"
]
EVENT = "legacy_issuer_retired"


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def verify_origin(origin):
    if origin != "https://4orm.harrhy.xyz":
        raise ValueError("Retirement requires the canonical production origin")
    for method, path in [
        ("GET", "/.well-known/openid-configuration"),
        ("GET", "/.well-known/oauth-authorization-server"),
        ("GET", "/oauth/authorize"),
        ("GET", "/oauth/userinfo"),
        ("POST", "/oauth/token"),
        ("POST", "/oauth/introspect"),
        ("POST", "/oauth/register"),
        ("GET", "/admin/oauth"),
        ("POST", "/login"),
        ("POST", "/register"),
        ("POST", "/login/forgot-password"),
    ]:
        request = Request(
            origin + path, method=method, data=b"" if method == "POST" else None
        )
        try:
            with urlopen(request, timeout=12) as response:
                status = response.status
        except HTTPError as error:
            status = error.code
        expected = (
            {405}
            if path in {"/login", "/register", "/login/forgot-password"}
            else {404, 410}
        )
        if status not in expected:
            raise ValueError(f"Legacy surface remains: {method} {path} ({status})")
    with urlopen(origin + "/api/v1/auth-config", timeout=12) as response:
        configuration = json.load(response)
    if configuration.get("issuer") != "https://auth.jackharrhy.dev":
        raise ValueError("API must advertise only the central issuer")


def retire(database, reviewed, acceptance, backup, receipt, origin):
    if database.resolve() == backup.resolve() or not backup.is_file():
        raise ValueError("A separate retained SQLite backup is required")
    with sqlite3.connect(backup.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Backup integrity failed")
    approved = json.loads(acceptance.read_text())
    if approved.get("allConsumerClassesAccepted") is not True:
        raise ValueError("Consumer acceptance is incomplete")
    expected = json.loads(reviewed.read_text())["clients"]
    if sorted(approved.get("legacyClientIds", [])) != sorted(
        c["client_id"] for c in expected
    ):
        raise ValueError("Acceptance does not cover the reviewed legacy client set")
    verify_origin(origin)
    result = {
        "status": "prepared",
        "checkedAt": datetime.now(UTC).isoformat(),
        "backup": str(backup.resolve()),
        "backupSha256": digest(backup),
        "reviewedInventorySha256": digest(reviewed),
        "acceptanceSha256": digest(acceptance),
    }
    with sqlite3.connect(database.resolve().as_uri() + "?mode=rw", uri=True) as conn:
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute(
            "SELECT count(*) FROM oauth2_audit_events WHERE event_type=?", (EVENT,)
        ).fetchone()[0]:
            raise ValueError("Legacy retirement is already recorded; do not replay")
        current = inventory(database)["clients"]
        if current != expected:
            raise ValueError("Legacy inventory changed; audit before retirement")
        with sqlite3.connect(backup.resolve().as_uri() + "?mode=ro", uri=True) as saved:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            for (table,) in tables:
                if table == "visitor_counters":
                    continue
                quoted = '"' + table.replace('"', '""') + '"'
                query = "SELECT * FROM " + quoted
                live_rows = sorted(conn.execute(query).fetchall(), key=repr)
                backup_rows = sorted(saved.execute(query).fetchall(), key=repr)
                if live_rows != backup_rows:
                    raise ValueError(
                        "Backup is not current; preserve it and take a fresh one"
                    )
        # Reserve the evidence path before any write, so a retry cannot replace it.
        descriptor = os.open(receipt, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w") as stream:
            json.dump(result, stream, indent=2)
            stream.write("\n")
        result["disabledClients"] = conn.execute(
            "UPDATE oauth2_clients SET is_enabled=0 WHERE is_enabled!=0"
        ).rowcount
        result["revokedTokens"] = conn.execute(
            "UPDATE oauth2_tokens SET revoked=1 WHERE revoked=0"
        ).rowcount
        result["expiredAuthorizationCodes"] = conn.execute(
            "UPDATE oauth2_authorization_codes "
            "SET expires_at='1970-01-01 00:00:00.000000' "
            "WHERE expires_at>CURRENT_TIMESTAMP"
        ).rowcount
        result["spentLocalResetTokens"] = conn.execute(
            "UPDATE password_reset_tokens SET used_at=CURRENT_TIMESTAMP "
            "WHERE used_at IS NULL AND expires_at>CURRENT_TIMESTAMP"
        ).rowcount
        detail = json.dumps(
            {k: v for k, v in result.items() if k != "backup"}, sort_keys=True
        )
        conn.execute(
            "INSERT INTO oauth2_audit_events (event_type,success,detail) "
            "VALUES (?,1,?)",
            (EVENT, detail),
        )
        if (
            conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok"
            or conn.execute("PRAGMA foreign_key_check").fetchall()
        ):
            raise ValueError("Post-retirement database integrity failed")
        conn.commit()
    result["status"] = "committed"
    # A prepared-only receipt is an unknown outcome: inspect the DB audit event.
    # Never overwrite a prior receipt or automatically repeat the mutation.
    receipt.write_text(json.dumps(result, indent=2) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--reviewed-inventory", type=Path)
    parser.add_argument("--acceptance", type=Path)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--origin", default="https://4orm.harrhy.xyz")
    args = parser.parse_args()
    if not args.apply:
        report = inventory(args.database)
        print(
            json.dumps(
                {
                    "mode": "read-only",
                    "clients": len(report["clients"]),
                    "enabledClients": sum(
                        c["acceptance_required"] for c in report["clients"]
                    ),
                    "unrevokedRefreshRows": sum(
                        c["tokens"]["unrevoked_refresh"] for c in report["clients"]
                    ),
                }
            )
        )
        return
    if not all((args.reviewed_inventory, args.acceptance, args.backup, args.receipt)):
        parser.error(
            "--apply requires reviewed inventory, acceptance, backup and new receipt"
        )
    print(
        json.dumps(
            retire(
                args.database,
                args.reviewed_inventory,
                args.acceptance,
                args.backup,
                args.receipt,
                args.origin,
            ),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
