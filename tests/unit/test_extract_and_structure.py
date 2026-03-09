from __future__ import annotations

from pathlib import Path

from papercoach.extract.extractor import PdfExtractor
from papercoach.extract.normalize import clean_text
from papercoach.extract.structure import StructureDetector


def test_extractor_reads_blocks_and_reference_page(sample_pdf: Path) -> None:
    document = PdfExtractor().extract(sample_pdf)

    assert document.title
    assert len(document.pages) == 2
    assert any(block.section_title for block in document.pages[0].blocks if not block.is_heading)
    assert document.pages[1].is_reference_page is True


def test_extractor_uses_pymupdf_block_number_for_words() -> None:
    document = PdfExtractor().extract(
        Path("/Users/nirtzur/Documents/projects/PDFReasoner/papers/Explaining the Predictions of Any Classifier.pdf")
    )

    page3 = document.pages[2]
    block = next(block for block in page3.blocks if block.block_id == "p3-b5")

    assert block.text.startswith("This formulation can be used with different explanation families")
    assert clean_text(" ".join(word.text for word in block.words)).startswith(
        "This formulation can be used with different explanation families"
    )


def test_structure_detector_recognizes_numbered_reference_heading_on_mixed_page() -> None:
    detector = StructureDetector()

    assert detector.is_reference_heading("9. REFERENCES") is True
    assert detector.is_reference_section("9. REFERENCES") is True
    assert detector.is_reference_heading("8. CONCLUSION AND FUTURE WORK") is False
    assert detector.leading_section_title("5.4 Can I trust this model? In the final simulated user experiment") == "5.4 Can I trust this model?"
    assert detector.leading_section_title("4. SUBMODULAR PICK FOR EXPLAINING MODELS Although an explanation") == "4. SUBMODULAR PICK FOR EXPLAINING MODELS"


def test_extractor_rejects_author_lines_and_chart_axes_as_headings() -> None:
    document = PdfExtractor().extract(
        Path("/Users/nirtzur/Documents/projects/PDFReasoner/papers/Explaining the Predictions of Any Classifier.pdf")
    )

    page1 = document.pages[0]
    page7 = document.pages[6]

    assert next(block for block in page1.blocks if block.block_id == "p1-b2").is_heading is False
    assert next(block for block in page1.blocks if block.block_id == "p1-b3").is_heading is False
    assert next(block for block in page1.blocks if block.block_id == "p1-b15").is_heading is False
    assert next(block for block in page1.blocks if block.block_id == "p1-b4").is_heading is True
    assert next(block for block in page7.blocks if block.block_id == "p7-b4").is_heading is False
    assert next(block for block in page7.blocks if block.block_id == "p7-b11").is_heading is False
    assert next(block for block in document.pages[7].blocks if block.block_id == "p8-b7").is_heading is False


def test_extractor_recovers_words_for_real_blocks_missing_global_block_mapping() -> None:
    document = PdfExtractor().extract(
        Path("/Users/nirtzur/Documents/projects/PDFReasoner/papers/Explaining the Predictions of Any Classifier.pdf")
    )

    page2 = document.pages[1]
    block10 = next(block for block in page2.blocks if block.block_id == "p2-b10")
    block15 = next(block for block in page2.blocks if block.block_id == "p2-b15")
    block17 = next(block for block in page2.blocks if block.block_id == "p2-b17")

    assert block10.word_count == 3
    assert clean_text(" ".join(word.text for word in block10.words)) == "Human makes decision"
    assert block15.word_count > 100
    assert clean_text(" ".join(word.text for word in block15.words)).startswith(
        "2, we show how individual prediction explanations can be used to select between models"
    )
    assert block17.word_count > 40
    assert clean_text(" ".join(word.text for word in block17.words)).startswith(
        "We now outline a number of desired characteristics from explanation methods"
    )


def test_extractor_assigns_inline_numbered_section_titles_on_real_paper() -> None:
    document = PdfExtractor().extract(
        Path("/Users/nirtzur/Documents/projects/PDFReasoner/papers/Explaining the Predictions of Any Classifier.pdf")
    )

    assert next(block for block in document.pages[4].blocks if block.block_id == "p5-b9").section_title == "4. SUBMODULAR PICK FOR EXPLAINING MODELS"
    assert next(block for block in document.pages[5].blocks if block.block_id == "p6-b7").section_title == "5.1 Experiment Setup"
    assert next(block for block in document.pages[6].blocks if block.block_id == "p7-b20").section_title == "5.4 Can I trust this model?"
    assert next(block for block in document.pages[8].blocks if block.block_id == "p9-b9").section_title == "7. RELATED WORK"


def test_extractor_detects_height_based_headings_when_font_metadata_is_flat() -> None:
    document = PdfExtractor().extract(
        Path("/Users/nirtzur/Documents/projects/PDFReasoner/papers/Linear system em algo.pdf")
    )

    page1 = document.pages[0]
    page2 = document.pages[1]
    page3 = document.pages[2]
    page5 = document.pages[4]

    assert next(block for block in page1.blocks if block.block_id == "p1-b16").is_heading is True
    assert next(block for block in page1.blocks if block.block_id == "p1-b21").is_heading is True
    assert next(block for block in page2.blocks if block.block_id == "p2-b237").is_heading is True
    assert next(block for block in page3.blocks if block.block_id == "p3-b17").is_heading is True
    assert next(block for block in page5.blocks if block.block_id == "p5-b106").is_heading is False
    assert next(block for block in page1.blocks if block.block_id == "p1-b17").section_title == "In tro duction"
    assert next(block for block in page1.blocks if block.block_id == "p1-b22").section_title == "The Model"
