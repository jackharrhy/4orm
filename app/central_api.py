"""Validate centrally issued API tokens and resolve explicit local identity links."""

import base64
import json
import os
import time
from pathlib import Path
from urllib.parse import quote, urlparse

from sqlalchemy import select

from app import oidc
from app.schema import external_identities, users


def get_api_user(conn, token, permission):
    issuer, _, _ = oidc.configuration()
    project = os.environ["OIDC_PROJECT_ID"]
    organization = os.environ["OIDC_ORGANIZATION_ID"]
    credentials = json.loads(Path(os.environ["OIDC_API_CREDENTIALS_FILE"]).read_text())
    if (
        not project
        or not organization
        or not isinstance(credentials, dict)
        or not all(
            isinstance(credentials.get(key), str) and credentials[key]
            for key in ("clientId", "clientSecret")
        )
    ):
        raise ValueError("Central API credentials are not configured")
    document = oidc.discovery(issuer)
    endpoint = document.get("introspection_endpoint", "")
    if urlparse(endpoint).scheme != "https" or (
        urlparse(endpoint).netloc != urlparse(issuer).netloc
    ):
        raise ValueError("Introspection endpoint is outside the configured issuer")
    basic = base64.b64encode(
        (
            quote(credentials["clientId"], safe="")
            + ":"
            + quote(credentials["clientSecret"], safe="")
        ).encode()
    ).decode()
    claims = oidc.provider_json(
        endpoint,
        {"token": token, "token_type_hint": "access_token"},
        headers={"Authorization": "Basic " + basic},
    )
    if not valid_claims(claims, issuer, project, organization, permission):
        return None
    return (
        conn.execute(
            select(users)
            .join(external_identities, external_identities.c.user_id == users.c.id)
            .where(
                external_identities.c.issuer == issuer,
                external_identities.c.subject == claims["sub"],
                users.c.is_disabled.is_(False),
            )
        )
        .mappings()
        .first()
    )


def valid_claims(claims, issuer, project, organization, permission):
    if not isinstance(claims, dict):
        return False
    audience = claims.get("aud")
    if isinstance(audience, str):
        audience = [audience]
    expiration = claims.get("exp")
    role_claim = claims.get(f"urn:zitadel:iam:org:project:{project}:roles")
    member = role_claim.get("member") if isinstance(role_claim, dict) else None
    grant = role_claim.get(permission) if isinstance(role_claim, dict) else None
    required_scopes = {
        f"urn:zitadel:iam:org:project:id:{project}:aud",
        "urn:zitadel:iam:org:projects:roles",
        "urn:zitadel:iam:org:project:role:member",
    }
    if permission:
        required_scopes.add(f"urn:zitadel:iam:org:project:role:{permission}")
    return (
        claims.get("active") is True
        and claims.get("iss") == issuer
        and isinstance(claims.get("sub"), str)
        and bool(claims["sub"])
        and isinstance(claims.get("client_id"), str)
        and bool(claims["client_id"])
        and isinstance(expiration, (float, int))
        and not isinstance(expiration, bool)
        and expiration > time.time()
        and isinstance(audience, list)
        and all(isinstance(value, str) for value in audience)
        and project in audience
        and claims.get("jack_auth_principal_type") == "user"
        and isinstance(claims.get("token_type"), str)
        and claims["token_type"].lower() == "bearer"
        and isinstance(claims.get("scope"), str)
        and required_scopes <= set(claims["scope"].split())
        and isinstance(member, dict)
        and isinstance(member.get(organization), str)
        and (
            not permission
            or (isinstance(grant, dict) and isinstance(grant.get(organization), str))
        )
    )
