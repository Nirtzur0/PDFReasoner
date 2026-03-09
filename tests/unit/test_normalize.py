from __future__ import annotations

from papercoach.extract.normalize import repair_extracted_text


def test_repair_extracted_text_merges_common_pdf_word_fragments() -> None:
    repaired = repair_extracted_text("w e com bine the state v ariable and mo del parameters in to one estimate")

    assert repaired == "we com bine the state variable and model parameters into one estimate"


def test_repair_extracted_text_keeps_real_word_boundaries() -> None:
    repaired = repair_extracted_text("factor analysis is used with output noise")

    assert repaired == "factor analysis is used with output noise"
