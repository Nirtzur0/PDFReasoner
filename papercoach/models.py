from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Rect(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float


class SpanRef(BaseModel):
    page: int
    block_id: str
    span_index: int
    bbox: list[float]
    text: str


class TextBlock(BaseModel):
    page: int
    block_id: str
    bbox: list[float]
    text: str
    font_meta: dict


class ResolvedRef(BaseModel):
    doi: str | None = None
    s2_paper_id: str | None = None
    title: str | None = None
    year: int | None = None
    venue: str | None = None
    url: str | None = None
    abstract_snippet: str | None = None


class Citation(BaseModel):
    bib_key: str | None = None
    raw: str
    in_text_spans: list[SpanRef] = Field(default_factory=list)
    resolved: ResolvedRef | None = None
    mention_count: int = 0


class EvidenceRef(BaseModel):
    type: Literal["paper", "external"]
    pointer: dict
    quote: str | None = None


class Highlight(BaseModel):
    page: int
    bbox: list[float]
    tag: str


class MarginNote(BaseModel):
    page: int
    anchor_bbox: list[float]
    note_bbox: list[float] | None = None
    title: str
    body: str
    key_points: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    confidence: float = 0.0
    uncertainties: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_confidence(self) -> "MarginNote":
        if not self.evidence and self.confidence > 0.35:
            raise ValueError("Notes without evidence must have confidence <= 0.35")
        return self


class GlossaryItem(BaseModel):
    symbol: str
    meaning: str | None = None
    first_occurrence_page: int
    first_occurrence_bbox: list[float]
    confidence: float = 0.0
    evidence: list[EvidenceRef] = Field(default_factory=list)


class MindmapArtifact(BaseModel):
    path: str
    position: Literal["cover", "appendix"]
    node_count: int
    edge_count: int


class PagePlan(BaseModel):
    page: int
    highlights: list[Highlight] = Field(default_factory=list)
    anchors: list[SpanRef] = Field(default_factory=list)
    notes: list[MarginNote] = Field(default_factory=list)


class AnnotationPlan(BaseModel):
    paper_id: str
    meta: dict
    pages: dict[int, PagePlan]
    references: list[Citation] = Field(default_factory=list)
    glossary: list[GlossaryItem] = Field(default_factory=list)
    mindmaps: list[MindmapArtifact] = Field(default_factory=list)
