from __future__ import annotations

import re
from collections import defaultdict

from papercoach.models import Citation, EvidenceRef, SpanRef

TRACE_RE = re.compile(r"\b(as in|following|based on|using the method of)\b", re.IGNORECASE)


def _citation_external_evidence(citation: Citation) -> EvidenceRef | None:
    if not citation.resolved:
        return None
    r = citation.resolved
    parts = []
    if r.title:
        parts.append(r.title)
    if r.year:
        parts.append(str(r.year))
    if r.venue:
        parts.append(r.venue)
    if r.abstract_snippet:
        parts.append(r.abstract_snippet)
    quote = " | ".join(parts).strip()
    if not quote:
        return None
    return EvidenceRef(
        type="external",
        pointer={
            "bib_key": citation.bib_key,
            "doi": r.doi,
            "s2_paper_id": r.s2_paper_id,
            "url": r.url,
        },
        quote=quote[:250],
    )


def _best_nearby_citation(span: SpanRef, by_page: dict[int, list[tuple[SpanRef, Citation]]]) -> Citation | None:
    cands = by_page.get(span.page, [])
    if not cands:
        return None

    same_block = [(s, c) for s, c in cands if s.block_id == span.block_id]
    pool = same_block if same_block else cands
    nearest = min(pool, key=lambda item: abs(item[0].span_index - span.span_index))
    s, c = nearest
    if not same_block and abs(s.span_index - span.span_index) > 25:
        return None
    return c


def build_citation_provenance_index(citations: list[Citation]) -> dict[tuple[int, str], list[EvidenceRef]]:
    out: dict[tuple[int, str], list[EvidenceRef]] = defaultdict(list)
    for c in citations:
        ext = _citation_external_evidence(c)
        for s in c.in_text_spans:
            key = (s.page, s.block_id)
            out[key].append(
                EvidenceRef(
                    type="paper",
                    pointer={"page": s.page, "block_id": s.block_id, "span_index": s.span_index},
                    quote=s.text[:250],
                )
            )
            if ext:
                out[key].append(ext)
    return out


def build_tracing_targets(spans: list[SpanRef], citations: list[Citation]) -> list[dict]:
    out: list[dict] = []
    citation_spans: dict[tuple[int, int], Citation] = {}
    by_page: dict[int, list[tuple[SpanRef, Citation]]] = defaultdict(list)
    for c in citations:
        for s in c.in_text_spans:
            citation_spans[(s.page, s.span_index)] = c
            by_page[s.page].append((s, c))

    for s in spans:
        if not TRACE_RE.search(s.text):
            continue
        linked = citation_spans.get((s.page, s.span_index)) or _best_nearby_citation(s, by_page)
        evidence = [
            EvidenceRef(
                type="paper",
                pointer={"page": s.page, "block_id": s.block_id, "span_index": s.span_index},
                quote=s.text[:250],
            )
        ]
        if linked:
            ext = _citation_external_evidence(linked)
            if ext:
                evidence.append(ext)
        out.append({"span": s, "citation": linked, "evidence": evidence})

    targets_by_key = {(t["span"].page, t["span"].block_id, t["span"].span_index) for t in out}
    spans_by_block: dict[tuple[int, str], list[SpanRef]] = defaultdict(list)
    for s in spans:
        spans_by_block[(s.page, s.block_id)].append(s)
    for (page, block_id), block_spans in spans_by_block.items():
        block_spans = sorted(block_spans, key=lambda x: x.span_index)
        merged_text = " ".join(s.text for s in block_spans)
        if not TRACE_RE.search(merged_text):
            continue
        representative = block_spans[0]
        key = (representative.page, representative.block_id, representative.span_index)
        if key in targets_by_key:
            continue
        linked = _best_nearby_citation(representative, by_page)
        evidence = [
            EvidenceRef(
                type="paper",
                pointer={"page": page, "block_id": block_id, "span_index": representative.span_index},
                quote=merged_text[:250],
            )
        ]
        if linked:
            ext = _citation_external_evidence(linked)
            if ext:
                evidence.append(ext)
        out.append({"span": representative, "citation": linked, "evidence": evidence})
    return out
