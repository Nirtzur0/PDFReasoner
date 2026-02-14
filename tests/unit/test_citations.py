from __future__ import annotations

from papercoach.analyze.citations import parse_bibliography_from_text, parse_in_text_citations
from papercoach.models import SpanRef, TextBlock


def test_parse_bibliography_and_in_text_citations() -> None:
    blocks = [
        TextBlock(page=0, block_id="b0", bbox=[0, 0, 1, 1], text="Body text", font_meta={}),
        TextBlock(page=1, block_id="b1", bbox=[0, 0, 1, 1], text="References", font_meta={}),
        TextBlock(page=1, block_id="b2", bbox=[0, 0, 1, 1], text="[1] Smith 2019", font_meta={}),
    ]
    spans = [
        SpanRef(page=0, block_id="b0", span_index=0, bbox=[0, 0, 1, 1], text="As in [1] we proceed"),
    ]

    bib = parse_bibliography_from_text(blocks)
    citations = parse_in_text_citations(spans, bib)

    assert len(bib) == 1
    assert citations
    assert citations[0].mention_count >= 1


def test_parse_author_year_citations_and_unnumbered_bibliography() -> None:
    blocks = [
        TextBlock(page=0, block_id="b0", bbox=[0, 0, 1, 1], text="Main content", font_meta={}),
        TextBlock(page=1, block_id="b1", bbox=[0, 0, 1, 1], text="References", font_meta={}),
        TextBlock(
            page=1,
            block_id="b2",
            bbox=[0, 0, 1, 1],
            text="Anderson, B. D. O. and Moore, J. B. (1979). Optimal Filtering.",
            font_meta={},
        ),
    ]
    spans = [
        SpanRef(
            page=0,
            block_id="b0",
            span_index=0,
            bbox=[0, 0, 1, 1],
            text="Following the method in (Anderson and Moore, 1979), we update the estimate.",
        ),
    ]

    bib = parse_bibliography_from_text(blocks)
    citations = parse_in_text_citations(spans, bib)

    assert bib
    assert citations
    assert any("1979" in c.raw for c in citations)


def test_parse_author_year_from_split_spans_block_fallback() -> None:
    bib = [{"id": "1", "raw": "Anderson, B. D. O. and Moore, J. B. (1979). Optimal Filtering."}]
    spans = [
        SpanRef(page=0, block_id="b0", span_index=0, bbox=[0, 0, 1, 1], text="following"),
        SpanRef(page=0, block_id="b0", span_index=1, bbox=[0, 0, 1, 1], text="("),
        SpanRef(page=0, block_id="b0", span_index=2, bbox=[0, 0, 1, 1], text="Anderson and Moore,"),
        SpanRef(page=0, block_id="b0", span_index=3, bbox=[0, 0, 1, 1], text="1979"),
        SpanRef(page=0, block_id="b0", span_index=4, bbox=[0, 0, 1, 1], text=")"),
    ]
    citations = parse_in_text_citations(spans, bib)
    assert citations
    assert any("1979" in c.raw for c in citations)


def test_parse_citation_from_surname_match_when_year_is_corrupted() -> None:
    blocks = [
        TextBlock(page=0, block_id="b0", bbox=[0, 0, 1, 1], text="References", font_meta={}),
        TextBlock(
            page=0,
            block_id="b1",
            bbox=[0, 0, 1, 1],
            text="Sh um w a y , R. H. and Sto er, D. S. (\x01 \x08\x02). EM algorithm paper.",
            font_meta={},
        ),
    ]
    bib = parse_bibliography_from_text(blocks)
    spans = [
        SpanRef(
            page=0,
            block_id="b9",
            span_index=0,
            bbox=[0, 0, 1, 1],
            text="Following Sh um w a y and Sto er we apply the update.",
        ),
    ]
    citations = parse_in_text_citations(spans, bib)
    assert citations
    assert any("Sh um w a y" in c.raw for c in citations)
