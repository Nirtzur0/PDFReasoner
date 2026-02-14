from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

import fitz

from papercoach.models import SpanRef, TextBlock
from papercoach.analyze.text_clean import clean_extracted_text


@dataclass(slots=True)
class ExtractedDocument:
    blocks: list[TextBlock]
    spans: list[SpanRef]
    page_sizes: dict[int, tuple[float, float]]


def short_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:8]


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def extract_text(pdf_path: Path) -> ExtractedDocument:
    blocks: list[TextBlock] = []
    spans: list[SpanRef] = []
    page_sizes: dict[int, tuple[float, float]] = {}

    with fitz.open(pdf_path) as doc:
        for page_idx, page in enumerate(doc):
            page_sizes[page_idx] = (page.rect.width, page.rect.height)
            raw = page.get_text("dict")
            block_i = 0
            span_i = 0
            for block in raw.get("blocks", []):
                if block.get("type") != 0:
                    continue
                block_text_parts: list[str] = []
                font_sizes: list[float] = []
                is_bold = False
                bbox = list(block.get("bbox", [0.0, 0.0, 0.0, 0.0]))

                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        text = span.get("text", "")
                        if not text.strip():
                            continue
                        clean_span = clean_extracted_text(text)
                        block_text_parts.append(clean_span)
                        size = float(span.get("size", 0.0))
                        font_sizes.append(size)
                        if "bold" in str(span.get("font", "")).lower() or int(span.get("flags", 0)) & 16:
                            is_bold = True

                        spans.append(
                            SpanRef(
                                page=page_idx,
                                block_id="",
                                span_index=span_i,
                                bbox=list(span.get("bbox", bbox)),
                                text=clean_span,
                            )
                        )
                        span_i += 1

                block_text = clean_extracted_text(normalize_ws(" ".join(block_text_parts)))
                if not block_text:
                    continue
                block_id = f"p{page_idx}_b{block_i}_{short_hash(block_text)}"
                font_meta = {
                    "avg_size": (sum(font_sizes) / len(font_sizes)) if font_sizes else 0.0,
                    "bold": is_bold,
                    "span_count": len(font_sizes),
                }
                blocks.append(
                    TextBlock(
                        page=page_idx,
                        block_id=block_id,
                        bbox=bbox,
                        text=block_text,
                        font_meta=font_meta,
                    )
                )

                for i in range(len(spans) - 1, -1, -1):
                    if spans[i].page != page_idx:
                        break
                    if spans[i].block_id:
                        break
                    spans[i].block_id = block_id
                block_i += 1

    return ExtractedDocument(blocks=blocks, spans=spans, page_sizes=page_sizes)
