from __future__ import annotations

import re

from papercoach.models import EvidenceRef, GlossaryItem, TextBlock

SYMBOL_RE = re.compile(
    r"(\\mathbb\{[A-Za-z]\}|\\[A-Za-z]+|[α-ωΑ-Ω]|[A-Za-z](?:_[A-Za-z0-9]+)?|\|\|[A-Za-z]+\|\||λ|μ|σ|π|θ)",
)
MEANING_PATTERNS = [
    re.compile(r"where\s+(?P<sym>\S+)\s+denotes\s+(?P<meaning>[^.,;]+)", re.IGNORECASE),
    re.compile(r"let\s+(?P<sym>\S+)\s+be\s+(?P<meaning>[^.,;]+)", re.IGNORECASE),
    re.compile(r"(?P<sym>\S+)\s+is\s+defined\s+as\s+(?P<meaning>[^.,;]+)", re.IGNORECASE),
]


def extract_glossary(blocks: list[TextBlock], max_items: int = 50) -> list[GlossaryItem]:
    by_symbol: dict[str, GlossaryItem] = {}

    for idx, block in enumerate(blocks):
        text = block.text
        symbols = [s for s in SYMBOL_RE.findall(text) if s.strip()]
        if not symbols:
            continue
        nearby = " ".join(b.text for b in blocks[max(0, idx - 1): min(len(blocks), idx + 2)])

        for symbol in symbols:
            if symbol in by_symbol:
                continue
            meaning = None
            confidence = 0.2
            evidence: list[EvidenceRef] = [
                EvidenceRef(
                    type="paper",
                    pointer={"page": block.page, "block_id": block.block_id},
                    quote=block.text[:220],
                )
            ]

            for pattern in MEANING_PATTERNS:
                m = pattern.search(nearby)
                if m and m.group("sym").strip("$,.:;") == symbol.strip("$,.:;"):
                    meaning = m.group("meaning").strip()
                    confidence = 0.9
                    break

            if meaning is None and symbol in text:
                confidence = 0.45

            by_symbol[symbol] = GlossaryItem(
                symbol=symbol,
                meaning=meaning,
                first_occurrence_page=block.page,
                first_occurrence_bbox=block.bbox,
                confidence=confidence,
                evidence=evidence,
            )
            if len(by_symbol) >= max_items:
                return list(by_symbol.values())

    return list(by_symbol.values())
