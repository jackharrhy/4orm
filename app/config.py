"""Deployment configuration with fail-fast production validation."""

import os


def session_config() -> dict:
    """Return Starlette session settings for the current environment."""
    environment = os.environ.get("FOURM_ENV", "production").strip().lower()
    secret_key = os.environ.get("SECRET_KEY")

    if environment not in {"development", "test", "production"}:
        raise RuntimeError("FOURM_ENV must be one of: development, test, production")
    if not secret_key:
        if environment == "production":
            raise RuntimeError(
                "SECRET_KEY is required when FOURM_ENV=production. "
                "Generate one with: openssl rand -hex 32"
            )
        secret_key = "4orm-local-development-only"

    return {
        "secret_key": secret_key,
        "https_only": environment == "production",
        "same_site": "lax",
    }
