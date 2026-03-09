from __future__ import annotations

from pathlib import Path

from papercoach.extract.equations import EquationDetector
from papercoach.extract.extractor import PdfExtractor
from papercoach.extract.normalize import clean_text


def test_equation_detector_finds_centered_display_equation(sample_pdf: Path) -> None:
    document = PdfExtractor().extract(sample_pdf)

    detector = EquationDetector()
    candidates = detector.detect(document)

    assert candidates
    assert any(candidate.equation_text_clean == "z = x + y" for candidate in candidates)
    assert any(candidate.equation_label == "(1)" for candidate in candidates)

    page_blocks = [block for block in document.pages[0].blocks if block.words]
    anchor = next(candidate for candidate in candidates if candidate.equation_text_clean == "z = x + y")
    anchor_words = detector.anchor_words(page_blocks, anchor)

    assert clean_text(" ".join(word.text for word in anchor_words)) == "(1)"
