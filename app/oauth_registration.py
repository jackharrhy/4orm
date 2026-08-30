"""Bounded RFC 7591 dynamic registration for Artbin MCP clients."""

from __future__ import annotations

import ipaddress
import re
import secrets
from urllib.parse import urlsplit

from sqlalchemy import insert

from app.oauth_policy import ARTBIN_ADMIN_SCOPE, ARTBIN_MCP_RESOURCE
from app.schema import oauth2_audit_events, oauth2_clients

_MAX_REDIRECT_URIS = 10
_MAX_REDIRECT_URI_LENGTH = 2048
_VALID_PERCENT_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")


class OAuthRegistrationError(Exception):
    def __init__(self, error: str, description: str):
        super().__init__(description)
        self.error = error
        self.description = description


def _registration_error(description: str) -> OAuthRegistrationError:
    return OAuthRegistrationError("invalid_client_metadata", description)


def validate_redirect_uri(uri: object) -> str:
    """Validate a public-client redirect URI without normalizing it."""
    if not isinstance(uri, str) or not uri or len(uri) > _MAX_REDIRECT_URI_LENGTH:
        raise OAuthRegistrationError(
            "invalid_redirect_uri", "Each redirect URI must be a non-empty string."
        )
    if any(not 0x21 <= ord(character) <= 0x7E for character in uri) or "\\" in uri:
        raise OAuthRegistrationError(
            "invalid_redirect_uri", "The redirect URI is malformed."
        )
    if _VALID_PERCENT_ESCAPE.search(uri):
        raise OAuthRegistrationError(
            "invalid_redirect_uri", "The redirect URI has invalid percent encoding."
        )

    try:
        parsed = urlsplit(uri)
        # Accessing port makes urllib validate invalid and out-of-range ports.
        _port = parsed.port
    except ValueError as error:
        raise OAuthRegistrationError(
            "invalid_redirect_uri", "The redirect URI is malformed."
        ) from error

    if (
        not parsed.scheme
        or not parsed.netloc
        or not parsed.hostname
        or parsed.fragment
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise OAuthRegistrationError(
            "invalid_redirect_uri",
            "Redirect URIs require an authority and cannot contain credentials "
            "or fragments.",
        )

    scheme = parsed.scheme.lower()
    if scheme == "https":
        return uri
    if scheme != "http":
        raise OAuthRegistrationError(
            "invalid_redirect_uri", "Redirect URIs must use HTTPS or HTTP loopback."
        )

    hostname = parsed.hostname.lower()
    if hostname == "localhost":
        return uri
    try:
        is_loopback = ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        is_loopback = False
    if not is_loopback:
        raise OAuthRegistrationError(
            "invalid_redirect_uri", "HTTP redirect URIs must use a loopback host."
        )
    return uri


def _string_list(metadata: dict, name: str, default: list[str]) -> list[str]:
    value = metadata.get(name, default)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise _registration_error(f"{name} must be an array of strings.")
    if len(value) != len(set(value)):
        raise _registration_error(f"{name} cannot contain duplicate values.")
    return value


def validate_registration_metadata(metadata: object) -> dict:
    """Return the accepted public-client metadata or raise an RFC 7591 error."""
    if not isinstance(metadata, dict):
        raise _registration_error("The registration body must be a JSON object.")

    redirect_uris = metadata.get("redirect_uris")
    if (
        not isinstance(redirect_uris, list)
        or not redirect_uris
        or len(redirect_uris) > _MAX_REDIRECT_URIS
    ):
        raise OAuthRegistrationError(
            "invalid_redirect_uri",
            f"redirect_uris must contain between 1 and {_MAX_REDIRECT_URIS} values.",
        )
    validated_redirect_uris = [validate_redirect_uri(uri) for uri in redirect_uris]
    if len(validated_redirect_uris) != len(set(validated_redirect_uris)):
        raise OAuthRegistrationError(
            "invalid_redirect_uri", "redirect_uris cannot contain duplicate values."
        )

    auth_method = metadata.get("token_endpoint_auth_method", "none")
    if auth_method != "none":
        raise _registration_error(
            "Only public clients using no authentication are supported."
        )

    grant_types = _string_list(metadata, "grant_types", ["authorization_code"])
    allowed_grants = {"authorization_code", "refresh_token"}
    if "authorization_code" not in grant_types or not set(grant_types).issubset(
        allowed_grants
    ):
        raise _registration_error(
            "Only authorization_code with optional refresh_token is supported."
        )

    response_types = _string_list(metadata, "response_types", ["code"])
    if response_types != ["code"]:
        raise _registration_error("Only the code response type is supported.")

    if "scope" in metadata:
        requested_scope = metadata["scope"]
        if not isinstance(requested_scope, str) or requested_scope.split() != [
            ARTBIN_ADMIN_SCOPE
        ]:
            raise _registration_error(
                f"Dynamic clients may request only {ARTBIN_ADMIN_SCOPE}."
            )

    client_name = metadata.get("client_name", "Artbin MCP client")
    if not isinstance(client_name, str):
        raise _registration_error("client_name must be a string.")
    client_name = client_name.strip()
    if not client_name or len(client_name) > 120:
        raise _registration_error(
            "client_name must contain between 1 and 120 characters."
        )

    return {
        "client_name": client_name,
        "redirect_uris": validated_redirect_uris,
        "grant_types": grant_types,
        "response_types": response_types,
        "token_endpoint_auth_method": "none",
        "scope": ARTBIN_ADMIN_SCOPE,
    }


def register_dynamic_client(conn, metadata: object) -> dict:
    """Persist and return one Artbin-scoped public client registration."""
    accepted = validate_registration_metadata(metadata)
    client_id = f"artbin-mcp-{secrets.token_urlsafe(18)}"
    conn.execute(
        insert(oauth2_clients).values(
            client_id=client_id,
            client_secret_hash="",
            client_name=accepted["client_name"],
            client_kind="public",
            registration_source="dynamic",
            subject="",
            redirect_uris="\n".join(accepted["redirect_uris"]),
            scope=ARTBIN_ADMIN_SCOPE,
            allowed_resources=ARTBIN_MCP_RESOURCE,
            grant_types=" ".join(accepted["grant_types"]),
            response_types="code",
            token_endpoint_auth_method="none",
            access_token_lifetime=600,
        )
    )
    conn.execute(
        insert(oauth2_audit_events).values(
            event_type="client_registered",
            client_id=client_id,
            detail="dynamic public Artbin MCP client",
        )
    )
    return {"client_id": client_id, **accepted}
