from __future__ import annotations

from papercoach.extract.align import SpanAligner
from papercoach.extract.extractor import ExtractedBlock, ExtractedWord


def _word(line_number: int, word_number: int, text: str, x0: float) -> ExtractedWord:
    y0 = 10.0 + (line_number * 12.0)
    y1 = y0 + 10.0
    return ExtractedWord(
        page_number=1,
        block_id="p1-b1",
        line_number=line_number,
        word_number=word_number,
        text=text,
        normalized=text.lower(),
        bbox=(x0, y0, x0 + 10.0, y1),
    )


def test_span_aligner_matches_unique_quote() -> None:
    block = ExtractedBlock(
        page_number=1,
        block_id="p1-b1",
        bbox=(0.0, 0.0, 100.0, 20.0),
        text="This system aligns a contiguous quote back to the PDF words.",
        avg_font_size=11.0,
        is_heading=False,
        section_title="Method",
        words=[
            _word(0, 0, "This", 0.0),
            _word(0, 1, "system", 11.0),
            _word(0, 2, "aligns", 22.0),
            _word(0, 3, "a", 33.0),
            _word(0, 4, "contiguous", 44.0),
            _word(0, 5, "quote", 55.0),
            _word(0, 6, "back", 66.0),
            _word(0, 7, "to", 77.0),
            _word(0, 8, "the", 88.0),
            _word(0, 9, "PDF", 99.0),
            _word(0, 10, "words", 110.0),
        ],
    )

    result = SpanAligner().align_quote(block, "aligns a contiguous quote back to the PDF words")

    assert result is not None
    assert result.matched_text == "This system aligns a contiguous quote back to the PDF words"
    assert len(result.quads) == 1


def test_span_aligner_rejects_ambiguous_quote() -> None:
    words = [
        _word(0, 0, "result", 0.0),
        _word(0, 1, "claim", 11.0),
        _word(0, 2, "result", 22.0),
        _word(0, 3, "claim", 33.0),
    ]
    block = ExtractedBlock(
        page_number=1,
        block_id="p1-b1",
        bbox=(0.0, 0.0, 100.0, 20.0),
        text="result claim result claim",
        avg_font_size=11.0,
        is_heading=False,
        section_title=None,
        words=words,
    )

    assert SpanAligner().align_quote(block, "result claim") is None


def test_span_aligner_expands_quote_to_full_sentence_across_neighbor_words() -> None:
    words = [
        _word(0, 0, "Only", 0.0),
        _word(0, 1, "the", 11.0),
        _word(0, 2, "output", 22.0),
        _word(0, 3, "of", 33.0),
        _word(0, 4, "the", 44.0),
        _word(0, 5, "system", 55.0),
        _word(0, 6, "is", 66.0),
        _word(0, 7, "observed,", 77.0),
        _word(0, 8, "the", 88.0),
        _word(0, 9, "state", 99.0),
        _word(0, 10, "and", 110.0),
        _word(0, 11, "all", 121.0),
        _word(0, 12, "the", 132.0),
        _word(0, 13, "noise", 143.0),
        _word(1, 0, "variables", 0.0),
        _word(1, 1, "are", 11.0),
        _word(1, 2, "hidden.", 22.0),
    ]

    result = SpanAligner().align_quote_in_words(words, "Only the output of the system is observed")

    assert result is not None
    assert result.matched_text == "Only the output of the system is observed, the state and all the noise variables are hidden."
    assert len(result.quads) == 2


def test_span_aligner_matches_repaired_quote_against_fragmented_words() -> None:
    words = [
        _word(0, 0, "Linear", 0.0),
        _word(0, 1, "time-in", 11.0),
        _word(0, 2, "v", 22.0),
        _word(0, 3, "arian", 33.0),
        _word(0, 4, "t", 44.0),
        _word(0, 5, "dynamical", 55.0),
        _word(0, 6, "systems,", 66.0),
        _word(0, 7, "also", 77.0),
        _word(0, 8, "kno", 88.0),
        _word(0, 9, "wn", 99.0),
        _word(0, 10, "as", 110.0),
        _word(0, 11, "linear", 121.0),
        _word(0, 12, "Gaussian", 132.0),
        _word(0, 13, "state-space", 143.0),
        _word(0, 14, "mo", 154.0),
        _word(0, 15, "dels,", 165.0),
    ]

    result = SpanAligner().align_quote_in_words(
        words,
        "Linear time-in variant dynamical systems, also known as linear Gaussian state-space models",
    )

    assert result is not None
    assert "Linear time-in v arian t dynamical systems, also kno wn as linear Gaussian state-space mo dels" in result.matched_text


def test_span_aligner_matches_notation_when_spacing_differs() -> None:
    words = [
        _word(0, 0, "We", 0.0),
        _word(0, 1, "denote", 11.0),
        _word(0, 2, "x", 22.0),
        _word(0, 3, "∈Rd", 33.0),
        _word(0, 4, "and", 44.0),
        _word(0, 5, "approximate", 55.0),
        _word(0, 6, "L(f,", 66.0),
        _word(0, 7, "g,", 77.0),
        _word(0, 8, "πx)", 88.0),
        _word(0, 9, "locally.", 99.0),
    ]

    result = SpanAligner().align_quote_in_words(
        words,
        "We denote x∈Rd and approximate L(f, g,πx) locally.",
    )

    assert result is not None
    assert "approximate L(f, g, πx) locally." in result.matched_text


