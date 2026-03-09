from __future__ import annotations

from pydantic import BaseModel, Field


class Box(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float


class Point(BaseModel):
    x: float
    y: float


class QuadPoints(BaseModel):
    ul: Point
    ur: Point
    ll: Point
    lr: Point


class PromptProfile(BaseModel):
    density: str
    audience: str
    style: str
    source_links: list[str] = Field(default_factory=list)


class CandidateBlock(BaseModel):
    block_id: str
    bbox: Box
    text: str
    section_title: str | None = None
    is_heading: bool = False
    word_count: int


class HighlightSelection(BaseModel):
    highlight_id: str
    block_id: str
    label: str
    rationale: str
    confidence: float
    source_quote: str
    matched_quote: str
    quads: list[QuadPoints]


class NoteSelection(BaseModel):
    note_id: str
    highlight_id: str
    anchor_block_id: str
    title: str
    body: str
    confidence: float


class EquationSelection(BaseModel):
    equation_id: str
    block_id: str
    page_number: int
    equation_text_clean: str
    source_kind: str
    equation_label: str | None = None
    quads: list[QuadPoints]
    role: str
    confidence: float


class EquationExplanation(BaseModel):
    equation_id: str
    title: str
    display_latex: str | None = None
    symbol_map: dict[str, str] = Field(default_factory=dict)
    body: str
    intuition: str
    confidence: float


class PagePlan(BaseModel):
    page_number: int
    width: float
    height: float
    is_reference_page: bool
    candidate_blocks: list[CandidateBlock] = Field(default_factory=list)
    highlights: list[HighlightSelection] = Field(default_factory=list)
    notes: list[NoteSelection] = Field(default_factory=list)
    equations: list[EquationSelection] = Field(default_factory=list)
    equation_notes: list[EquationExplanation] = Field(default_factory=list)


class PaperMeta(BaseModel):
    paper_id: str
    title: str
    input_pdf: str
    page_count: int


class HighlightPlan(BaseModel):
    meta: PaperMeta
    prompt_profile: PromptProfile
    pages: list[PagePlan]


class RunManifest(BaseModel):
    input_pdf: str
    output_pdf: str
    plan_path: str
    trace_path: str
    model: str
    highlight_count: int
    pages_with_highlights: int
    note_count: int
    equation_count: int = 0
    equation_note_count: int = 0
