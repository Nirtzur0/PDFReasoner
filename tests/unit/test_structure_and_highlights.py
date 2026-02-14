from __future__ import annotations

from papercoach.analyze.highlights import detect_highlights
from papercoach.analyze.structure import detect_sections
from papercoach.models import TextBlock


def _blocks() -> list[TextBlock]:
    return [
        TextBlock(page=0, block_id="b0", bbox=[0, 0, 10, 10], text="1 Introduction", font_meta={"avg_size": 14, "bold": True}),
        TextBlock(page=0, block_id="b1", bbox=[0, 12, 10, 24], text="Definition 1. Let x be real", font_meta={"avg_size": 10, "bold": False}),
        TextBlock(page=0, block_id="b2", bbox=[0, 24, 10, 36], text="Proof. Clearly this holds", font_meta={"avg_size": 10, "bold": False}),
        TextBlock(page=0, block_id="b3", bbox=[0, 36, 10, 48], text="L = x^2 + y", font_meta={"avg_size": 10, "bold": False}),
    ]


def test_detect_sections() -> None:
    sections = detect_sections(_blocks())
    assert any("introduction" in s.title.lower() for s in sections)


def test_detect_highlights() -> None:
    highlights, anchors, targets = detect_highlights(_blocks())
    tags = {h.tag for h in highlights}
    assert "theorem_like" in tags
    assert "proof" in tags
    assert "equation" in tags
    assert len(anchors) == len(targets)
