from __future__ import annotations

import pytest

from papercoach.analyze.commentary import validate_generated_note
from papercoach.analyze.glossary import extract_glossary
from papercoach.models import TextBlock


def test_glossary_confidence_when_denotes_pattern_exists() -> None:
    blocks = [
        TextBlock(page=0, block_id="b0", bbox=[0, 0, 10, 10], text="where x denotes the parameter vector", font_meta={}),
    ]
    glossary = extract_glossary(blocks)
    x_items = [g for g in glossary if g.symbol == "x"]
    assert x_items
    assert x_items[0].confidence >= 0.9


def test_commentary_validator_rejects_unknown_evidence_ids() -> None:
    payload = {
        "title": "t",
        "body": "likely explanation; uncertain",
        "key_points": [],
        "evidence_used": ["e9"],
        "confidence": 0.2,
        "uncertainties": ["u"],
    }
    with pytest.raises(RuntimeError):
        validate_generated_note(payload, {"e0", "e1"})
