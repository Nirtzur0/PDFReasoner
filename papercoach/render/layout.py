from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil

@dataclass(slots=True)
class MarginNote:
    note_id: str
    title: str
    body: str
    priority: int = 1
    equation_latex: str | None = None
    symbol_rows: list[tuple[str, str]] = field(default_factory=list)


@dataclass(slots=True)
class AnchoredNote:
    note: MarginNote
    anchor_y: float
    quads: list


@dataclass(slots=True)
class NotePlacement:
    note: MarginNote
    bbox: tuple[float, float, float, float]


def estimate_note_height(note: MarginNote, width: float) -> float:
    title_chars_per_line = max(18, int(width / 7.5))
    body_chars_per_line = max(20, int(width / 5.7))
    title_lines = max(1, ceil(len(note.title) / title_chars_per_line))
    body_lines = max(3, ceil(len(note.body) / body_chars_per_line) + 1)
    equation_height = 34 if note.equation_latex else 0
    symbol_height = len(note.symbol_rows[:2]) * 18
    return 22 + title_lines * 14 + equation_height + symbol_height + body_lines * 12


def place_notes(
    notes: list[AnchoredNote],
    page_height: float,
    margin_x0: float,
    margin_x1: float,
    max_notes: int,
) -> list[NotePlacement]:
    placements: list[NotePlacement] = []
    notes = sorted(notes, key=lambda item: (item.anchor_y, item.note.priority, item.note.note_id))[:max_notes]
    top_margin = 24.0
    bottom_margin = 24.0
    gutter = 12.0
    cursor_y = top_margin
    page_bottom = page_height - bottom_margin

    for anchored_note in notes:
        height = estimate_note_height(anchored_note.note, margin_x1 - margin_x0)
        desired_y = max(top_margin, min(anchored_note.anchor_y - (height / 2.0), page_bottom - height))
        y0 = max(cursor_y, desired_y)
        if placements and y0 < placements[-1].bbox[3] + gutter:
            y0 = placements[-1].bbox[3] + gutter
        placements.append(NotePlacement(note=anchored_note.note, bbox=(margin_x0, y0, margin_x1, y0 + height)))
        cursor_y = y0 + height + gutter
    return _shift_placements_to_fit(placements, top_margin, page_bottom, gutter)


def _shift_placements_to_fit(
    placements: list[NotePlacement],
    top_margin: float,
    page_bottom: float,
    gutter: float,
) -> list[NotePlacement]:
    if not placements:
        return placements

    overflow = placements[-1].bbox[3] - page_bottom
    if overflow <= 0:
        return placements

    shifted = [
        NotePlacement(
            note=placement.note,
            bbox=(
                placement.bbox[0],
                placement.bbox[1] - overflow,
                placement.bbox[2],
                placement.bbox[3] - overflow,
            ),
        )
        for placement in placements
    ]
    if shifted[0].bbox[1] >= top_margin:
        return shifted

    packed: list[NotePlacement] = []
    cursor_y = top_margin
    for placement in shifted:
        height = placement.bbox[3] - placement.bbox[1]
        if cursor_y + height > page_bottom:
            break
        packed.append(
            NotePlacement(
                note=placement.note,
                bbox=(placement.bbox[0], cursor_y, placement.bbox[2], cursor_y + height),
            )
        )
        cursor_y += height + gutter
    return packed
