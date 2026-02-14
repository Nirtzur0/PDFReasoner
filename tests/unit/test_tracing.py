from __future__ import annotations

from papercoach.analyze.tracing import build_citation_provenance_index, build_tracing_targets
from papercoach.models import Citation, ResolvedRef, SpanRef


def _span(page: int, block_id: str, span_index: int, text: str) -> SpanRef:
    return SpanRef(page=page, block_id=block_id, span_index=span_index, bbox=[0, 0, 10, 10], text=text)


def test_tracing_targets_link_to_nearby_citation_when_not_exact_match() -> None:
    citation_span = _span(0, "b0", 12, "[1]")
    trace_span = _span(0, "b0", 10, "based on")
    c = Citation(
        bib_key="1",
        raw="Anderson and Moore",
        in_text_spans=[citation_span],
        resolved=ResolvedRef(title="Optimal Filtering", abstract_snippet="Recursive estimation principles."),
        mention_count=1,
    )
    targets = build_tracing_targets([trace_span, citation_span], [c])
    assert targets
    assert targets[0]["citation"] is not None
    assert any(e.type == "external" for e in targets[0]["evidence"])


def test_build_citation_provenance_index_emits_external_context() -> None:
    s = _span(2, "b4", 7, "(Anderson, 1979)")
    c = Citation(
        bib_key="2",
        raw="Anderson and Moore, 1979",
        in_text_spans=[s],
        resolved=ResolvedRef(title="Optimal Filtering", year=1979, venue="Prentice-Hall"),
        mention_count=1,
    )
    idx = build_citation_provenance_index([c])
    evidence = idx[(2, "b4")]
    assert any(e.type == "paper" for e in evidence)
    assert any(e.type == "external" for e in evidence)
