from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal


Level = Literal["light", "medium", "heavy"]
MindmapPosition = Literal["cover", "appendix"]


@dataclass(slots=True)
class ServiceConfig:
    grobid_url: str = os.getenv("PAPERCOACH_GROBID_URL", "http://localhost:8070")
    ollama_url: str = os.getenv("PAPERCOACH_OLLAMA_URL", "http://localhost:11434")
    ollama_model: str = os.getenv("PAPERCOACH_OLLAMA_MODEL", "llama3.1:8b-instruct-q8_0")
    crossref_url: str = "https://api.crossref.org"
    semanticscholar_url: str = "https://api.semanticscholar.org/graph/v1"


@dataclass(slots=True)
class RunConfig:
    input_pdf: Path
    out_pdf: Path
    workdir: Path
    level: Level = "medium"
    margin_width: float = 180.0
    max_notes_per_page: int = 8
    no_web: bool = False
    mindmap_position: MindmapPosition = "appendix"

    @property
    def top_n_references(self) -> int:
        if self.level == "light":
            return 5
        if self.level == "heavy":
            return 20
        return 10
