from __future__ import annotations

from pathlib import Path

from papercoach.extract.extractor import ExtractedBlock, ExtractedDocument, ExtractedPage, ExtractedWord, PdfExtractor
from papercoach.extract.align import AlignmentResult, SpanAligner
from papercoach.extract.structure import StructureDetector
from papercoach.models import EquationExplanation
from papercoach.models import HighlightSelection, Point, QuadPoints
from papercoach.pipeline import HighlightPlanner


def test_corruption_driven_equation_explanations_are_rejected() -> None:
    planner = HighlightPlanner(None, None, None, None, None)  # type: ignore[arg-type]

    rejected = EquationExplanation(
        equation_id="eq1",
        title="New state dynamics matrix (corrupt)",
        display_latex=r"\text{broken row}",
        symbol_map={"A": "state dynamics matrix"},
        body="The local text fragment is too corrupted to reliably recover the exact algebraic relationship.",
        intuition="The row cannot be reconstructed non-speculatively.",
        confidence=0.2,
    )
    accepted = EquationExplanation(
        equation_id="eq2",
        title="State transition",
        display_latex=r"x_{t+1} = A x_t + w_t",
        symbol_map={"A": "state dynamics matrix"},
        body="This row defines the latent state evolution used by the LDS.",
        intuition="It provides the transition model carried through the rest of the derivation.",
        confidence=0.9,
    )

    assert planner._accept_equation_explanation(rejected, r"x_{t+1} = A x_t + w_t") is False
    assert planner._accept_equation_explanation(accepted, r"x_{t+1} = A x_t + w_t") is True


def test_equation_explanations_must_match_source_equation_symbols() -> None:
    planner = HighlightPlanner(None, None, None, None, None)  # type: ignore[arg-type]

    mismatched = EquationExplanation(
        equation_id="eq3",
        title="State transition",
        display_latex=r"z = x + y",
        symbol_map={"z": "overall score"},
        body="This equation defines the paper's local score as the sum of method and result contributions.",
        intuition="Increasing either component raises the combined score.",
        confidence=0.9,
    )
    grounded = EquationExplanation(
        equation_id="eq4",
        title="State transition",
        display_latex=r"x_{t+1} = A x_t + w_t",
        symbol_map={"A": "state transition matrix"},
        body="This row defines the latent state evolution.",
        intuition="It carries the previous state forward with process noise.",
        confidence=0.9,
    )

    assert planner._accept_equation_explanation(mismatched, r"x_{t+1} = A x_t + w_t") is False
    assert planner._accept_equation_explanation(grounded, r"x_{t+1} = A x_t + w_t") is True


def test_incomplete_fragment_highlights_are_rejected() -> None:
    planner = HighlightPlanner(None, None, None, None, None)  # type: ignore[arg-type]

    rejected = HighlightSelection(
        highlight_id="h1",
        block_id="b1",
        label="method",
        rationale="",
        confidence=0.8,
        source_quote="These posterior probabilities form the basis of the",
        matched_quote="These posterior probabilities form the basis of the",
        quads=[
            QuadPoints(
                ul=Point(x=0, y=0),
                ur=Point(x=10, y=0),
                ll=Point(x=0, y=10),
                lr=Point(x=10, y=10),
            )
        ],
    )
    accepted = HighlightSelection(
        highlight_id="h2",
        block_id="b2",
        label="method",
        rationale="",
        confidence=0.8,
        source_quote="These posterior probabilities form the basis of the E step of the EM algorithm.",
        matched_quote="These posterior probabilities form the basis of the E step of the EM algorithm.",
        quads=[
            QuadPoints(
                ul=Point(x=0, y=0),
                ur=Point(x=10, y=0),
                ll=Point(x=0, y=10),
                lr=Point(x=10, y=10),
            )
        ],
    )

    assert planner._accept_highlight(rejected) is False
    assert planner._accept_highlight(accepted) is True


def test_section_context_falls_back_to_neighboring_blocks_when_structure_is_degenerate() -> None:
    planner = HighlightPlanner(None, None, None, None, None)  # type: ignore[arg-type]
    word = ExtractedWord(
        page_number=1,
        block_id="p1-b1",
        line_number=0,
        word_number=0,
        text="alpha",
        normalized="alpha",
        bbox=(0, 0, 10, 10),
    )
    document = ExtractedDocument(
        paper_id="paper",
        title="Test",
        input_pdf=Path("test.pdf"),
        pages=[
            ExtractedPage(
                page_number=1,
                width=100,
                height=100,
                is_reference_page=False,
                blocks=[
                    ExtractedBlock(1, "p1-b1", (0, 0, 1, 1), "First context block.", 10.0, False, "Abstract", [word]),
                    ExtractedBlock(1, "p1-b2", (0, 0, 1, 1), "Anchor equation context.", 10.0, False, "Abstract", [word]),
                ],
            ),
            ExtractedPage(
                page_number=2,
                width=100,
                height=100,
                is_reference_page=False,
                blocks=[
                    ExtractedBlock(2, "p2-b1", (0, 0, 1, 1), "Next-page technical context.", 10.0, False, "Abstract", [word]),
                ],
            ),
        ],
    )

    context = planner._neighboring_block_context(document, 1, "p1-b2", 500)

    assert planner._has_useful_section_structure(document) is False
    assert "Anchor equation context." in context
    assert "Next-page technical context." in context


