from __future__ import annotations

from papercoach.extract.extractor import PdfExtractor
from papercoach.llm.prompt_library import PromptLibrary


def test_prompt_library_exposes_balanced_paper_native_profile(sample_pdf) -> None:
    document = PdfExtractor().extract(sample_pdf)
    blocks = [block for page in document.pages for block in page.blocks if not block.is_heading]
    library = PromptLibrary()

    profile = library.profile("balanced", "paper-native", "minimal")
    _, user_prompt = library.document_selection_prompts(blocks, document, 4, [{"idea_id": "idea-1", "title": "Core idea"}])
    _, idea_prompt = library.key_idea_prompt(document, blocks, 4)

    assert profile.density == "balanced"
    assert profile.audience == "paper-native"
    assert "TASK_KIND: document_selection" in user_prompt
    assert "key ideas to drive coverage" in user_prompt
    assert "TASK_KIND: key_idea_extraction" in idea_prompt
    assert "PAYLOAD_JSON_START" in user_prompt


def test_note_prompt_is_local_and_non_generic(sample_pdf) -> None:
    document = PdfExtractor().extract(sample_pdf)
    library = PromptLibrary()

    _, user_prompt = library.note_prompt(
        document,
        1,
        [
            {
                "highlight_id": "h1",
                "label": "method",
                "section_title": "Method",
                "matched_quote": "This keeps highlights precise.",
                "local_context": "Method Our method extracts block-level text with word coordinates and aligns a contiguous quote back to the PDF words.",
                "section_context": "The method section explains extraction, alignment, and rendering constraints for the full pipeline.",
                "paper_context": "This paper builds a PDF-native highlighting system for research study workflows.",
                "article_context": "Full paper text goes here with all sections in order.",
                "idea_context": "Core pipeline idea: preserve precise PDF-native anchoring.",
                "focus_question": "Explain what technical role this sentence plays in the method.",
            }
        ],
    )

    assert "local technical role" in user_prompt
    assert "full article text" in user_prompt
    assert "specific target line or idea" in user_prompt
    assert "linked key idea" in user_prompt
    assert "focus question" in user_prompt
    assert "Do not write review-summary prose" in user_prompt
    assert "Do not use LaTeX" in user_prompt
    assert "PhD reader" in user_prompt


def test_equation_prompts_are_structured(sample_pdf) -> None:
    document = PdfExtractor().extract(sample_pdf)
    library = PromptLibrary()

    _, candidate_prompt = library.equation_candidate_prompt(
        document,
        [
            type(
                "Candidate",
                (),
                {
                    "equation_id": "eq1",
                    "block_id": "p1-b1",
                    "page_number": 1,
                    "equation_text_clean": "z = x + y",
                    "equation_label": "(1)",
                    "source_kind": "equation",
                    "section_title": "Method",
                    "local_context": "We define z as the sum of x and y.",
                    "symbol_context": "where z is score, x is method score, y is result score",
                },
            )()
        ],
    )
    _, explain_prompt = library.equation_explanation_prompt(
        document,
        1,
        [
            {
                "equation_id": "eq1",
                "equation_label": "(1)",
                "equation_text_clean": "z = x + y",
                "source_kind": "equation",
                "section_title": "Method",
                "role": "definition",
                "local_context": "We define z as the sum of x and y.",
                "symbol_context": "where z is score, x is method score, y is result score",
                "page_context": "Full page context with surrounding derivation.",
                "section_context": "Section-level context describing the objective and notation.",
                "paper_context": "Paper overview context tying this equation to the larger method.",
                "article_context": "Full article text tying this equation to the full method and results.",
                "focus_question": "Explain what this equation is doing in the paper.",
            }
        ],
    )

    assert "TASK_KIND: equation_candidate_screen" in candidate_prompt
    assert "TASK_KIND: equation_explanation" in explain_prompt
    assert '"symbol_map"' in explain_prompt
    assert '"display_latex"' in explain_prompt
    assert '"page_context"' in explain_prompt
    assert '"article_context"' in explain_prompt
    assert '"focus_question"' in explain_prompt
    assert "specific target inside the full article" in explain_prompt
    assert "Do not invent symbol meanings" in explain_prompt
