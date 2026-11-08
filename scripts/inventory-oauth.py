"""Read legacy client policies and aggregate activity without exporting credentials."""

import argparse
import datetime
import json
import sqlite3
import time
from pathlib import Path


def inventory(database):
    now = int(time.time())
    with sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        clients = []
        for row in conn.execute(
            "SELECT client_id, client_kind, registration_source, is_enabled, "
            "redirect_uris, scope, allowed_resources, grant_types, "
            "token_endpoint_auth_method FROM oauth2_clients ORDER BY client_id"
        ):
            client = dict(row)
            activity = conn.execute(
                "SELECT count(*) AS total, "
                "coalesce(sum(revoked=0 AND issued_at+expires_in>?),0) "
                "AS active_access, "
                "coalesce(sum(revoked=0 AND refresh_token IS NOT NULL),0) "
                "AS unrevoked_refresh, max(issued_at) AS last_issued "
                "FROM oauth2_tokens WHERE client_id=?",
                (now, row["client_id"]),
            ).fetchone()
            client["tokens"] = dict(activity)
            # Activity alone cannot establish that an enabled consumer is retired.
            client["acceptance_required"] = bool(row["is_enabled"])
            clients.append(client)
        identities = dict(
            conn.execute(
                "SELECT count(*) AS links, count(distinct user_id) AS linked_users "
                "FROM external_identities"
            ).fetchone()
        )
    return {
        "observed_at": datetime.datetime.fromtimestamp(now, datetime.UTC).isoformat(),
        "clients": clients,
        "identity_counts": identities,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(inventory(args.database), indent=2))
