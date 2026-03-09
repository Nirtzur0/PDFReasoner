from __future__ import annotations

from papercoach.render.layout import AnchoredNote, MarginNote, place_notes


def test_place_notes_respects_anchor_order_over_priority() -> None:
    notes = [
        AnchoredNote(
            note=MarginNote(note_id="lower-priority-zero", title="Lower", body="Body", priority=0),
            anchor_y=320.0,
            quads=[],
        ),
        AnchoredNote(
            note=MarginNote(note_id="upper-priority-one", title="Upper", body="Body", priority=1),
            anchor_y=120.0,
            quads=[],
        ),
    ]

    placements = place_notes(notes, page_height=700.0, margin_x0=500.0, margin_x1=720.0, max_notes=2)

    assert [placement.note.note_id for placement in placements] == ["upper-priority-one", "lower-priority-zero"]