def test_highlight_falls_back_to_raw_block_words_when_repaired_quote_will_not_align() -> None:
    planner = HighlightPlanner(None, None, None, SpanAligner(), None)  # type: ignore[arg-type]
    block = ExtractedBlock(
        page_number=1,
        block_id="p1-b1",
        bbox=(0, 0, 100, 20),
        text="Linear time-in variant dynamical systems",
        avg_font_size=10.0,
        is_heading=False,
        section_title="Method",
        words=[
            ExtractedWord(1, "p1-b1", 0, 0, "Linear", "linear", (0, 0, 10, 10)),
            ExtractedWord(1, "p1-b1", 0, 1, "time-in", "time-in", (11, 0, 21, 10)),
            ExtractedWord(1, "p1-b1", 0, 2, "v", "v", (22, 0, 24, 10)),
            ExtractedWord(1, "p1-b1", 0, 3, "arian", "arian", (25, 0, 35, 10)),
            ExtractedWord(1, "p1-b1", 0, 4, "t", "t", (36, 0, 38, 10)),
            ExtractedWord(1, "p1-b1", 0, 5, "dynamical", "dynamical", (39, 0, 49, 10)),
            ExtractedWord(1, "p1-b1", 0, 6, "systems.", "systems", (50, 0, 60, 10)),
        ],
    )

    highlight = planner._to_highlight(
        block,
        "setup",
        {"selected_quote": "Linear time-in variant dynamical systems", "rationale": "", "confidence": 0.9},
        1,
        [block],
    )

    assert highlight is not None
    assert "Linear time-in v arian t dynamical systems" in highlight.matched_quote


def test_highlight_falls_back_to_alternative_block_anchor_when_selected_quote_will_not_align() -> None:
    class FakeAligner:
        def align_quote_in_words(self, _words: list[ExtractedWord], quote: str) -> AlignmentResult | None:
            if "foobar" in quote:
                return None
            if "understandable to humans" in quote:
                return AlignmentResult(
                    matched_text="As mentioned before, interpretable explanations need to use a representation that is understandable to humans, regardless of the actual features used by the model.",
                    quads=[((0.0, 0.0), (100.0, 0.0), (0.0, 10.0), (100.0, 10.0))],
                )
            return None

    class FakeTraceWriter:
        def write(self, _payload: dict) -> None:
            return

    planner = HighlightPlanner(None, None, None, FakeAligner(), FakeTraceWriter())  # type: ignore[arg-type]
    block = ExtractedBlock(
        page_number=1,
        block_id="p3-b2",
        bbox=(0, 0, 100, 40),
        text=(
            "As mentioned before, interpretable explanations need to use a representation that is understandable to humans, "
            "regardless of the actual features used by the model. "
            "We denote x∈Rd be the original representation of an instance being explained, and we usex′ ∈{0, 1}d′ to denote "
            "a binary vector for its interpretable representation."
        ),
        avg_font_size=10.0,
        is_heading=False,
        section_title="Method",
        words=[ExtractedWord(1, "p3-b2", 0, 0, "placeholder", "placeholder", (0, 0, 1, 1))],
    )

    highlight = planner._to_highlight(
        block,
        "definition",
        {
            "selected_quote": "We denote x∈Rd be the original representation of an instance being explained, and we usex′ ∈{0, 1}d′ to denote a binary vector for its interpretable representation foobar.",
            "rationale": "The explainer must operate on a human-understandable representation x′ rather than the model's raw features.",
            "confidence": 0.9,
            "label": "definition",
        },
        1,
        [block],
    )

    assert highlight is not None
    assert "interpretable explanations need to use a representation that is understandable to humans" in highlight.matched_quote


