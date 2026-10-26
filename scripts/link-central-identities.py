"""Install the reviewed identity mapping after the external-identities migration."""

import argparse
import json
import sqlite3
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--manifest", type=Path, required=True)
parser.add_argument("--database", type=Path, required=True)
parser.add_argument("--apply", action="store_true")
args = parser.parse_args()
manifest = json.loads(args.manifest.read_text())
mode = "rw" if args.apply else "ro"
connection = sqlite3.connect(
    args.database.resolve().as_uri() + "?mode=" + mode, uri=True
)
connection.execute("PRAGMA foreign_keys=ON")
with connection:
    for item in manifest.values():
        assert item["issuer"] == "https://auth.jackharrhy.dev"
        assert isinstance(item["subject"], str) and 0 < len(item["subject"]) <= 255
        local = connection.execute(
            "select username from users where id=?", (item["legacyUserId"],)
        ).fetchone()
        assert local and local[0] == item["legacyUsername"], (
            "Local account differs from reviewed mapping"
        )
        existing = connection.execute(
            "select user_id from external_identities where issuer=? and subject=?",
            (item["issuer"], item["subject"]),
        ).fetchone()
        assert not existing or existing[0] == item["legacyUserId"], (
            "Subject is linked to a different account"
        )
        if args.apply and not existing:
            connection.execute(
                "insert into external_identities (issuer, subject, user_id) "
                "values (?,?,?)",
                (item["issuer"], item["subject"], item["legacyUserId"]),
            )
print(
    ("Installed" if args.apply else "Validated")
    + f" {len(manifest)} identity links; local user IDs and content are unchanged."
)
