from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import logging
import re
import shutil
import subprocess
from pathlib import Path

import fitz

from papercoach.analyze.citations import enrich_citations, parse_bibliography_from_text, parse_in_text_citations
from papercoach.analyze.commentary import build_skip_notes, generate_note
from papercoach.analyze.extractor import extract_text
from papercoach.analyze.highlights import detect_highlights
from papercoach.analyze.mindmap import generate_mindmap
from papercoach.analyze.structure import Section, detect_sections
from papercoach.analyze.text_clean import clean_extracted_text
from papercoach.analyze.tracing import build_citation_provenance_index, build_tracing_targets
from papercoach.config import RunConfig, ServiceConfig
from papercoach.integrations.cache import SQLiteCache
from papercoach.integrations.crossref_client import CrossrefClient
from papercoach.integrations.grobid_client import GrobidClient
from papercoach.integrations.ollama_client import OllamaClient
from papercoach.integrations.semanticscholar_client import SemanticScholarClient
from papercoach.models import AnnotationPlan, EvidenceRef, Highlight, MarginNote, PagePlan, SpanRef, TextBlock
from papercoach.render.pdf_renderer import render_pdf
from papercoach.reporting.html_report import write_low_confidence_report

_WORD_RE = re.compile(r"[A-Za-z]{3,}")
_SPLIT_FRAGMENT_RE = re.compile(r"\b[a-z]{3,}\s+[a-z]{1,2}\b")
_REFERENCE_ENTRY_RE = re.compile(r"^[A-Z][A-Za-z\-\.\s]{1,40},\s+.+\(\s*(?:19|20)\d{2}[a-z]?\s*\)")
_TECHNICAL_KEYWORDS = (
    "algorithm",
    "kalman",
    "likelihood",
    "covariance",
    "estimate",
    "estimation",
    "parameter",
    "dynamics",
    "state",
    "observation",
    "density",
    "filter",
    "smoothing",
    "recursion",
    "expectation",
    "maximization",
)


def _logger(workdir: Path) -> logging.Logger:
    workdir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(f"papercoach.{workdir}")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fh = logging.FileHandler(workdir / "run.log")
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(fh)
    logger.addHandler(logging.StreamHandler())
    return logger


