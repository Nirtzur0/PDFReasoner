from __future__ import annotations

import re

from papercoach.models import Highlight, SpanRef, TextBlock

THEOREM_RE = re.compile(r"^(Theorem|Lemma|Proposition|Corollary|Definition|Assumption)\b", re.IGNORECASE)
PROOF_RE = re.compile(r"^Proof\b", re.IGNORECASE)
MATH_TOKEN_RE = re.compile(r"[=+\-*/^_∑∫λμσπθΩαβγδ]|\\[a-zA-Z]+")
SECTION_TITLE_RE = re.compile(
    r"^(abstract|introduction|related work|background|method|methods|experiments|results|discussion|conclusion|references)\b",
    re.IGNORECASE,
)
NUMBERED_HEADING_RE = re.compile(r"^\d+(\.\d+)*\s+[A-Z]")
HEADING_STYLE_RE = re.compile(r"^(the\s+)?([A-Z][A-Za-z0-9\-']+\s+){1,6}[A-Z][A-Za-z0-9\-']+$")


def _is_equation_block(block: TextBlock) -> bool:
    text = block.text
    if len(text) < 8:
        return False
    token_hits = len(MATH_TOKEN_RE.findall(text))
    ratio = token_hits / max(len(text), 1)
    if "=" in text and token_hits >= 2:
        return True
    return token_hits >= 4 and ratio > 0.04


def _is_section_heading_block(block: TextBlock, baseline_size: float) -> bool:
    text = block.text.strip()
    if len(text) < 3 or len(text) > 90:
        return False
    if text.endswith("."):
        return False
    if SECTION_TITLE_RE.match(text):
        return True
    if NUMBERED_HEADING_RE.match(text):
        return True
    if HEADING_STYLE_RE.match(text) and len(words := text.split()) <= 8:
        lower_words = [w.lower() for w in words]
        heading_keywords = {"algorithm", "model", "methods", "step", "analysis", "results", "references"}
        if any(k in lower_words for k in heading_keywords):
            return True
    words = text.split()
    avg_size = float(block.font_meta.get("avg_size", 0.0))
    if len(words) <= 8 and (bool(block.font_meta.get("bold")) or avg_size >= baseline_size * 1.12):
        return True
    return False


def detect_highlights(blocks: list[TextBlock]) -> tuple[list[Highlight], list[SpanRef], list[tuple[TextBlock, str]]]:
    highlights: list[Highlight] = []
    anchors: list[SpanRef] = []
    note_targets: list[tuple[TextBlock, str]] = []
    sizes = [float(b.font_meta.get("avg_size", 0.0)) for b in blocks if b.text.strip()]
    baseline_size = sorted(sizes)[len(sizes) // 2] if sizes else 10.0

    for b in blocks:
        tag = None
        if THEOREM_RE.match(b.text):
            tag = "theorem_like"
        elif PROOF_RE.match(b.text):
            tag = "proof"
        elif _is_equation_block(b):
            tag = "equation"
        elif _is_section_heading_block(b, baseline_size):
            tag = "section_heading"

        if tag:
            highlights.append(Highlight(page=b.page, bbox=b.bbox, tag=tag))
            anchors.append(
                SpanRef(
                    page=b.page,
                    block_id=b.block_id,
                    span_index=0,
                    bbox=b.bbox,
                    text=b.text,
                )
            )
            note_targets.append((b, tag))

    return highlights, anchors, note_targets
