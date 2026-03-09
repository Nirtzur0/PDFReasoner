"""Equation candidate detection grounded in local PDF layout and nearby prose.

Sources:
- https://pymupdf.readthedocs.io/en/latest/recipes-text.html
- https://aclanthology.org/2020.sdp-1.16.pdf
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from papercoach.extract.extractor import ExtractedBlock, ExtractedDocument
from papercoach.extract.extractor import ExtractedWord
from papercoach.extract.normalize import clean_text
from papercoach.extract.structure import StructureDetector

_CAPTION_RE = re.compile(r"^(figure|table|algorithm)\s+\d+", re.IGNORECASE)
_EQUATION_LABEL_RE = re.compile(r"^\(?\d+\)?$")
_INLINE_LABEL_RE = re.compile(r"\((\d+)\)\s*$")
_MATH_WORD_RE = re.compile(r"\b(argmin|argmax|exp|log|sum|prod|min|max|s\.t\.|subject to)\b", re.IGNORECASE)
_GROUNDING_HINT_RE = re.compile(r"\b(where|denote|denotes|let|defined as|is the|are the)\b", re.IGNORECASE)


@dataclass(slots=True)
class EquationCandidate:
    equation_id: str
    block_id: str
    page_number: int
    equation_text_clean: str
    local_context: str
    symbol_context: str
    source_kind: str
    equation_label: str | None
    section_title: str | None
    words: list[ExtractedWord]
    quality_score: float


class EquationDetector:
    def __init__(self) -> None:
        self._structure = StructureDetector()

    def detect(self, document: ExtractedDocument) -> list[EquationCandidate]:
        candidates: list[EquationCandidate] = []
        for page in document.pages:
            if page.is_reference_page:
                continue
            blocks = [block for block in page.blocks if block.words and not self._is_reference_block(block)]
            seen_ids: set[str] = set()
            for candidate in self._grouped_row_candidates(blocks):
                if candidate.equation_id in seen_ids:
                    continue
                seen_ids.add(candidate.equation_id)
                candidates.append(candidate)
            for index, block in enumerate(blocks):
                if not self._looks_like_equation(block, page.width):
                    continue
                label = self._equation_label(block, blocks, index)
                equation_id = f"{block.block_id}-eq"
                if equation_id in seen_ids:
                    continue
                seen_ids.add(equation_id)
                candidates.append(
                    EquationCandidate(
                        equation_id=equation_id,
                        block_id=block.block_id,
                        page_number=block.page_number,
                        equation_text_clean=self._equation_text(block.text, label),
                        local_context=self._local_context(blocks, index),
                        symbol_context=self._symbol_context(blocks, index),
                        source_kind=self._source_kind(blocks, index),
                        equation_label=label,
                        section_title=block.section_title,
                        words=block.words,
                        quality_score=self._quality_score(self._equation_text(block.text, label), self._local_context(blocks, index)),
                    )
                )
        return candidates

    def _is_reference_block(self, block: ExtractedBlock) -> bool:
        return self._structure.is_reference_section(block.section_title) or self._structure.is_reference_entry(block.text)

    def anchor_words(self, page_blocks: list[ExtractedBlock], candidate: EquationCandidate) -> list[ExtractedWord]:
        if candidate.equation_label:
            label_words = self._label_anchor_words(page_blocks, candidate)
            if label_words:
                return label_words
        return self._minimal_anchor_words(candidate.words)

    def _grouped_row_candidates(self, blocks: list[ExtractedBlock]) -> list[EquationCandidate]:
        candidates: list[EquationCandidate] = []
        rows = self._row_groups(blocks)
        for row in rows:
            if len(row) < 3:
                continue
            if any(block.word_count > 5 for block in row):
                continue
            text = clean_text(" ".join(block.text for block in row))
            if not text or len(text) > 120:
                continue
            if text.count("=") + text.count("+") + text.count("-") < 1:
                continue
            label = None
            if _INLINE_LABEL_RE.search(text):
                label = f"({_INLINE_LABEL_RE.search(text).group(1)})"
            equation_text = self._equation_text(text, label)
            if len(equation_text.split()) < 3:
                continue
            anchor = row[0]
            candidates.append(
                EquationCandidate(
                    equation_id=f"{anchor.block_id}-eqrow",
                    block_id=anchor.block_id,
                    page_number=anchor.page_number,
                    equation_text_clean=equation_text,
                    local_context=self._row_context(blocks, row),
                    symbol_context=self._row_symbol_context(blocks, row),
                    source_kind="equation",
                    equation_label=label,
                    section_title=anchor.section_title,
                    words=[word for block in row for word in block.words],
                    quality_score=self._quality_score(equation_text, self._row_context(blocks, row)),
                )
            )
        return candidates

    def _row_groups(self, blocks: list[ExtractedBlock]) -> list[list[ExtractedBlock]]:
        rows: list[list[ExtractedBlock]] = []
        current: list[ExtractedBlock] = []
        current_mid: float | None = None
        for block in sorted(blocks, key=lambda item: ((item.bbox[1] + item.bbox[3]) / 2.0, item.bbox[0])):
            mid = (block.bbox[1] + block.bbox[3]) / 2.0
            if current and current_mid is not None and abs(mid - current_mid) > 9.0:
                rows.append(sorted(current, key=lambda item: item.bbox[0]))
                current = []
            current.append(block)
            current_mid = mid if current_mid is None else ((current_mid * (len(current) - 1)) + mid) / len(current)
        if current:
            rows.append(sorted(current, key=lambda item: item.bbox[0]))
        return rows

    def _row_context(self, blocks: list[ExtractedBlock], row: list[ExtractedBlock]) -> str:
        first = row[0]
        try:
            index = next(i for i, block in enumerate(blocks) if block.block_id == first.block_id)
        except StopIteration:
            return clean_text(" ".join(block.text for block in row))
        return self._local_context(blocks, index)

    def _row_symbol_context(self, blocks: list[ExtractedBlock], row: list[ExtractedBlock]) -> str:
        first = row[0]
        try:
            index = next(i for i, block in enumerate(blocks) if block.block_id == first.block_id)
        except StopIteration:
            return ""
        return self._symbol_context(blocks, index)

    def _equation_text(self, text: str, equation_label: str | None) -> str:
        cleaned = clean_text(text)
        if equation_label and cleaned.endswith(equation_label):
            cleaned = cleaned[: -len(equation_label)].rstrip()
        return cleaned

    def _looks_like_equation(self, block: ExtractedBlock, page_width: float) -> bool:
        text = clean_text(block.text)
        if not text or len(text) > 220:
            return False
        line_count = len({word.line_number for word in block.words})
        if line_count > 5:
            return False
        math_char_count = sum(text.count(symbol) for symbol in "=+-/*^_[](){}<>|")
        alpha_count = sum(ch.isalpha() for ch in text)
        digit_count = sum(ch.isdigit() for ch in text)
        center_x = (block.bbox[0] + block.bbox[2]) / 2.0
        centered = abs(center_x - (page_width / 2.0)) <= page_width * 0.18
        width_ratio = (block.bbox[2] - block.bbox[0]) / max(page_width, 1.0)
        has_math_words = bool(_MATH_WORD_RE.search(text))
        has_inline_label = bool(_INLINE_LABEL_RE.search(text))
        punctuation_end = text.endswith(".")
        if punctuation_end and math_char_count < 3 and not has_math_words:
            return False
        if has_inline_label and math_char_count >= 1:
            return True
        if has_math_words and (math_char_count >= 2 or centered):
            return True
        if math_char_count >= 4 and centered and width_ratio <= 0.75:
            return True
        if math_char_count >= 6 and digit_count >= 1 and alpha_count <= max(18, len(text) // 2):
            return True
        return False

    def _equation_label(self, block: ExtractedBlock, blocks: list[ExtractedBlock], index: int) -> str | None:
        inline = _INLINE_LABEL_RE.search(block.text)
        if inline:
            return f"({inline.group(1)})"
        for neighbor in self._same_row_neighbors(blocks, index):
            label = clean_text(neighbor.text)
            if _EQUATION_LABEL_RE.fullmatch(label):
                if label.startswith("("):
                    return label
                return f"({label})"
        return None

    def _same_row_neighbors(self, blocks: list[ExtractedBlock], index: int) -> list[ExtractedBlock]:
        target = blocks[index]
        neighbors: list[ExtractedBlock] = []
        target_mid = (target.bbox[1] + target.bbox[3]) / 2.0
        for offset in (-1, 1):
            candidate_index = index + offset
            if candidate_index < 0 or candidate_index >= len(blocks):
                continue
            candidate = blocks[candidate_index]
            candidate_mid = (candidate.bbox[1] + candidate.bbox[3]) / 2.0
            if abs(target_mid - candidate_mid) <= 10.0:
                neighbors.append(candidate)
        return neighbors

    def _local_context(self, blocks: list[ExtractedBlock], index: int) -> str:
        context_parts: list[str] = []
        for candidate in blocks[max(0, index - 2) : min(len(blocks), index + 3)]:
            if candidate.is_heading:
                if candidate.block_id != blocks[index].block_id:
                    continue
            if candidate.block_id == blocks[index].block_id or not _CAPTION_RE.match(clean_text(candidate.text)):
                context_parts.append(clean_text(candidate.text))
        return " ".join(context_parts)[:1500]

    def _symbol_context(self, blocks: list[ExtractedBlock], index: int) -> str:
        snippets: list[str] = []
        for candidate in blocks[max(0, index - 2) : min(len(blocks), index + 4)]:
            if candidate.is_heading:
                continue
            text = clean_text(candidate.text)
            if _GROUNDING_HINT_RE.search(text):
                snippets.append(text)
        return " ".join(snippets)[:1000]

    def _source_kind(self, blocks: list[ExtractedBlock], index: int) -> str:
        for candidate in blocks[max(0, index - 2) : min(len(blocks), index + 2)]:
            if _CAPTION_RE.match(clean_text(candidate.text)):
                return "caption-linked"
        return "equation"

    def _label_anchor_words(self, page_blocks: list[ExtractedBlock], candidate: EquationCandidate) -> list[ExtractedWord]:
        label = candidate.equation_label
        if not label:
            return []
        direct = self._matching_label_span(candidate.words, label)
        if direct:
            return direct
        try:
            index = next(i for i, block in enumerate(page_blocks) if block.block_id == candidate.block_id)
        except StopIteration:
            return []
        for neighbor in self._same_row_neighbors(page_blocks, index):
            if self._normalized_label(neighbor.text) != self._normalized_label(label):
                continue
            direct = self._matching_label_span(neighbor.words, label)
            if direct:
                return direct
            if neighbor.words:
                return sorted(neighbor.words, key=lambda item: (item.bbox[1], item.bbox[0]))
        return []

    def _matching_label_span(self, words: list[ExtractedWord], label: str) -> list[ExtractedWord]:
        if not words:
            return []
        ordered = sorted(words, key=lambda item: (round(item.bbox[1], 1), item.bbox[0]))
        target = self._normalized_label(label)
        for start in range(len(ordered)):
            combined = ""
            span: list[ExtractedWord] = []
            for word in ordered[start : min(len(ordered), start + 3)]:
                span.append(word)
                combined += self._normalized_label(word.text)
                if combined == target:
                    return span
                if not target.startswith(combined):
                    break
        return []

    def _minimal_anchor_words(self, words: list[ExtractedWord]) -> list[ExtractedWord]:
        if not words:
            return []
        ordered = sorted(words, key=lambda item: (round(item.bbox[1], 1), item.bbox[0]))
        tail = ordered[-1]
        line_words = [
            word
            for word in ordered
            if abs(((word.bbox[1] + word.bbox[3]) / 2.0) - ((tail.bbox[1] + tail.bbox[3]) / 2.0)) <= 2.8
        ]
        line_words = sorted(line_words, key=lambda item: item.bbox[0])
        return line_words[-min(2, len(line_words)) :]

    def _normalized_label(self, text: str) -> str:
        return re.sub(r"\s+", "", clean_text(text))

    def _quality_score(self, equation_text: str, local_context: str) -> float:
        tokens = equation_text.split()
        if not tokens:
            return 0.0
        long_alpha_tokens = sum(1 for token in tokens if len(token) >= 3 and any(ch.isalpha() for ch in token))
        single_char_tokens = sum(1 for token in tokens if len(token) == 1 and token.isalpha())
        placeholder_hits = equation_text.count("( )")
        score = 0.0
        if "=" in equation_text:
            score += 0.35
        if _GROUNDING_HINT_RE.search(local_context) or "equations" in local_context.lower() or "equation" in local_context.lower():
            score += 0.35
        score += min(0.25, long_alpha_tokens * 0.04)
        score -= min(0.3, placeholder_hits * 0.1)
        if single_char_tokens / max(len(tokens), 1) > 0.55:
            score -= 0.15
        return max(0.0, min(score, 1.0))
