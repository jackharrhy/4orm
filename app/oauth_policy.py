"""Shared OAuth scope and resource policy."""

from authlib.oauth2.rfc6749.errors import OAuth2Error

ARTBIN_ADMIN_SCOPE = "artbin:admin"
ARTBIN_MCP_RESOURCE = "https://artbin.jackharrhy.dev/mcp"


class InvalidTargetError(OAuth2Error):
    """RFC 8707 resource indicator validation failure."""

    error = "invalid_target"
    description = "The requested resource is invalid, unknown, or unauthorized."
    status_code = 400


def allowed_resources_from_text(value: str) -> tuple[str, ...]:
    """Decode the newline-separated resource policy stored on a client."""
    return tuple(resource for resource in value.splitlines() if resource)


def validate_resource_request(
    client_row: dict,
    requested_resource: str | None,
    *,
    bound_resource: str | None = None,
    require_bound_resource: bool = False,
) -> str:
    """Validate one resource indicator against client policy and grant binding.

    ``bound_resource=None`` validates an authorization request. Passing a string,
    including the empty string, validates a token or refresh request against an
    existing grant.
    """
    allowed = set(allowed_resources_from_text(client_row["allowed_resources"]))
    requested = requested_resource or ""

    if bound_resource is None:
        if not requested or requested not in allowed:
            if requested or allowed:
                raise InvalidTargetError()
            return ""
        return requested

    if bound_resource:
        if bound_resource not in allowed:
            raise InvalidTargetError()
        if requested:
            if requested != bound_resource:
                raise InvalidTargetError()
        elif require_bound_resource:
            raise InvalidTargetError()
        return bound_resource

    # Never let an unbound grant acquire an audience during token exchange or
    # refresh, including after its client's policy changes.
    if requested or allowed:
        raise InvalidTargetError()
    return ""
