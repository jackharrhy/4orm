import pytest

from app.config import session_config


def test_production_requires_session_secret(monkeypatch):
    monkeypatch.setenv("FOURM_ENV", "production")
    monkeypatch.delenv("SECRET_KEY", raising=False)

    with pytest.raises(RuntimeError, match="SECRET_KEY is required"):
        session_config()


def test_production_session_cookie_is_https_only(monkeypatch):
    monkeypatch.setenv("FOURM_ENV", "production")
    monkeypatch.setenv("SECRET_KEY", "test-production-secret")

    assert session_config() == {
        "secret_key": "test-production-secret",
        "https_only": True,
        "same_site": "lax",
    }


def test_development_uses_local_session_settings(monkeypatch):
    monkeypatch.setenv("FOURM_ENV", "development")
    monkeypatch.delenv("SECRET_KEY", raising=False)

    settings = session_config()

    assert settings["https_only"] is False
    assert settings["secret_key"] == "4orm-local-development-only"
