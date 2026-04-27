"""Sync OAuth2 clients from a TOML config file to the database.

On every app startup the declared clients are reconciled with the DB:
  - new clients are inserted
  - existing clients are updated to match the file
  - clients in the DB but absent from the file are deleted

The TOML format is:

    [clients.<client_id>]
    client_name = "My App"
    redirect_uris = ["https://example.com/callback"]
    scope = "openid profile"                      # optional, default "openid profile"
    grant_types = "authorization_code"             # optional
    response_types = "code"                        # optional
    token_endpoint_auth_method = "none"            # optional
    client_secret = ""                             # optional, default "" (public client)
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from loguru import logger
from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Engine

from app.schema import oauth2_clients

# Defaults for optional fields
_DEFAULTS = {
    "client_secret": "",
    "scope": "openid profile",
    "grant_types": "authorization_code",
    "response_types": "code",
    "token_endpoint_auth_method": "none",
}


def sync_oauth2_clients(engine: Engine, config_path: Path) -> None:
    """Read *config_path* and reconcile the ``oauth2_clients`` table."""
    if not config_path.exists():
        logger.info("No OAuth2 clients config at {}, skipping sync", config_path)
        return

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    declared: dict[str, dict] = data.get("clients", {})

    with engine.begin() as conn:
        existing_rows = conn.execute(select(oauth2_clients)).mappings().all()
        existing = {row["client_id"]: dict(row) for row in existing_rows}

        # --- insert / update ---
        for client_id, cfg in declared.items():
            # redirect_uris: list in TOML → newline-separated string in DB
            redirect_uris_raw = cfg.get("redirect_uris", [])
            if isinstance(redirect_uris_raw, list):
                redirect_uris = "\n".join(redirect_uris_raw)
            else:
                redirect_uris = str(redirect_uris_raw)

            values = {
                "client_name": cfg["client_name"],
                "redirect_uris": redirect_uris,
                "client_secret": cfg.get("client_secret", _DEFAULTS["client_secret"]),
                "scope": cfg.get("scope", _DEFAULTS["scope"]),
                "grant_types": cfg.get("grant_types", _DEFAULTS["grant_types"]),
                "response_types": cfg.get("response_types", _DEFAULTS["response_types"]),
                "token_endpoint_auth_method": cfg.get(
                    "token_endpoint_auth_method",
                    _DEFAULTS["token_endpoint_auth_method"],
                ),
            }

            if client_id in existing:
                # Check if anything changed
                row = existing[client_id]
                changed = any(row[k] != v for k, v in values.items())
                if changed:
                    conn.execute(
                        update(oauth2_clients)
                        .where(oauth2_clients.c.client_id == client_id)
                        .values(**values)
                    )
                    logger.info("OAuth2 client '{}' updated", client_id)
            else:
                conn.execute(
                    insert(oauth2_clients).values(client_id=client_id, **values)
                )
                logger.info("OAuth2 client '{}' created", client_id)

        # --- remove clients not in the config ---
        declared_ids = set(declared.keys())
        for client_id in existing:
            if client_id not in declared_ids:
                conn.execute(
                    delete(oauth2_clients).where(
                        oauth2_clients.c.client_id == client_id
                    )
                )
                logger.info("OAuth2 client '{}' removed (not in config)", client_id)
