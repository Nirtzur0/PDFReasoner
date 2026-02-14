from __future__ import annotations

import re
from collections import defaultdict

from papercoach.analyze.text_clean import clean_extracted_text
from papercoach.models import Citation, ResolvedRef, SpanRef, TextBlock

NUMERIC_CIT_RE = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
AUTH_YEAR_RE = re.compile(r"\(([^()]{2,120}?(?:19|20)\d{2}[a-z]?)\s*\)")
BIB_SPLIT_RE = re.compile(r"^(?:\[(\d+)\]|(\d+)\.)\s+(.+)$")
REFERENCE_ENTRY_RE = re.compile(r"^[A-Z][A-Za-z\-\.\s]{1,40},\s+.+\(\s*(?:19|20)\d{2}[a-z]?\s*\)")


def parse_bibliography_from_text(blocks: list[TextBlock]) -> list[dict]:
    refs_start = None
    for i, b in enumerate(blocks):
        lowered = b.text.strip().lower()
        if lowered == "references" or lowered.startswith("referenc"):
            refs_start = i
            break
    if refs_start is None:
        return []

    entries: list[dict] = []
    for b in blocks[refs_start + 1:]:
        txt = b.text.strip()
        if not txt:
            continue
        m = BIB_SPLIT_RE.match(txt)
        if m:
            idx = m.group(1) or m.group(2)
            entries.append({"id": idx, "raw": m.group(3).strip()})
        elif re.search(r"^[A-Z][A-Za-z\-\.\s]{1,40},", txt):
            entries.append({"id": str(len(entries) + 1), "raw": txt})
        elif entries:
            entries[-1]["raw"] += f" {txt}"

    return entries


def _pick_best_bib(raw_match: str, bibliography: list[dict]) -> dict | None:
    raw_lower = raw_match.lower()
    for bib in bibliography:
        if bib.get("id") and bib["id"] in raw_match:
            return bib
        title = (bib.get("title") or bib.get("raw") or "").lower()
        if title and any(token for token in raw_lower.split() if len(token) > 4 and token in title):
            return bib
    return None


def _collapsed_alpha(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower())


def _extract_bib_surnames(raw: str) -> list[str]:
    author_part = raw.split(".")[0]
    matches = re.findall(r"([A-Z][A-Za-z\-\s]{1,24}),", author_part)
    out: list[str] = []
    for m in matches:
        s = _collapsed_alpha(m)
        if len(s) >= 5:
            out.append(s)
    if out:
        return out
    words = [w for w in re.findall(r"[A-Za-z]{3,}", raw) if len(w) >= 5]
    return [_collapsed_alpha(w) for w in words[:2]]


def _looks_like_reference_entry(text: str) -> bool:
    candidate = clean_extracted_text(text)
    if len(candidate) < 30:
        return False
    if REFERENCE_ENTRY_RE.match(candidate):
        return True
    return bool(
        re.match(r"^[A-Z][A-Za-z\-\.\s]{1,40},", candidate)
        and candidate.count("(") >= 1
        and candidate.count(")") >= 1
        and candidate.count(".") >= 2
    )