def _hash_pdf(pdf_path: Path) -> str:
    h = hashlib.sha256()
    with pdf_path.open("rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _validate_pdf_readable(pdf_path: Path) -> None:
    if not pdf_path.exists():
        raise FileNotFoundError(f"Input PDF not found: {pdf_path}")
    with fitz.open(pdf_path):
        pass


def preflight(run: RunConfig, services: ServiceConfig, logger: logging.Logger) -> dict:
    _validate_pdf_readable(run.input_pdf)

    grobid = GrobidClient(services.grobid_url)
    grobid.healthcheck()

    ollama = OllamaClient(services.ollama_url, services.ollama_model)
    ollama.healthcheck()

    cache = SQLiteCache(run.workdir / "cache.sqlite")
    crossref = CrossrefClient(services.crossref_url, cache)
    s2 = SemanticScholarClient(services.semanticscholar_url, cache)
    if not run.no_web:
        crossref.healthcheck()
        s2.healthcheck()

    logger.info("Preflight complete")
    return {
        "grobid": grobid,
        "ollama": ollama,
        "crossref": crossref,
        "s2": s2,
        "cache": cache,
        "paper_id": _hash_pdf(run.input_pdf),
    }


def _block_index(blocks) -> dict[str, int]:
    return {b.block_id: i for i, b in enumerate(blocks)}


def _context_for_block(blocks, idx: int, radius: int = 1) -> str:
    start = max(0, idx - radius)
    end = min(len(blocks), idx + radius + 1)
    return "\n".join(b.text for b in blocks[start:end])


def _find_block_for_title(blocks, title: str):
    normalized = title.strip().lower()
    if not normalized:
        return None
    exact = next((b for b in blocks if b.text.strip().lower() == normalized), None)
    if exact:
        return exact
    prefix = next((b for b in blocks if b.text.strip().lower().startswith(normalized)), None)
    if prefix:
        return prefix
    return next((b for b in blocks if normalized in b.text.lower() and len(b.text) <= 140), None)


def _append_note(page_map: dict[int, PagePlan], note: MarginNote) -> None:
    page_map[note.page].notes.append(note)


def _merge_evidence(base: list[EvidenceRef], extra: list[EvidenceRef], cap: int = 3) -> list[EvidenceRef]:
    merged: list[EvidenceRef] = []
    seen: set[str] = set()
    for e in base + extra:
        key = json.dumps(e.model_dump(), sort_keys=True, ensure_ascii=True)
        if key in seen:
            continue
        seen.add(key)
        merged.append(e)
        if len(merged) >= cap:
            break
    return merged


def _looks_like_reference_entry(text: str) -> bool:
    compact = clean_extracted_text(text)
    if len(compact) < 30:
        return False
    if _REFERENCE_ENTRY_RE.match(compact):
        return True
    return bool(
        re.match(r"^[A-Z][A-Za-z\-\.\s]{1,40},", compact)
        and compact.count("(") >= 1
        and compact.count(")") >= 1
        and compact.count(".") >= 2
    )


def _detect_reference_pages(blocks: list[TextBlock]) -> set[int]:
    by_page: dict[int, list[TextBlock]] = defaultdict(list)
    for b in blocks:
        by_page[b.page].append(b)
    out: set[int] = set()
    for page, page_blocks in by_page.items():
        has_heading = any(b.text.strip().lower().startswith("references") for b in page_blocks)
        ref_like_count = sum(1 for b in page_blocks if _looks_like_reference_entry(b.text))
        if has_heading or ref_like_count >= 4:
            out.add(page)
    return out


def _technical_block_score(block: TextBlock) -> float:
    text = clean_extracted_text(block.text)
    if len(text) < 65:
        return -1000.0
    if _looks_like_reference_entry(text):
        return -1000.0
    lower = text.lower()
    words = _WORD_RE.findall(lower)
    if len(words) < 8:
        return -1000.0

    keyword_hits = sum(1 for k in _TECHNICAL_KEYWORDS if k in lower)
    equation_refs = len(re.findall(r"\(\d{1,2}\)", text))
    signal_hits = sum(1 for w in ("thus", "therefore", "assume", "let", "update", "goal") if w in lower)
    split_penalty = len(_SPLIT_FRAGMENT_RE.findall(lower))
    noise_chars = sum(1 for ch in text if ord(ch) < 32 and ch not in "\t\n\r")
    symbol_penalty = len(re.findall(r"[^\w\s\.,;:()\-\+\*/=']", text))

    return (
        keyword_hits * 1.4
        + min(len(words) / 16.0, 2.0)
        + equation_refs * 0.6
        + signal_hits * 0.6
        + (0.3 if block.font_meta.get("bold") else 0.0)
        - split_penalty * 0.35
        - noise_chars * 1.5
        - (symbol_penalty / max(len(text), 1)) * 10.0
    )


def _select_focus_blocks(
    blocks: list[TextBlock],
    used_block_ids: set[str],
    reference_pages: set[int],
    per_page: int = 2,
) -> list[TextBlock]:
    by_page: dict[int, list[TextBlock]] = defaultdict(list)
    for b in blocks:
        by_page[b.page].append(b)

    selected: list[TextBlock] = []
    for page, page_blocks in sorted(by_page.items()):
        if page in reference_pages:
            continue
        ranked = sorted(page_blocks, key=_technical_block_score, reverse=True)
        picked = 0
        for b in ranked:
            if picked >= per_page:
                break
            if b.block_id in used_block_ids:
                continue
            if _technical_block_score(b) <= -900.0:
                continue
            used_block_ids.add(b.block_id)
            selected.append(b)
            picked += 1
    return selected


def _section_anchor_block(blocks: list[TextBlock], section_block: TextBlock, idx: int) -> TextBlock:
    if len(section_block.text.split()) > 3 or len(section_block.text) > 32:
        return section_block
    for probe in blocks[idx + 1 : idx + 7]:
        if probe.page != section_block.page:
            break
        if len(probe.text) < 90:
            continue
        if _looks_like_reference_entry(probe.text):
            continue
        return probe
    return section_block


def analyze(run: RunConfig, services: ServiceConfig) -> AnnotationPlan:
    logger = _logger(run.workdir)
    deps = preflight(run, services, logger)

    extracted = extract_text(run.input_pdf)
    blocks = extracted.blocks
    spans = extracted.spans
    page_map = {p: PagePlan(page=p, highlights=[], anchors=[], notes=[]) for p in extracted.page_sizes}
    block_idx = _block_index(blocks)

    tei = deps["grobid"].process_fulltext(run.input_pdf)
    sections = detect_sections(blocks)
    tei_sections = tei.get("sections", [])
    tei_page_context: dict[int, str] = {}
    if tei_sections:
        existing = {s.title.lower() for s in sections}
        matched_tei_positions: list[tuple[int, str]] = []
        for s in tei_sections:
            title = (s.get("title") or "").strip()
            if title and title.lower() not in existing:
                matched_block = _find_block_for_title(blocks, title)
                if not matched_block:
                    continue
                sections.append(Section(title=title, page=matched_block.page, block_id=matched_block.block_id))
                existing.add(title.lower())
                if s.get("text"):
                    matched_tei_positions.append((matched_block.page, clean_extracted_text(str(s["text"]))[:1600]))
        for s in tei_sections:
            title = (s.get("title") or "").strip().lower()
            if not title or not s.get("text"):
                continue
            b = _find_block_for_title(blocks, title)
            if b:
                matched_tei_positions.append((b.page, clean_extracted_text(str(s["text"]))[:1600]))
        matched_tei_positions = sorted(matched_tei_positions, key=lambda x: x[0])
        for i, (start_page, text) in enumerate(matched_tei_positions):
            end_page = matched_tei_positions[i + 1][0] if i + 1 < len(matched_tei_positions) else max(page_map.keys()) + 1
            for p in range(start_page, end_page):
                if p not in tei_page_context:
                    tei_page_context[p] = text

    reference_pages = _detect_reference_pages(blocks)
    highlights, anchors, note_targets = detect_highlights(blocks)
    highlights = [h for h in highlights if h.page not in reference_pages]
    anchors = [a for a in anchors if a.page not in reference_pages]
    note_targets = [(b, tag) for b, tag in note_targets if b.page not in reference_pages]
    note_target_blocks = {block.block_id for block, tag in note_targets if tag != "section_heading"}
    for block in _select_focus_blocks(blocks, note_target_blocks, reference_pages, per_page=2):
        note_targets.append((block, "page_focus"))
        highlights.append(Highlight(page=block.page, bbox=block.bbox, tag="focus"))
        anchors.append(
            SpanRef(
                page=block.page,
                block_id=block.block_id,
                span_index=0,
                bbox=block.bbox,
                text=block.text,
            )
        )
    for hl in highlights:
        page_map[hl.page].highlights.append(hl)
    for a in anchors:
        page_map[a.page].anchors.append(a)

    bib_entries = tei.get("bibliography") or parse_bibliography_from_text(blocks)
    citations = parse_in_text_citations(spans, bib_entries)
    citations = enrich_citations(
        citations,
        top_n=run.top_n_references,
        use_web=not run.no_web,
        crossref_client=deps["crossref"],
        s2_client=deps["s2"],
    )

    tracing_targets = build_tracing_targets(spans, citations)
    citation_provenance_by_block = build_citation_provenance_index(citations)
    citation_provenance_by_page: dict[int, list[EvidenceRef]] = defaultdict(list)
    for (page_idx, _block_id), evidence in citation_provenance_by_block.items():
        citation_provenance_by_page[page_idx].extend(evidence)
    tracing_by_block: dict[tuple[int, str], list[EvidenceRef]] = defaultdict(list)
    for target in tracing_targets:
        span = target["span"]
        key = (span.page, span.block_id)
        tracing_by_block[key].extend(target["evidence"])
    pages_with_tracing = {target["span"].page for target in tracing_targets}

    def _with_page_citation_provenance(page: int, evidence: list[EvidenceRef]) -> list[EvidenceRef]:
        if any("span_index" in (e.pointer or {}) for e in evidence):
            return evidence
        return _merge_evidence(evidence, citation_provenance_by_page.get(page, []))
    page_note_counts: dict[int, int] = defaultdict(int)
    section_note_counts: dict[int, int] = defaultdict(int)
    max_total_notes_per_page = 2
    max_section_notes_per_page = 1

    for sec in sections:
        b = next((x for x in blocks if x.block_id == sec.block_id), None)
        if not b:
            continue
        if b.page in reference_pages:
            continue
        if b.block_id in note_target_blocks:
            continue
        if page_note_counts[b.page] >= max_total_notes_per_page:
            continue
        if section_note_counts[b.page] >= max_section_notes_per_page:
            continue
        b_anchor = _section_anchor_block(blocks, b, block_idx[b.block_id])
        evidence = [
            EvidenceRef(
                type="paper",
                pointer={"page": b_anchor.page, "block_id": b_anchor.block_id, "kind": "section"},
                quote=b_anchor.text[:250],
            )
        ]
        evidence = _merge_evidence(evidence, citation_provenance_by_block.get((b_anchor.page, b_anchor.block_id), []))
        evidence = _merge_evidence(evidence, tracing_by_block.get((b_anchor.page, b_anchor.block_id), []))
        evidence = _with_page_citation_provenance(b_anchor.page, evidence)
        context = _context_for_block(blocks, block_idx[b_anchor.block_id])
        if tei_page_context.get(b_anchor.page):
            context = f"{context}\n{tei_page_context[b_anchor.page][:700]}"
        note = generate_note(
            deps["ollama"],
            page=b_anchor.page,
            anchor_bbox=b_anchor.bbox,
            anchor_text=b_anchor.text,
            context=context,
            evidence=evidence,
            note_kind="section_tldr",
        )
        _append_note(page_map, note)
        page_note_counts[b_anchor.page] += 1
        section_note_counts[b_anchor.page] += 1

    for block, tag in note_targets:
        if tag == "section_heading":
            continue
        if block.page in reference_pages:
            continue
        if tag == "page_focus" and block.page in pages_with_tracing and page_note_counts[block.page] >= max_total_notes_per_page - 1:
            continue
        if page_note_counts[block.page] >= max_total_notes_per_page:
            continue
        evidence = [
            EvidenceRef(
                type="paper",
                pointer={"page": block.page, "block_id": block.block_id, "tag": tag},
                quote=block.text[:250],
            )
        ]
        evidence = _merge_evidence(evidence, citation_provenance_by_block.get((block.page, block.block_id), []))
        evidence = _merge_evidence(evidence, tracing_by_block.get((block.page, block.block_id), []))
        evidence = _with_page_citation_provenance(block.page, evidence)
        context = _context_for_block(blocks, block_idx[block.block_id])
        if tei_page_context.get(block.page):
            context = f"{context}\n{tei_page_context[block.page][:700]}"
        note = generate_note(
            deps["ollama"],
            page=block.page,
            anchor_bbox=block.bbox,
            anchor_text=block.text,
            context=context,
            evidence=evidence,
            note_kind=tag,
        )
        _append_note(page_map, note)
        page_note_counts[block.page] += 1

    for block, evidence, tag in build_skip_notes(blocks):
        if block.page in reference_pages:
            continue
        evidence = _merge_evidence(evidence, citation_provenance_by_block.get((block.page, block.block_id), []))
        evidence = _merge_evidence(evidence, tracing_by_block.get((block.page, block.block_id), []))
        evidence = _with_page_citation_provenance(block.page, evidence)
        if page_note_counts[block.page] >= max_total_notes_per_page:
            continue
        context = _context_for_block(blocks, block_idx[block.block_id])
        note = generate_note(
            deps["ollama"],
            page=block.page,
            anchor_bbox=block.bbox,
            anchor_text=block.text,
            context=context,
            evidence=evidence,
            note_kind=tag,
        )
        _append_note(page_map, note)
        page_note_counts[block.page] += 1

    for target in tracing_targets:
        span: SpanRef = target["span"]
        if span.page in reference_pages:
            continue
        if page_note_counts[span.page] >= max_total_notes_per_page:
            continue
        c = target["citation"]
        title = c.resolved.title if c and c.resolved and c.resolved.title else (c.raw if c else "referenced work")
        anchor_text = f"Imported idea marker: {span.text} | citation: {title}"
        block = next((b for b in blocks if b.block_id == span.block_id), None)
        context = block.text if block else span.text
        if tei_page_context.get(span.page):
            context = f"{context}\n{tei_page_context[span.page][:700]}"
        note = generate_note(
            deps["ollama"],
            page=span.page,
            anchor_bbox=span.bbox,
            anchor_text=anchor_text,
            context=context,
            evidence=target["evidence"],
            note_kind="citation_trace",
        )
        _append_note(page_map, note)
        page_note_counts[span.page] += 1

    blocks_by_page: dict[int, list] = defaultdict(list)
    for b in blocks:
        blocks_by_page[b.page].append(b)
    for page_idx in sorted(page_map):
        if page_idx in reference_pages:
            continue
        if page_note_counts[page_idx] > 0:
            continue
        candidates = [b for b in blocks_by_page.get(page_idx, []) if len(b.text) >= 90]
        if not candidates:
            continue
        anchor = max(candidates, key=lambda b: (_technical_block_score(b), len(b.text)))
        evidence = [
            EvidenceRef(
                type="paper",
                pointer={"page": anchor.page, "block_id": anchor.block_id, "kind": "page_snapshot"},
                quote=anchor.text[:250],
            )
        ]
        evidence = _merge_evidence(evidence, citation_provenance_by_block.get((anchor.page, anchor.block_id), []))
        evidence = _merge_evidence(evidence, tracing_by_block.get((anchor.page, anchor.block_id), []))
        evidence = _with_page_citation_provenance(anchor.page, evidence)
        context = _context_for_block(blocks, block_idx[anchor.block_id])
        if tei_page_context.get(anchor.page):
            context = f"{context}\n{tei_page_context[anchor.page][:700]}"
        note = generate_note(
            deps["ollama"],
            page=anchor.page,
            anchor_bbox=anchor.bbox,
            anchor_text=anchor.text,
            context=context,
            evidence=evidence,
            note_kind="page_tldr",
        )
        _append_note(page_map, note)
        page_map[anchor.page].highlights.append(Highlight(page=anchor.page, bbox=anchor.bbox, tag="focus"))
        page_note_counts[page_idx] += 1

    theorem_nodes = [
        {"block_id": b.block_id, "page": b.page, "label": b.text[:48]}
        for b, tag in note_targets
        if tag == "theorem_like"
    ]
    note_signals = []
    for page_idx, page_plan in sorted(page_map.items()):
        for note in page_plan.notes[:2]:
            note_signals.append(
                {
                    "page": page_idx,
                    "title": note.title[:80],
                    "flag": note.flags[0] if note.flags else "note",
                }
            )
    mindmap_path = run.workdir / "mindmap.png"
    sec_payload = [{"title": s.title, "page": s.page} for s in sections]
    mindmap = generate_mindmap(
        out_png=mindmap_path,
        sections=sec_payload,
        theorem_nodes=theorem_nodes,
        citations=citations,
        position=run.mindmap_position,
        ollama_client=deps["ollama"],
        note_signals=note_signals,
    )

    plan = AnnotationPlan(
        paper_id=deps["paper_id"],
        meta={
            "level": run.level,
            "input_pdf": str(run.input_pdf),
            "no_web": run.no_web,
            "margin_width": run.margin_width,
        },
        pages=page_map,
        references=citations,
        mindmaps=[mindmap],
    )

    plan_path = run.workdir / "annotation_plan.json"
    plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    _write_evidence_ledger(plan, run.workdir / "evidence_ledger.jsonl")
    write_low_confidence_report(plan, run.workdir / "report.html")

    logger.info("Analysis complete")
    return plan


def _write_evidence_ledger(plan: AnnotationPlan, out_path: Path) -> None:
    with out_path.open("w", encoding="utf-8") as f:
        for page_idx, page in sorted(plan.pages.items()):
            for note_idx, note in enumerate(page.notes):
                rec = {
                    "note_id": f"p{page_idx}_n{note_idx}",
                    "page": page_idx,
                    "title": note.title,
                    "confidence": note.confidence,
                    "flags": note.flags,
                    "evidence": [e.model_dump() for e in note.evidence],
                }
                f.write(json.dumps(rec, ensure_ascii=True) + "\n")


def render(run: RunConfig, plan_path: Path | None = None) -> Path:
    logger = _logger(run.workdir)
    _validate_pdf_readable(run.input_pdf)
    plan_file = plan_path or (run.workdir / "annotation_plan.json")
    if not plan_file.exists():
        raise FileNotFoundError(f"Annotation plan not found: {plan_file}")

    plan = AnnotationPlan.model_validate_json(plan_file.read_text(encoding="utf-8"))
    render_pdf(
        input_pdf=run.input_pdf,
        output_pdf=run.out_pdf,
        plan=plan,
        margin_width=run.margin_width,
        max_notes_per_page=run.max_notes_per_page,
        mindmap_position=run.mindmap_position,
    )
    _render_preview_pngs(run.out_pdf, run.workdir)
    logger.info("Render complete")
    return run.out_pdf


def annotate(run: RunConfig, services: ServiceConfig) -> Path:
    analyze(run, services)
    return render(run)


def _render_preview_pngs(pdf: Path, workdir: Path) -> None:
    pdftoppm = shutil.which("pdftoppm")
    if not pdftoppm:
        return
    out_prefix = workdir / "preview"
    cmd = [pdftoppm, "-f", "1", "-singlefile", "-png", str(pdf), str(out_prefix)]
    subprocess.run(cmd, check=False, capture_output=True)


def detect_unsupported_claims(text: str) -> bool:
    return bool(re.search(r"\bnew theorem|we derive a new\b", text, re.IGNORECASE))