def test_source_block_selection_uses_sentence_scale_anchor() -> None:
    planner = HighlightPlanner(None, None, None, None, None)  # type: ignore[arg-type]
    block = ExtractedBlock(
        page_number=1,
        block_id="p1-b5",
        bbox=(0, 0, 100, 100),
        text=(
            "Despite widespread adoption, machine learning models remain mostly black boxes. "
            "In this work, we propose LIME, a novel explanation technique that explains the predictions "
            "of any classifier in an interpretable and faithful manner, by learning an interpretable model locally around the prediction. "
            "We also propose a method to explain models by presenting representative predictions."
        ),
        avg_font_size=11.0,
        is_heading=False,
        section_title="ABSTRACT",
        words=[],
    )

    quote = planner._best_anchor_quote(
        block,
        {
            "title": "Core contribution",
            "statement": "LIME explains predictions with an interpretable local surrogate.",
            "label": "contribution",
            "block_id": block.block_id,
            "confidence": 0.9,
        },
    )

    assert "explains the predictions of any classifier" in quote
    assert len(quote.split()) < len(block.text.split())


def test_reference_section_blocks_are_not_highlight_candidates_on_mixed_page() -> None:
    planner = HighlightPlanner(None, None, None, None, None)  # type: ignore[arg-type]
    structure = StructureDetector()
    document = PdfExtractor().extract(
        Path("/Users/nirtzur/Documents/projects/PDFReasoner/papers/Explaining the Predictions of Any Classifier.pdf")
    )
    mixed_page = document.pages[9]
    reference_block = next(block for block in mixed_page.blocks if block.block_id == "p10-b4")
    content_block = next(block for block in mixed_page.blocks if block.block_id == "p10-b0")

    assert structure.is_reference_section(reference_block.section_title) is True
    assert planner._is_candidate(reference_block, is_reference_page=False) is False
    assert planner._is_candidate(content_block, is_reference_page=False) is True


def test_inline_section_heading_only_quote_does_not_survive_as_final_match() -> None:
    planner = HighlightPlanner(None, None, None, SpanAligner(), None)  # type: ignore[arg-type]
    words = [
        ExtractedWord(1, "p7-b20", 0, 0, "5.4", "5.4", (0, 0, 10, 10)),
        ExtractedWord(1, "p7-b20", 0, 1, "Can", "can", (11, 0, 20, 10)),
        ExtractedWord(1, "p7-b20", 0, 2, "I", "i", (21, 0, 24, 10)),
        ExtractedWord(1, "p7-b20", 0, 3, "trust", "trust", (25, 0, 35, 10)),
        ExtractedWord(1, "p7-b20", 0, 4, "this", "this", (36, 0, 46, 10)),
        ExtractedWord(1, "p7-b20", 0, 5, "model?", "model", (47, 0, 60, 10)),
        ExtractedWord(1, "p7-b20", 0, 6, "In", "in", (61, 0, 68, 10)),
        ExtractedWord(1, "p7-b20", 0, 7, "the", "the", (69, 0, 77, 10)),
        ExtractedWord(1, "p7-b20", 0, 8, "final", "final", (78, 0, 90, 10)),
        ExtractedWord(1, "p7-b20", 0, 9, "simulated", "simulated", (91, 0, 112, 10)),
        ExtractedWord(1, "p7-b20", 0, 10, "user", "user", (113, 0, 123, 10)),
        ExtractedWord(1, "p7-b20", 0, 11, "experiment,", "experiment", (124, 0, 148, 10)),
    ]
    block = ExtractedBlock(
        page_number=7,
        block_id="p7-b20",
        bbox=(0, 0, 160, 20),
        text="5.4 Can I trust this model? In the final simulated user experiment, we evaluate whether the explanations can be used for model selection.",
        avg_font_size=10.0,
        is_heading=False,
        section_title="5.4 Can I trust this model?",
        words=words,
    )

    highlight = planner._to_highlight(
        block,
        "result",
        {"selected_quote": "5.4 Can I trust this model?", "rationale": "Test", "confidence": 0.8},
        1,
        [block],
    )

    assert highlight is not None
    assert highlight.matched_quote != "5.4 Can I trust this model?"


def test_source_block_selection_can_choose_clause_anchor_for_notation_sentence() -> None:
    planner = HighlightPlanner(None, None, None, None, None)  # type: ignore[arg-type]
    block = ExtractedBlock(
        page_number=1,
        block_id="p3-b2",
        bbox=(0, 0, 100, 100),
        text=(
            "We denote x∈Rd be the original representation of an instance being explained, "
            "and we usex′ ∈{0, 1}d′ to denote a binary vector for its interpretable representation."
        ),
        avg_font_size=11.0,
        is_heading=False,
        section_title="Method",
        words=[],
    )

    quote = planner._best_anchor_quote(
        block,
        {
            "title": "Interpretable representation",
            "statement": "The paper distinguishes the original feature space from the interpretable binary representation.",
            "label": "definition",
            "block_id": block.block_id,
            "confidence": 0.9,
        },
    )

    assert "interpretable representation" in quote or "original representation" in quote
    assert len(quote.split()) < len(block.text.split())
