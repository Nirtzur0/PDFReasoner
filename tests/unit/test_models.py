from __future__ import annotations

import pytest

from papercoach.models import EvidenceRef, MarginNote


def test_note_confidence_guardrail_rejects_high_confidence_without_evidence() -> None:
    with pytest.raises(ValueError):
        MarginNote(
            page=0,
            anchor_bbox=[0, 0, 10, 10],
            title="t",
            body="b",
            confidence=0.9,
            evidence=[],
            uncertainties=["u"],
            flags=[],
            key_points=[],
        )


def test_note_confidence_with_evidence_is_valid() -> None:
    note = MarginNote(
        page=0,
        anchor_bbox=[0, 0, 10, 10],
        title="t",
        body="b",
        confidence=0.8,
        evidence=[EvidenceRef(type="paper", pointer={"p": 0}, quote="q")],
        uncertainties=[],
        flags=[],
        key_points=[],
    )
    assert note.confidence == 0.8
