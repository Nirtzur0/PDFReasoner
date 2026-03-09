from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(slots=True)
class ServiceConfig:
    base_url: str | None = os.getenv("PAPERCOACH_BASE_URL")
    api_key: str | None = os.getenv("PAPERCOACH_API_KEY")
    model: str = os.getenv("PAPERCOACH_MODEL", "gpt-5")


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
