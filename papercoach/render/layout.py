from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from papercoach.models import MarginNote


@dataclass(slots=True)
class NotePlacement:
    note: MarginNote
    bbox: list[float]


def estimate_note_height(note: MarginNote, width: float) -> float:
    text_len = len(note.title) + len(note.body) + sum(len(k) for k in note.key_points)
    chars_per_line = max(24, int(width / 4.3))
    lines = max(5, ceil(text_len / chars_per_line))
    return 24 + lines * 12


def place_notes(
    notes: list[MarginNote],
    page_height: float,
    margin_x0: float,
    margin_x1: float,
    top: float = 20,
    gutter: float = 10,
    max_notes: int = 8,
) -> tuple[list[NotePlacement], list[MarginNote]]:
    placements: list[NotePlacement] = []
    overflow: list[MarginNote] = []

    cursor_y = top
    for idx, note in enumerate(notes):
        if idx >= max_notes:
            overflow.append(note)
            continue
        h = estimate_note_height(note, margin_x1 - margin_x0)
        if cursor_y + h > page_height - 20:
            overflow.append(note)
            continue
        bbox = [margin_x0, cursor_y, margin_x1, cursor_y + h]
        placements.append(NotePlacement(note=note, bbox=bbox))
        cursor_y += h + gutter

    return placements, overflow
