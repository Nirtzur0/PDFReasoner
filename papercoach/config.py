from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path

DEFAULT_CHATMOCK_BASE_URL = "http://127.0.0.1:8000/v1"
DEFAULT_CHATMOCK_API_KEY = "dummy"


def _resolve_base_url() -> str | None:
    explicit_base_url = os.getenv("PAPERCOACH_BASE_URL")
    if explicit_base_url:
        return explicit_base_url
    openai_base_url = os.getenv("OPENAI_BASE_URL")
    if openai_base_url:
        return openai_base_url
    if os.getenv("OPENAI_API_KEY"):
        return "https://api.openai.com/v1"
    return DEFAULT_CHATMOCK_BASE_URL


def _resolve_api_key() -> str | None:
    return os.getenv("PAPERCOACH_API_KEY") or os.getenv("OPENAI_API_KEY") or DEFAULT_CHATMOCK_API_KEY


def _resolve_model() -> str:
    return os.getenv("PAPERCOACH_MODEL") or os.getenv("OPENAI_MODEL") or "gpt-5"


@dataclass(slots=True)
class ServiceConfig:
    base_url: str | None = field(default_factory=_resolve_base_url)
    api_key: str | None = field(default_factory=_resolve_api_key)
    model: str = field(default_factory=_resolve_model)


@dataclass(slots=True)
class RunConfig:
    input_pdf: Path
    out_pdf: Path
    workdir: Path
    density: str = "balanced"
    style: str = "minimal"
    audience: str = "paper-native"
    max_highlights_per_page: int = 3
    margin_width: float = 240.0
    max_notes_per_page: int = 3
    max_equations_per_page: int = 2

    @property
    def plan_path(self) -> Path:
        return self.workdir / "highlight_plan.json"

    @property
    def manifest_path(self) -> Path:
        return self.workdir / "run_manifest.json"

    @property
    def trace_path(self) -> Path:
        return self.workdir / "trace.jsonl"
