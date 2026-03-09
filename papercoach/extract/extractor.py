"""Extraction pipeline based on PyMuPDF text and word recipes.

Sources:
- https://pymupdf.readthedocs.io/en/latest/recipes-text.html
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
from pathlib import Path

import fitz

from papercoach.extract.normalize import clean_text, normalize_token, repair_extracted_text
from papercoach.extract.structure import StructureDetector


@dataclass(slots=True)
class ExtractedWord:
    page_number: int
    block_id: str
    line_number: int
    word_number: int
    text: str
    normalized: str
    bbox: tuple[float, float, float, float]


@dataclass(slots=True)
class ExtractedBlock:
    page_number: int
    block_id: str
    bbox: tuple[float, float, float, float]
    text: str
    avg_font_size: float
    is_heading: bool
    section_title: str | None
    words: list[ExtractedWord] = field(default_factory=list)

    @property
    def word_count(self) -> int:
        return len([word for word in self.words if word.normalized])


@dataclass(slots=True)
class ExtractedPage:
    page_number: int
    width: float
    height: float
    is_reference_page: bool
    blocks: list[ExtractedBlock]


@dataclass(slots=True)
class ExtractedDocument:
    paper_id: str
    title: str
    input_pdf: Path
    pages: list[ExtractedPage]


class PdfExtractor:
    def __init__(self) -> None:
        self._structure = StructureDetector()

    def extract(self, pdf_path: Path) -> ExtractedDocument:
        with fitz.open(pdf_path) as document:
            paper_id = self._hash_pdf(pdf_path)
            title = self._resolve_title(document, pdf_path)
            pages = [self._extract_page(page) for page in document]
        self._assign_section_titles(pages)
        return ExtractedDocument(paper_id=paper_id, title=title, input_pdf=pdf_path, pages=pages)

    def _extract_page(self, page: fitz.Page) -> ExtractedPage:
        raw_blocks = page.get_text("dict", sort=True)["blocks"]
        raw_words = page.get_text("words", sort=True)
        words_by_block: dict[int, list[tuple]] = {}
        for word in raw_words:
            words_by_block.setdefault(int(word[5]), []).append(word)

        font_sizes = []
        for raw_block in raw_blocks:
            if raw_block.get("type") != 0:
                continue
            for line in raw_block.get("lines", []):
                for span in line.get("spans", []):
                    size = float(span.get("size", 0.0))
                    if size > 0:
                        font_sizes.append(size)
        baseline_font_size = sorted(font_sizes)[len(font_sizes) // 2] if font_sizes else 10.0
        block_heights = [
            float(raw_block["bbox"][3]) - float(raw_block["bbox"][1])
            for raw_block in raw_blocks
            if raw_block.get("type") == 0
        ]
        baseline_block_height = sorted(block_heights)[len(block_heights) // 2] if block_heights else 12.0

        blocks: list[ExtractedBlock] = []
        for block_number, raw_block in enumerate(raw_blocks):
            if raw_block.get("type") != 0:
                continue
            block_number = int(raw_block.get("number", block_number))
            block_words = self._resolve_block_words(page, raw_block, words_by_block.get(block_number, []))
            text = self._resolve_block_text(raw_block, block_words)
            if not text:
                continue
            avg_font_size = self._average_font_size(raw_block)
            block_height = float(raw_block["bbox"][3]) - float(raw_block["bbox"][1])
            is_heading = self._structure.is_heading(text, avg_font_size, baseline_font_size, block_height, baseline_block_height)
            block_id = f"p{page.number + 1}-b{block_number}"
            words = [
                ExtractedWord(
                    page_number=page.number + 1,
                    block_id=block_id,
                    line_number=int(word[6]),
                    word_number=int(word[7]),
                    text=str(word[4]),
                    normalized=normalize_token(str(word[4])),
                    bbox=(float(word[0]), float(word[1]), float(word[2]), float(word[3])),
                )
                for word in block_words
            ]
            blocks.append(
                ExtractedBlock(
                    page_number=page.number + 1,
                    block_id=block_id,
                    bbox=tuple(float(value) for value in raw_block["bbox"]),
                    text=text,
                    avg_font_size=avg_font_size,
                    is_heading=is_heading,
                    section_title=None,
                    words=words,
                )
            )

        reference_page = self._structure.is_reference_page([block.text for block in blocks])
        return ExtractedPage(
            page_number=page.number + 1,
            width=float(page.rect.width),
            height=float(page.rect.height),
            is_reference_page=reference_page,
            blocks=blocks,
        )

    def _resolve_block_words(self, page: fitz.Page, raw_block: dict, block_words: list[tuple]) -> list[tuple]:
        if block_words and self._words_match_block_bbox(block_words, tuple(float(value) for value in raw_block["bbox"])):
            return block_words
        return page.get_text("words", clip=fitz.Rect(raw_block["bbox"]), sort=True)

    def _words_match_block_bbox(self, words: list[tuple], bbox: tuple[float, float, float, float]) -> bool:
        if not words:
            return False
        x0, y0, x1, y1 = bbox
        tolerance = 2.0
        inside = 0
        for word in words:
            center_x = (float(word[0]) + float(word[2])) / 2.0
            center_y = (float(word[1]) + float(word[3])) / 2.0
            if (x0 - tolerance) <= center_x <= (x1 + tolerance) and (y0 - tolerance) <= center_y <= (y1 + tolerance):
                inside += 1
        return (inside / len(words)) >= 0.8

    def _assign_section_titles(self, pages: list[ExtractedPage]) -> None:
        current_section: str | None = None
        for page in pages:
            for block in page.blocks:
                if block.is_heading:
                    current_section = block.text
                    block.section_title = block.text
                else:
                    inline_section = self._structure.leading_section_title(block.text)
                    if inline_section:
                        current_section = inline_section
                    block.section_title = current_section

    def _average_font_size(self, raw_block: dict) -> float:
        sizes = []
        for line in raw_block.get("lines", []):
            for span in line.get("spans", []):
                size = float(span.get("size", 0.0))
                if size > 0:
                    sizes.append(size)
        return sum(sizes) / len(sizes) if sizes else 10.0

    def _resolve_block_text(self, raw_block: dict, block_words: list[tuple]) -> str:
        word_text = repair_extracted_text(" ".join(str(word[4]) for word in block_words))
        span_lines: list[str] = []
        for line in raw_block.get("lines", []):
            line_text = "".join(str(span.get("text", "")) for span in line.get("spans", []))
            if clean_text(line_text):
                span_lines.append(line_text)
        span_text = repair_extracted_text(" ".join(span_lines))
        candidates = [candidate for candidate in (span_text, word_text) if candidate]
        if not candidates:
            return ""
        return min(candidates, key=self._fragmentation_score)

    def _fragmentation_score(self, text: str) -> tuple[int, int]:
        alpha_tokens = [token for token in clean_text(text).split(" ") if token.isalpha()]
        singletons = sum(1 for token in alpha_tokens if len(token) == 1)
        short_tokens = sum(1 for token in alpha_tokens if len(token) <= 2)
        return (singletons * 2 + short_tokens, -sum(len(token) for token in alpha_tokens))

    def _resolve_title(self, document: fitz.Document, pdf_path: Path) -> str:
        meta_title = clean_text(document.metadata.get("title") or "")
        if meta_title:
            return meta_title
        first_page = self._extract_page(document[0])
        if first_page.blocks:
            return first_page.blocks[0].text[:160]
        return pdf_path.stem

    def _hash_pdf(self, pdf_path: Path) -> str:
        digest = hashlib.sha256()
        with pdf_path.open("rb") as handle:
            while chunk := handle.read(65536):
                digest.update(chunk)
        return digest.hexdigest()
