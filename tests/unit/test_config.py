from __future__ import annotations

from papercoach.config import DEFAULT_CHATMOCK_API_KEY, DEFAULT_CHATMOCK_BASE_URL, ServiceConfig


def test_service_config_defaults_to_local_chatmock(monkeypatch) -> None:
    monkeypatch.delenv("PAPERCOACH_BASE_URL", raising=False)
    monkeypatch.delenv("PAPERCOACH_API_KEY", raising=False)
    monkeypatch.delenv("PAPERCOACH_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)

    config = ServiceConfig()

    assert config.base_url == DEFAULT_CHATMOCK_BASE_URL
    assert config.api_key == DEFAULT_CHATMOCK_API_KEY
    assert config.model == "gpt-5"


def test_service_config_uses_openai_defaults_when_available(monkeypatch) -> None:
    monkeypatch.delenv("PAPERCOACH_BASE_URL", raising=False)
    monkeypatch.delenv("PAPERCOACH_API_KEY", raising=False)
    monkeypatch.delenv("PAPERCOACH_MODEL", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5-mini")

    config = ServiceConfig()

    assert config.base_url == "https://api.openai.com/v1"
    assert config.api_key == "openai-key"
    assert config.model == "gpt-5-mini"


def test_service_config_prefers_explicit_papercoach_settings(monkeypatch) -> None:
    monkeypatch.setenv("PAPERCOACH_BASE_URL", "http://127.0.0.1:9000/v1")
    monkeypatch.setenv("PAPERCOACH_API_KEY", "papercoach-key")
    monkeypatch.setenv("PAPERCOACH_MODEL", "gpt-5")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5-mini")

    config = ServiceConfig()

    assert config.base_url == "http://127.0.0.1:9000/v1"
    assert config.api_key == "papercoach-key"
    assert config.model == "gpt-5"
