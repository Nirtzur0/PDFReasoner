from __future__ import annotations

import re
from dataclasses import dataclass

from papercoach.models import TextBlock


SECTION_HINTS = {
    "abstract",
    "introduction",
    "related work",
    "background",
    "methods",
    "method",
    "experiments",
    "results",
    "discussion",
    "conclusion",
    "references",
}


@dataclass(slots=True)
class Section:
    title: str
    page: int
    block_id: str


def detect_sections(blocks: list[TextBlock]) -> list[Section]:
    if not blocks:
        return []

    sizes = [float(b.font_meta.get("avg_size", 0.0)) for b in blocks if b.text.strip()]
    baseline = sorted(sizes)[len(sizes) // 2] if sizes else 10.0

    sections: list[Section] = []
    for b in blocks:
        txt = b.text.strip()
        txt_lower = txt.lower()
        avg_size = float(b.font_meta.get("avg_size", 0.0))
        numbered = bool(re.match(r"^\d+(\.\d+)*\s+", txt))
        short = len(txt) < 120
        likely_heading = short and (numbered or avg_size >= baseline * 1.15 or bool(b.font_meta.get("bold")))
        if likely_heading or txt_lower in SECTION_HINTS:
            sections.append(Section(title=txt, page=b.page, block_id=b.block_id))

    if not any(s.title.lower() == "abstract" for s in sections):
        first = blocks[0]
        sections.insert(0, Section(title="Abstract", page=first.page, block_id=first.block_id))

    dedup: list[Section] = []
    seen: set[tuple[int, str]] = set()
    for s in sections:
        key = (s.page, s.title.lower())
        if key not in seen:
            seen.add(key)
            dedup.append(s)
    return dedup