def test_span_aligner_does_not_expand_incomplete_phrase_into_next_capitalized_block() -> None:
    words = [
        ExtractedWord(1, "p1-b1", 0, 0, "These", "these", (0, 0, 10, 10)),
        ExtractedWord(1, "p1-b1", 0, 1, "posterior", "posterior", (11, 0, 21, 10)),
        ExtractedWord(1, "p1-b1", 0, 2, "probabilities", "probabilities", (22, 0, 32, 10)),
        ExtractedWord(1, "p1-b1", 0, 3, "form", "form", (33, 0, 43, 10)),
        ExtractedWord(1, "p1-b1", 0, 4, "the", "the", (44, 0, 54, 10)),
        ExtractedWord(1, "p1-b1", 0, 5, "basis", "basis", (55, 0, 65, 10)),
        ExtractedWord(1, "p1-b1", 0, 6, "of", "of", (66, 0, 76, 10)),
        ExtractedWord(1, "p1-b1", 0, 7, "the", "the", (77, 0, 87, 10)),
        ExtractedWord(1, "p1-b1", 0, 8, "E", "e", (88, 0, 92, 10)),
        ExtractedWord(1, "p1-b1", 0, 9, "step", "step", (93, 0, 103, 10)),
        ExtractedWord(1, "p1-b1", 0, 10, "of", "of", (104, 0, 114, 10)),
        ExtractedWord(1, "p1-b1", 0, 11, "the", "the", (115, 0, 125, 10)),
        ExtractedWord(1, "p1-b2", 1, 0, "Finally", "finally", (0, 12, 10, 22)),
        ExtractedWord(1, "p1-b2", 1, 1, "we", "we", (11, 12, 21, 22)),
        ExtractedWord(1, "p1-b2", 1, 2, "continue.", "continue", (22, 12, 32, 22)),
    ]

    result = SpanAligner().align_quote_in_words(
        words,
        "These posterior probabilities form the basis of the E step of the",
    )

    assert result is not None
    assert result.matched_text == "These posterior probabilities form the basis of the E step of the"


def test_span_aligner_trims_leading_citation_debris_before_sentence() -> None:
    words = [
        ExtractedWord(1, "p1-b1", 0, 0, ";", "", (0, 0, 2, 10)),
        ExtractedWord(1, "p1-b1", 0, 1, "A", "a", (3, 0, 8, 10)),
        ExtractedWord(1, "p1-b1", 0, 2, "thaide,", "thaide", (9, 0, 19, 10)),
        ExtractedWord(1, "p1-b1", 0, 3, ").", "", (20, 0, 24, 10)),
        ExtractedWord(1, "p1-b1", 0, 4, "Here", "here", (25, 0, 35, 10)),
        ExtractedWord(1, "p1-b1", 0, 5, "w", "w", (36, 0, 40, 10)),
        ExtractedWord(1, "p1-b1", 0, 6, "e", "e", (41, 0, 45, 10)),
        ExtractedWord(1, "p1-b1", 0, 7, "presen", "presen", (46, 0, 56, 10)),
        ExtractedWord(1, "p1-b1", 0, 8, "t", "t", (57, 0, 61, 10)),
        ExtractedWord(1, "p1-b1", 0, 9, "a", "a", (62, 0, 66, 10)),
        ExtractedWord(1, "p1-b1", 0, 10, "basic", "basic", (67, 0, 77, 10)),
        ExtractedWord(1, "p1-b1", 0, 11, "form", "form", (78, 0, 88, 10)),
        ExtractedWord(1, "p1-b1", 0, 12, "of", "of", (89, 0, 99, 10)),
        ExtractedWord(1, "p1-b1", 0, 13, "the", "the", (100, 0, 110, 10)),
        ExtractedWord(1, "p1-b1", 0, 14, "EM", "em", (111, 0, 121, 10)),
        ExtractedWord(1, "p1-b1", 0, 15, "algorithm", "algorithm", (122, 0, 132, 10)),
        ExtractedWord(1, "p1-b1", 0, 16, "with", "with", (133, 0, 143, 10)),
        ExtractedWord(1, "p1-b1", 0, 17, "C", "c", (144, 0, 154, 10)),
        ExtractedWord(1, "p1-b1", 0, 18, "unkno", "unkno", (155, 0, 165, 10)),
        ExtractedWord(1, "p1-b1", 0, 19, "wn,", "wn", (166, 0, 176, 10)),
    ]

    result = SpanAligner().align_quote_in_words(
        words,
        "Here we presen t a basic form of the EM algorithm with C unkno wn,",
    )

    assert result is not None
    assert result.matched_text.startswith("Here w e presen t a basic form of the EM algorithm")


def test_span_aligner_does_not_expand_into_next_inline_numbered_heading_block() -> None:
    aligner = SpanAligner()
    words = [
        _word(0, 0, "Then,", 0.0),
        _word(0, 1, "we", 12.0),
        _word(0, 2, "select", 24.0),
        _word(0, 3, "the", 36.0),
        _word(0, 4, "classifier", 48.0),
        _word(0, 5, "with", 60.0),
        ExtractedWord(1, "p1-b2", 1, 0, "6.2", "6.2", (0, 12, 12, 22)),
        ExtractedWord(1, "p1-b2", 1, 1, "Can", "can", (14, 12, 28, 22)),
        ExtractedWord(1, "p1-b2", 1, 2, "users", "users", (30, 12, 46, 22)),
    ]

    result = aligner.align_quote_in_words(words, "we select the classifier with")

    assert result is not None
    assert result.matched_text == "Then, we select the classifier with"
