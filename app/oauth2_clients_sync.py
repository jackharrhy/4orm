"""Sync OAuth2 clients from a TOML config file to the database.

On every app startup the declared clients are reconciled with the DB:
  - new clients are inserted
  - existing clients are updated to match the file
  - declarative clients absent from the file are disabled and their tokens revoked
  - dynamically registered clients are left unchanged

The TOML format is:

    [clients.<client_id>]
    client_name = "My App"
    redirect_uris = ["https://example.com/callback"]
    scope = "openid profile"                      # optional, default "openid profile"
    allowed_resources = ["https://api.example.com/mcp"] # optional
    grant_types = "authorization_code"             # optional
    response_types = "code"                        # optional
    token_endpoint_auth_method = "none"            # optional
    client_kind = "service"                       # public, service, resource_server
    subject = "my-service"                        # required for service clients
    access_token_lifetime = 600                    # optional

Secrets are generated and rotated in the 4orm admin interface. Sync never reads
or overwrites secret hashes.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from loguru import logger
from sqlalchemy import func, insert, select, update
from sqlalchemy.engine import Engine

from app.schema import oauth2_audit_events, oauth2_clients, oauth2_tokens

# Defaults for optional fields
_DEFAULTS = {
    "scope": "openid profile",
    "grant_types": "authorization_code",
    "response_types": "code",
    "token_endpoint_auth_method": "none",
    "client_kind": "public",
    "subject": "",
    "access_token_lifetime": 3600,
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

            allowed_resources_raw = cfg.get("allowed_resources", [])
            if not isinstance(allowed_resources_raw, list) or not all(
                isinstance(resource, str) and resource
                for resource in allowed_resources_raw
            ):
                raise ValueError(
                    f"OAuth client {client_id} allowed_resources must be a list "
                    "of non-empty strings"
                )
            allowed_resources = "\n".join(allowed_resources_raw)

            kind = cfg.get("client_kind", _DEFAULTS["client_kind"])
            if kind not in {"public", "service", "resource_server"}:
                raise ValueError(f"Invalid client_kind for OAuth client {client_id}")

            values = {
                "client_name": cfg["client_name"],
                "client_kind": kind,
                "registration_source": "declarative",
                "redirect_uris": redirect_uris,
                "scope": cfg.get("scope", _DEFAULTS["scope"]),
                "allowed_resources": allowed_resources,
                "grant_types": cfg.get("grant_types", _DEFAULTS["grant_types"]),
                "response_types": cfg.get(
                    "response_types", _DEFAULTS["response_types"]
                ),
                "token_endpoint_auth_method": cfg.get(
                    "token_endpoint_auth_method",
                    _DEFAULTS["token_endpoint_auth_method"],
                ),
                "subject": cfg.get("subject", _DEFAULTS["subject"]),
                "access_token_lifetime": int(
                    cfg.get(
                        "access_token_lifetime",
                        _DEFAULTS["access_token_lifetime"],
                    )
                ),
                "is_enabled": True,
                "disabled_at": None,
                "updated_at": func.now(),
            }

            if kind == "service" and not values["subject"]:
                raise ValueError(f"Service OAuth client {client_id} requires subject")
            if kind == "service":
                values.update(
                    grant_types="client_credentials",
                    response_types="",
                    token_endpoint_auth_method="client_secret_basic",
                )
            elif kind == "resource_server":
                values.update(
                    subject="",
                    scope="",
                    grant_types="",
                    response_types="",
                    token_endpoint_auth_method="client_secret_basic",
                )
            elif values["token_endpoint_auth_method"] != "none":
                raise ValueError(f"Public OAuth client {client_id} cannot use a secret")
            if not 60 <= values["access_token_lifetime"] <= 86400:
                raise ValueError(
                    f"OAuth client {client_id} access_token_lifetime must be 60-86400"
                )

            if client_id in existing:
                if existing[client_id]["registration_source"] == "dynamic":
                    raise ValueError(
                        f"Declarative OAuth client {client_id} conflicts with a "
                        "dynamically registered client"
                    )
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

        # --- disable clients not in the config ---
        declared_ids = set(declared.keys())
        for client_id in existing:
            if (
                client_id not in declared_ids
                and existing[client_id]["registration_source"] == "declarative"
                and existing[client_id]["is_enabled"]
            ):
                conn.execute(
                    update(oauth2_clients)
                    .where(oauth2_clients.c.client_id == client_id)
                    .values(is_enabled=False, disabled_at=func.now())
                )
                conn.execute(
                    update(oauth2_tokens)
                    .where(oauth2_tokens.c.client_id == client_id)
                    .values(revoked=True)
                )
                conn.execute(
                    insert(oauth2_audit_events).values(
                        event_type="client_disabled",
                        client_id=client_id,
                        detail="removed from declarative configuration",
                    )
                )
                logger.info("OAuth2 client '{}' disabled (not in config)", client_id)