def parse_in_text_citations(spans: list[SpanRef], bibliography: list[dict]) -> list[Citation]:
    by_bib_key: dict[str, Citation] = {}
    by_raw: dict[str, Citation] = {}

    for span in spans:
        txt = span.text
        if _looks_like_reference_entry(txt):
            continue
        for m in NUMERIC_CIT_RE.finditer(txt):
            for n in [t.strip() for t in m.group(1).split(",") if t.strip()]:
                ref_key = n
                raw = f"[{n}]"
                if ref_key not in by_bib_key:
                    bib = next((b for b in bibliography if b.get("id") == n), None)
                    by_bib_key[ref_key] = Citation(
                        bib_key=ref_key,
                        raw=(bib.get("raw") if bib else raw),
                        in_text_spans=[],
                        mention_count=0,
                    )
                by_bib_key[ref_key].in_text_spans.append(span)
                by_bib_key[ref_key].mention_count += 1

        for m in AUTH_YEAR_RE.finditer(txt):
            group = m.group(1)
            parts = [p.strip() for p in group.split(";") if p.strip()]
            for raw in parts:
                if not re.search(r"(19|20)\d{2}", raw):
                    continue
                if raw not in by_raw:
                    bib = _pick_best_bib(raw, bibliography)
                    by_raw[raw] = Citation(
                        bib_key=(bib.get("id") if bib else None),
                        raw=(bib.get("raw") if bib else raw),
                        in_text_spans=[],
                        mention_count=0,
                    )
                by_raw[raw].in_text_spans.append(span)
                by_raw[raw].mention_count += 1

    # Block-level fallback for PDFs where citation text is split across many tiny spans.
    spans_by_block: dict[tuple[int, str], list[SpanRef]] = defaultdict(list)
    for s in spans:
        spans_by_block[(s.page, s.block_id)].append(s)

    for (_page, _block_id), block_spans in spans_by_block.items():
        if not block_spans:
            continue
        block_spans = sorted(block_spans, key=lambda x: x.span_index)
        merged_text = " ".join(s.text for s in block_spans)
        if _looks_like_reference_entry(merged_text):
            continue
        representative = block_spans[0]

        for m in NUMERIC_CIT_RE.finditer(merged_text):
            for n in [t.strip() for t in m.group(1).split(",") if t.strip()]:
                ref_key = n
                raw = f"[{n}]"
                if ref_key not in by_bib_key:
                    bib = next((b for b in bibliography if b.get("id") == n), None)
                    by_bib_key[ref_key] = Citation(
                        bib_key=ref_key,
                        raw=(bib.get("raw") if bib else raw),
                        in_text_spans=[],
                        mention_count=0,
                    )
                by_bib_key[ref_key].in_text_spans.append(representative)
                by_bib_key[ref_key].mention_count += 1

        for m in AUTH_YEAR_RE.finditer(merged_text):
            group = m.group(1)
            parts = [p.strip() for p in group.split(";") if p.strip()]
            for raw in parts:
                if not re.search(r"(19|20)\d{2}", raw):
                    continue
                if raw not in by_raw:
                    bib = _pick_best_bib(raw, bibliography)
                    by_raw[raw] = Citation(
                        bib_key=(bib.get("id") if bib else None),
                        raw=(bib.get("raw") if bib else raw),
                        in_text_spans=[],
                        mention_count=0,
                    )
                by_raw[raw].in_text_spans.append(representative)
                by_raw[raw].mention_count += 1

        if bibliography:
            block_compact = _collapsed_alpha(merged_text)
            for bib in bibliography:
                surnames = _extract_bib_surnames(bib.get("raw", ""))
                if not surnames:
                    continue
                if any(s in block_compact for s in surnames):
                    raw = bib.get("raw") or (bib.get("id") or "reference")
                    key = f"bib:{bib.get('id') or raw[:40]}"
                    if key not in by_raw:
                        by_raw[key] = Citation(
                            bib_key=(bib.get("id") if bib else None),
                            raw=raw,
                            in_text_spans=[],
                            mention_count=0,
                        )
                    by_raw[key].in_text_spans.append(representative)
                    by_raw[key].mention_count += 1

    return list(by_bib_key.values()) + list(by_raw.values())


def enrich_citations(
    citations: list[Citation],
    top_n: int,
    use_web: bool,
    crossref_client,
    s2_client,
) -> list[Citation]:
    sorted_citations = sorted(citations, key=lambda c: c.mention_count, reverse=True)
    for c in sorted_citations[:top_n]:
        resolved = ResolvedRef()
        if use_web:
            cross = crossref_client.resolve(c.raw) if crossref_client else None
            s2 = s2_client.resolve(c.raw) if s2_client else None
            if cross:
                resolved.doi = cross.get("doi")
                resolved.title = cross.get("title")
                resolved.year = cross.get("year")
                resolved.venue = cross.get("venue")
                resolved.url = cross.get("url")
            if s2:
                resolved.s2_paper_id = s2.get("s2_paper_id")
                resolved.title = resolved.title or s2.get("title")
                resolved.year = resolved.year or s2.get("year")
                resolved.venue = resolved.venue or s2.get("venue")
                resolved.url = resolved.url or s2.get("url")
                resolved.abstract_snippet = s2.get("abstract_snippet")
        c.resolved = resolved if any(v is not None for v in resolved.model_dump().values()) else None
    return citations
