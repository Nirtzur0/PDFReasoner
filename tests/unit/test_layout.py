from __future__ import annotations

from papercoach.models import MarginNote
from papercoach.render.layout import place_notes


def _note(i: int) -> MarginNote:
    return MarginNote(
        page=0,
        anchor_bbox=[0, 0, 1, 1],
        title=f"n{i}",
        body="body " * 40,
        key_points=[],
        evidence=[],
        confidence=0.2,
        uncertainties=["uncertain"],
        flags=[],
    )


def test_place_notes_overflow() -> None:
    notes = [_note(i) for i in range(12)]
    placements, overflow = place_notes(notes, page_height=220, margin_x0=500, margin_x1=700, max_notes=8)
    assert placements
    assert overflow
