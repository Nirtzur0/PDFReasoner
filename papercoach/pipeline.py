from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path
import re

from papercoach.config import RunConfig, ServiceConfig
from papercoach.extract.align import SpanAligner
from papercoach.extract.equations import EquationCandidate, EquationDetector
from papercoach.extract.extractor import ExtractedBlock, ExtractedDocument, PdfExtractor
from papercoach.extract.normalize import clean_text, tokenize_for_match
from papercoach.extract.structure import StructureDetector
from papercoach.llm.client import ChatMockClient, TraceWriter
from papercoach.llm.prompt_library import PromptLibrary
from papercoach.models import (
    Box,
    CandidateBlock,
    EquationExplanation,
    EquationSelection,
    HighlightPlan,
    HighlightSelection,
    NoteSelection,
    PagePlan,
    PaperMeta,
    Point,
    QuadPoints,
    RunManifest,
)
from papercoach.render.pdf_renderer import PdfHighlightRenderer

_VALID_LABELS = {"contribution", "method", "result", "setup", "limitation", "definition"}
_VALID_EQUATION_ROLES = {"objective", "definition", "transition", "update", "constraint", "result"}
_CRITICAL_EQUATION_ROLES = {"objective", "transition", "update"}
_INCOMPLETE_TRAILING_TOKENS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "by",
    "for",
    "from",
    "in",
    "into",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}


class HighlightPlanner:
    def __init__(
        self,
        extractor: PdfExtractor,
        prompt_library: PromptLibrary,
        llm: ChatMockClient,
        aligner: SpanAligner,
        trace_writer: TraceWriter,
    ) -> None:
        self._extractor = extractor
        self._equation_detector = EquationDetector()
        self._structure = StructureDetector()
        self._prompt_library = prompt_library
        self._llm = llm
        self._aligner = aligner
        self._trace_writer = trace_writer

    def build_plan(self, run: RunConfig) -> HighlightPlan:
        document = self._extractor.extract(run.input_pdf)
        profile = self._prompt_library.profile(run.density, run.audience, run.style)
        page_map = {
            page.page_number: PagePlan(
                page_number=page.page_number,
                width=page.width,
                height=page.height,
                is_reference_page=page.is_reference_page,
                candidate_blocks=[self._candidate_block(block) for block in page.blocks if self._is_candidate(block, page.is_reference_page)],
                highlights=[],
            )
            for page in document.pages
        }
        document_blocks = [
            block
            for page in document.pages
            for block in page.blocks
            if self._is_candidate(block, page.is_reference_page)
        ]
        key_ideas = self._apply_document_selections(run, document, document_blocks, page_map)
        self._apply_equations(run, document, page_map)
        self._apply_notes(run, document, document_blocks, page_map, key_ideas)
        return HighlightPlan(
            meta=PaperMeta(
                paper_id=document.paper_id,
                title=document.title,
                input_pdf=str(run.input_pdf),
                page_count=len(document.pages),
            ),
            prompt_profile=profile,
            pages=[page_map[page.page_number] for page in document.pages],
        )

    def _apply_document_selections(
        self,
        run: RunConfig,
        document: ExtractedDocument,
        document_blocks: list[ExtractedBlock],
        page_map: dict[int, PagePlan],
    ) -> list[dict]:
        if not document_blocks:
            return []
        page_blocks = {
            page.page_number: [block for block in page.blocks if block.words and not self._is_reference_block(block)]
            for page in document.pages
        }
        target_highlights = self._document_budget(document, run.max_highlights_per_page)
        key_ideas = self._extract_key_ideas(document, document_blocks, max(4, min(target_highlights, 10)))
        raw_selection = self._source_block_selections(document_blocks, key_ideas)
        seen_pairs: set[tuple[str, str]] = set()
        for index, selection in enumerate(raw_selection.get("selections", []), start=1):
            block = self._block_by_id(document_blocks, selection.get("block_id"))
            if block is None:
                self._trace_writer.write({"type": "selection_skip", "reason": "unknown_block", "selection": selection})
                continue
            label = selection.get("label")
            if label not in _VALID_LABELS:
                self._trace_writer.write({"type": "selection_skip", "reason": "invalid_label", "selection": selection})
                continue
            quote = self._normalize_selected_quote(str(selection.get("selected_quote", "")))
            if not quote:
                self._trace_writer.write({"type": "selection_skip", "reason": "missing_quote", "selection": selection})
                continue
            dedupe_key = (block.block_id, quote)
            if dedupe_key in seen_pairs:
                continue
            seen_pairs.add(dedupe_key)
            highlight = self._to_highlight(block, label, selection, index, page_blocks[block.page_number])
            if highlight is not None and self._accept_highlight(highlight):
                page_map[block.page_number].highlights.append(highlight)
        for page_plan in page_map.values():
            page_plan.highlights = self._rebalance_page_highlights(page_plan.highlights, run.max_highlights_per_page)
        return key_ideas

    def _apply_equations(
        self,
        run: RunConfig,
        document: ExtractedDocument,
        page_map: dict[int, PagePlan],
    ) -> None:
        candidates = self._equation_detector.detect(document)
        if not candidates:
            return
        screened = self._screen_equation_candidates(document, candidates)
        if not screened:
            return
        selected = self._select_equations(document, screened, run.max_equations_per_page)
        if not selected:
            return

        selected_by_page: dict[int, list[tuple[EquationCandidate, dict]]] = {}
        for candidate, selection in selected:
            page_blocks = [
                block
                for block in document.pages[candidate.page_number - 1].blocks
                if block.words and not self._is_reference_block(block)
            ]
            alignment = self._aligner.align_block_words(self._equation_detector.anchor_words(page_blocks, candidate))
            if alignment is None:
                continue
            equation = EquationSelection(
                equation_id=candidate.equation_id,
                block_id=candidate.block_id,
                page_number=candidate.page_number,
                equation_text_clean=candidate.equation_text_clean,
                source_kind=candidate.source_kind,
                equation_label=candidate.equation_label,
                quads=[self._quad(quad) for quad in alignment.quads],
                role=str(selection.get("role", "definition")).strip(),
                confidence=float(min(max(selection.get("confidence", 0.0), 0.0), 1.0)),
            )
            page_map[candidate.page_number].equations.append(equation)
            selected_by_page.setdefault(candidate.page_number, []).append((candidate, selection))

        for page_plan in page_map.values():
            page_plan.equations = self._rebalance_equations(page_plan.equations, run.max_equations_per_page)

        for page_number, pairs in selected_by_page.items():
            page_equations = {
                equation.equation_id: equation
                for equation in page_map[page_number].equations
            }
            final_pairs = [(candidate, selection) for candidate, selection in pairs if candidate.equation_id in page_equations]
            if not final_pairs:
                continue
            explanations = self._generate_equation_explanations(document, page_number, final_pairs, page_equations)
            page_map[page_number].equation_notes.extend(explanations)

    def _apply_notes(
        self,
        run: RunConfig,
        document: ExtractedDocument,
        document_blocks: list[ExtractedBlock],
        page_map: dict[int, PagePlan],
        key_ideas: list[dict],
    ) -> None:
        block_map = {block.block_id: block for block in document_blocks}
        page_blocks = {
            page.page_number: [block for block in page.blocks if block.words and not self._is_reference_block(block)]
            for page in document.pages
        }
        for page_plan in page_map.values():
            highlight_slice = page_plan.highlights[: run.max_notes_per_page]
            if not highlight_slice:
                continue
            note_json = self._generate_notes(
                document,
                page_plan.page_number,
                page_blocks[page_plan.page_number],
                highlight_slice,
                block_map,
                key_ideas,
            )
            for index, highlight in enumerate(highlight_slice, start=1):
                block = block_map.get(highlight.block_id)
                if block is None:
                    continue
                note = note_json.get(highlight.highlight_id)
                if note is None:
                    continue
                page_plan.notes.append(
                    NoteSelection(
                        note_id=f"{highlight.highlight_id}-n{index}",
                        highlight_id=highlight.highlight_id,
                        anchor_block_id=block.block_id,
                        title=self._clean_note_title(str(note.get("title", ""))),
                        body=self._clean_note_body(str(note.get("body", ""))),
                        confidence=float(min(max(note.get("confidence", 0.0), 0.0), 1.0)),
                    )
                )

    def _to_highlight(
        self,
        block: ExtractedBlock,
        label: str,
        block_selection: dict,
        index: int,
        page_blocks: list[ExtractedBlock],
    ) -> HighlightSelection | None:
        quote = str(block_selection["selected_quote"]).strip()
        context_words = self._context_words(page_blocks, block)
        alignment = self._aligner.align_quote_in_words(context_words, quote)
        if alignment is not None and self._is_inline_heading_only_match(block, alignment.matched_text):
            alignment = None
        if alignment is None:
            for candidate_quote in self._candidate_anchor_quotes(block, block_selection):
                if clean_text(candidate_quote) == clean_text(quote):
                    continue
                alignment = self._aligner.align_quote_in_words(context_words, candidate_quote)
                if alignment is not None and self._is_inline_heading_only_match(block, alignment.matched_text):
                    alignment = None
                if alignment is not None:
                    quote = candidate_quote
                    break
        if alignment is None:
            raw_block_quote = " ".join(word.text for word in block.words if word.text.strip())
            if raw_block_quote and clean_text(raw_block_quote) != clean_text(quote):
                alignment = self._aligner.align_quote_in_words(context_words, raw_block_quote)
                if alignment is not None and self._is_inline_heading_only_match(block, alignment.matched_text):
                    alignment = None
        if alignment is None:
            self._trace_writer.write(
                {
                    "type": "alignment_skip",
                    "reason": "ambiguous_or_missing",
                    "block_id": block.block_id,
                    "quote": quote,
                }
            )
            return None
        return HighlightSelection(
            highlight_id=f"{block.block_id}-h{index}",
            block_id=block.block_id,
            label=label,
            rationale=str(block_selection.get("rationale", "")).strip(),
            confidence=float(min(max(block_selection.get("confidence", 0.0), 0.0), 1.0)),
            source_quote=quote,
            matched_quote=alignment.matched_text,
            quads=[self._quad(quad) for quad in alignment.quads],
        )

    def _is_inline_heading_only_match(self, block: ExtractedBlock, matched_text: str) -> bool:
        inline_section = self._structure.leading_section_title(block.text)
        if not inline_section:
            return False
        if clean_text(matched_text) != clean_text(inline_section):
            return False
        return len(clean_text(block.text)) > len(clean_text(inline_section)) + 24

    def _accept_highlight(self, highlight: HighlightSelection) -> bool:
        words = highlight.matched_quote.split()
        if len(words) < 5:
            return False
        text = clean_text(highlight.matched_quote)
        if not text:
            return False
        tail = re.sub(r"^[^\w]+|[^\w]+$", "", words[-1].lower())
        if tail in _INCOMPLETE_TRAILING_TOKENS and not re.search(r"[.!?:;](?:[\"')\]]*)$", text):
            return False
        return True

    def _generate_notes(
        self,
        document: ExtractedDocument,
        page_number: int,
        page_blocks: list[ExtractedBlock],
        highlights: list[HighlightSelection],
        block_map: dict[str, ExtractedBlock],
        key_ideas: list[dict],
    ) -> dict[str, dict]:
        out: dict[str, dict] = {}
        for highlight in highlights:
            block = block_map.get(highlight.block_id)
            if block is None:
                continue
            request_item = self._note_request_item(page_blocks, document, block, highlight, key_ideas)
            system_prompt, user_prompt = self._prompt_library.note_prompt(document, page_number, [request_item])
            note_json = self._llm.create_json_response(
                "note_generation",
                system_prompt,
                user_prompt,
                max_output_tokens=800,
            )
            notes = note_json.get("notes", [])
            if not isinstance(notes, list):
                continue
            for note in notes:
                highlight_id = str(note.get("highlight_id", "")).strip()
                title = str(note.get("title", "")).strip()
                body = str(note.get("body", "")).strip()
                if highlight_id != highlight.highlight_id or not title or not body:
                    continue
                out[highlight_id] = note
                break
        return out

    def _extract_key_ideas(
        self,
        document: ExtractedDocument,
        document_blocks: list[ExtractedBlock],
        target_ideas: int,
    ) -> list[dict]:
        system_prompt, user_prompt = self._prompt_library.key_idea_prompt(document, document_blocks, target_ideas)
        response = self._llm.create_json_response("key_idea_extraction", system_prompt, user_prompt, max_output_tokens=2200)
        ideas = response.get("ideas", [])
        if not isinstance(ideas, list):
            return []
        block_ids = {block.block_id for block in document_blocks}
        seen_blocks: set[str] = set()
        out: list[dict] = []
        for index, item in enumerate(ideas, start=1):
            block_id = str(item.get("block_id", "")).strip()
            title = clean_text(str(item.get("title", "")))
            statement = clean_text(str(item.get("statement", "")))
            label = str(item.get("label", "")).strip()
            if block_id not in block_ids or not title or not statement or label not in _VALID_LABELS:
                continue
            if block_id in seen_blocks:
                continue
            seen_blocks.add(block_id)
            out.append(
                {
                    "idea_id": str(item.get("idea_id", f"idea-{index}")).strip() or f"idea-{index}",
                    "title": title[:48],
                    "statement": statement[:240],
                    "label": label,
                    "block_id": block_id,
                    "confidence": float(min(max(item.get("confidence", 0.0), 0.0), 1.0)),
                }
            )
        return out

    def _source_block_selections(
        self,
        document_blocks: list[ExtractedBlock],
        key_ideas: list[dict],
    ) -> dict:
        block_map = {block.block_id: block for block in document_blocks}
        selections: list[dict] = []
        for idea in key_ideas:
            block_id = str(idea.get("block_id", "")).strip()
            block = block_map.get(block_id)
            if block is None:
                continue
            selections.append(
                {
                    "block_id": block_id,
                    "label": idea["label"],
                    "rationale": idea["statement"],
                    "confidence": float(min(max(idea.get("confidence", 0.0), 0.0), 1.0)),
                    "selected_quote": self._best_anchor_quote(block, idea),
                }
            )
        return {"selections": selections}

    def _screen_equation_candidates(
        self,
        document: ExtractedDocument,
        candidates: list[EquationCandidate],
    ) -> list[dict]:
        candidates = [candidate for candidate in candidates if candidate.quality_score >= 0.2]
        if not candidates:
            return []
        prompt_candidates = [self._equation_request_item(document, candidate, role="definition") for candidate in candidates]
        for candidate, payload in zip(candidates, prompt_candidates, strict=False):
            payload["quality_score"] = candidate.quality_score
        system_prompt, user_prompt = self._prompt_library.equation_candidate_prompt(document, prompt_candidates)
        response = self._llm.create_json_response("equation_candidate_screen", system_prompt, user_prompt, max_output_tokens=2400)
        out: list[dict] = []
        candidate_ids = {candidate.equation_id for candidate in candidates}
        for item in response.get("candidates", []):
            equation_id = str(item.get("equation_id", "")).strip()
            role = str(item.get("role", "")).strip()
            if equation_id not in candidate_ids:
                continue
            if not bool(item.get("keep")):
                continue
            if role not in _VALID_EQUATION_ROLES:
                continue
            out.append(item)
        return out

    def _select_equations(
        self,
        document: ExtractedDocument,
        screened: list[dict],
        max_equations_per_page: int,
    ) -> list[tuple[EquationCandidate, dict]]:
        candidate_map = {candidate.equation_id: candidate for candidate in self._equation_detector.detect(document)}
        prompt_candidates = []
        for item in screened:
            candidate = candidate_map.get(str(item.get("equation_id", "")).strip())
            if candidate is None:
                continue
            payload = self._equation_request_item(document, candidate, role=item["role"])
            payload["quality_score"] = candidate.quality_score
            payload["rationale"] = item.get("rationale", "")
            payload["confidence"] = item.get("confidence", 0.0)
            prompt_candidates.append(payload)
        if not prompt_candidates:
            return []
        system_prompt, user_prompt = self._prompt_library.equation_selection_prompt(document, prompt_candidates, max_equations_per_page)
        response = self._llm.create_json_response("equation_selection", system_prompt, user_prompt, max_output_tokens=1800)
        seen_by_page: dict[int, int] = {}
        selections: list[tuple[EquationCandidate, dict]] = []
        seen_equations: set[str] = set()
        for item in response.get("selections", []):
            equation_id = str(item.get("equation_id", "")).strip()
            role = str(item.get("role", "")).strip()
            if equation_id in seen_equations or role not in _VALID_EQUATION_ROLES:
                continue
            candidate = candidate_map.get(equation_id)
            if candidate is None:
                continue
            if candidate.quality_score < 0.35 and role not in {"objective", "definition"}:
                continue
            if seen_by_page.get(candidate.page_number, 0) >= max_equations_per_page:
                continue
            seen_by_page[candidate.page_number] = seen_by_page.get(candidate.page_number, 0) + 1
            seen_equations.add(equation_id)
            selections.append((candidate, item))
        return selections

    def _generate_equation_explanations(
        self,
        document: ExtractedDocument,
        page_number: int,
        equations: list[tuple[EquationCandidate, dict]],
        page_equations: dict[str, EquationSelection],
    ) -> list[EquationExplanation]:
        out: list[EquationExplanation] = []
        for candidate, _selection in equations:
            if candidate.equation_id not in page_equations:
                continue
            payload_item = self._equation_request_item(document, candidate, page_equations[candidate.equation_id].role)
            raw = self._request_equation_explanation(document, page_number, payload_item)
            if raw is None:
                continue
            passed, feedback = self._evaluate_equation_explanation(document, page_number, payload_item, raw)
            if not passed:
                retry_item = dict(payload_item)
                retry_item["review_feedback"] = feedback
                retried = self._request_equation_explanation(
                    document,
                    page_number,
                    retry_item,
                    prompt_name="equation_explanation_retry",
                )
                if retried is None:
                    continue
                raw = retried
                passed, feedback = self._evaluate_equation_explanation(
                    document,
                    page_number,
                    payload_item,
                    raw,
                    prompt_name="equation_evaluation_retry",
                )
            if not passed:
                continue
            explanation = EquationExplanation(
                equation_id=candidate.equation_id,
                title=self._clean_equation_title(str(raw.get("title", "")), candidate.equation_label),
                display_latex=self._clean_equation_latex(raw.get("display_latex")),
                symbol_map=self._clean_symbol_map(raw.get("symbol_map", {})),
                body=self._clean_note_body(str(raw.get("plain_explanation", ""))),
                intuition=self._clean_note_body(str(raw.get("intuition_or_consequence", ""))),
                confidence=float(min(max(raw.get("confidence", 0.0), 0.0), 1.0)),
            )
            if not self._accept_equation_explanation(explanation, candidate.equation_text_clean):
                continue
            out.append(
                explanation
            )
        return out

    def _request_equation_explanation(
        self,
        document: ExtractedDocument,
        page_number: int,
        payload_item: dict,
        prompt_name: str = "equation_explanation",
    ) -> dict | None:
        system_prompt, user_prompt = self._prompt_library.equation_explanation_prompt(document, page_number, [payload_item])
        response = self._llm.create_json_response(prompt_name, system_prompt, user_prompt, max_output_tokens=2200)
        for item in response.get("explanations", []):
            equation_id = str(item.get("equation_id", "")).strip()
            role = str(item.get("equation_role", "")).strip()
            title = str(item.get("title", "")).strip()
            display_latex = str(item.get("display_latex", "")).strip()
            body = str(item.get("plain_explanation", "")).strip()
            intuition = str(item.get("intuition_or_consequence", "")).strip()
            if equation_id != payload_item["equation_id"]:
                continue
            if role not in _VALID_EQUATION_ROLES or not title or not display_latex or not body or not intuition:
                continue
            return item
        return None

    def _evaluate_equation_explanation(
        self,
        document: ExtractedDocument,
        page_number: int,
        payload_item: dict,
        explanation: dict,
        prompt_name: str = "equation_evaluation",
    ) -> tuple[bool, str]:
        evaluation_item = {
            "equation_id": payload_item["equation_id"],
            "equation_label": payload_item.get("equation_label"),
            "equation_text_clean": payload_item["equation_text_clean"],
            "local_context": payload_item["local_context"],
            "symbol_context": payload_item["symbol_context"],
            "page_context": payload_item["page_context"],
            "section_context": payload_item["section_context"],
            "paper_context": payload_item["paper_context"],
            "article_context": payload_item["article_context"],
            "focus_question": payload_item["focus_question"],
            "display_latex": explanation.get("display_latex", ""),
            "equation_role": explanation["equation_role"],
            "symbol_map": explanation.get("symbol_map", {}),
            "plain_explanation": explanation["plain_explanation"],
            "intuition_or_consequence": explanation["intuition_or_consequence"],
        }
        system_prompt, user_prompt = self._prompt_library.equation_evaluation_prompt(document, page_number, [evaluation_item])
        response = self._llm.create_json_response(prompt_name, system_prompt, user_prompt, max_output_tokens=1400)
        for item in response.get("evaluations", []):
            equation_id = str(item.get("equation_id", "")).strip()
            if equation_id != payload_item["equation_id"]:
                continue
            return (bool(item.get("pass")), str(item.get("feedback", "")).strip())
        return (False, "No equation evaluation returned.")

    def _candidate_block(self, block: ExtractedBlock) -> CandidateBlock:
        return CandidateBlock(
            block_id=block.block_id,
            bbox=self._box(block.bbox),
            text=block.text,
            section_title=block.section_title,
            is_heading=block.is_heading,
            word_count=block.word_count,
        )

    def _document_budget(self, document: ExtractedDocument, max_highlights_per_page: int) -> int:
        content_pages = sum(1 for page in document.pages if not page.is_reference_page)
        return max(4, content_pages * max(1, max_highlights_per_page - 1))

    def _is_reference_block(self, block: ExtractedBlock) -> bool:
        return self._structure.is_reference_section(block.section_title) or self._structure.is_reference_entry(block.text)

    def _rebalance_equations(
        self,
        equations: list[EquationSelection],
        max_equations_per_page: int,
    ) -> list[EquationSelection]:
        if len(equations) <= max_equations_per_page:
            return equations
        prioritized = sorted(
            equations,
            key=lambda item: (
                0 if item.role in _CRITICAL_EQUATION_ROLES else 1,
                -(item.confidence),
            ),
        )
        return prioritized[:max_equations_per_page]

    def _rebalance_page_highlights(
        self,
        highlights: list[HighlightSelection],
        max_highlights_per_page: int,
    ) -> list[HighlightSelection]:
        if len(highlights) <= max_highlights_per_page:
            return highlights

        selected: list[HighlightSelection] = []
        seen_blocks: set[str] = set()
        for highlight in highlights:
            if highlight.block_id in seen_blocks:
                continue
            selected.append(highlight)
            seen_blocks.add(highlight.block_id)
            if len(selected) == max_highlights_per_page:
                return selected

        return highlights[:max_highlights_per_page]

    def _is_candidate(self, block: ExtractedBlock, is_reference_page: bool) -> bool:
        if is_reference_page:
            return False
        if block.is_heading:
            return False
        if self._is_reference_block(block):
            return False
        if block.word_count < 12:
            return False
        text = block.text.lower()
        if re.fullmatch(r"[0-9]+", text):
            return False
        return True

    def _block_by_id(self, blocks: list[ExtractedBlock], block_id: str | None) -> ExtractedBlock | None:
        if not block_id:
            return None
        return next((block for block in blocks if block.block_id == block_id), None)

    def _box(self, rect: tuple[float, float, float, float]) -> Box:
        return Box(x0=rect[0], y0=rect[1], x1=rect[2], y1=rect[3])

    def _quad(
        self,
        quad: tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]],
    ) -> QuadPoints:
        return QuadPoints(
            ul=Point(x=quad[0][0], y=quad[0][1]),
            ur=Point(x=quad[1][0], y=quad[1][1]),
            ll=Point(x=quad[2][0], y=quad[2][1]),
            lr=Point(x=quad[3][0], y=quad[3][1]),
        )

    def _context_words(self, page_blocks: list[ExtractedBlock], block: ExtractedBlock) -> list:
        try:
            index = next(i for i, candidate in enumerate(page_blocks) if candidate.block_id == block.block_id)
        except StopIteration:
            return block.words

        context: list = []
        for candidate in page_blocks[max(0, index - 1) : min(len(page_blocks), index + 3)]:
            if not self._is_contextual_text_block(candidate, block):
                continue
            context.extend(candidate.words)
        return context or block.words

    def _is_contextual_text_block(self, candidate: ExtractedBlock, anchor: ExtractedBlock) -> bool:
        if candidate.block_id == anchor.block_id:
            return True
        if candidate.is_heading:
            return False
        if self._is_reference_block(candidate):
            return False
        alpha_words = [word for word in candidate.words if len(word.normalized) >= 2 and any(ch.isalpha() for ch in word.normalized)]
        math_symbol_hits = sum(candidate.text.count(symbol) for symbol in ("=", "[", "]", "(", ")", "+", "/", "*"))
        if math_symbol_hits >= 2 and len(alpha_words) < 6:
            return False
        if len(alpha_words) >= 3:
            return True
        return False

    def _clean_note_title(self, title: str) -> str:
        title = re.sub(r"\s+", " ", clean_text(title)).strip(" :.-")
        return title[:48] or "Study note"

    def _clean_note_body(self, body: str) -> str:
        body = self._strip_latex_markup(body)
        body = re.sub(r"\s+", " ", clean_text(body)).strip()
        if len(body) <= 260:
            return body
        sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", body) if sentence.strip()]
        if sentences:
            if len(sentences[0]) <= 220:
                return sentences[0]
            if len(sentences) >= 2:
                combined = f"{sentences[0]} {sentences[1]}"
                if len(combined) <= 260:
                    return combined
        trimmed = body[:260].rstrip(" ,;:-")
        split_at = trimmed.rfind(" ")
        return (trimmed[:split_at] if split_at >= 180 else trimmed).rstrip(" ,;:-")

    def _clean_equation_title(self, title: str, equation_label: str | None) -> str:
        cleaned = re.sub(r"\s+", " ", clean_text(title)).strip(" :.-")
        cleaned = cleaned[:34] or "Equation note"
        if equation_label:
            prefix = f"Eq. {equation_label} "
            if not cleaned.startswith(prefix):
                return (prefix + cleaned)[:34]
        return cleaned

    def _clean_equation_latex(self, value: object) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        if not cleaned:
            return None
        if cleaned.startswith("$") and cleaned.endswith("$") and len(cleaned) >= 2:
            cleaned = cleaned[1:-1].strip()
        cleaned = re.sub(r"\s+", " ", cleaned)
        if "@" in cleaned:
            return None
        if "\\text{" in cleaned and (":" in cleaned or len(re.findall(r"[A-Za-z]{4,}", cleaned)) > 6):
            return None
        return cleaned[:220] or None

    def _accept_equation_explanation(self, explanation: EquationExplanation, source_equation_text: str) -> bool:
        if explanation.display_latex is None:
            return False
        lowered_title = explanation.title.lower()
        lowered_body = f"{explanation.body} {explanation.intuition}".lower()
        banned_phrases = (
            "corrupt",
            "too corrupted",
            "cannot be recovered",
            "too garbled",
            "cannot be reconstructed",
            "too broken",
        )
        if any(phrase in lowered_title for phrase in banned_phrases):
            return False
        if any(phrase in lowered_body for phrase in banned_phrases):
            return False
        if not self._equation_latex_is_grounded(explanation.display_latex, source_equation_text):
            return False
        return True

    def _equation_latex_is_grounded(self, display_latex: str, source_equation_text: str) -> bool:
        display_tokens = tokenize_for_match(display_latex)
        source_tokens = tokenize_for_match(source_equation_text)
        if not display_tokens or not source_tokens:
            return False

        display_compact = " ".join(display_tokens)
        source_compact = " ".join(source_tokens)
        similarity = SequenceMatcher(None, display_compact, source_compact).ratio()
        if similarity >= 0.55:
            return True

        display_vocab = set(display_tokens)
        overlap_ratio = len(display_vocab & set(source_tokens)) / len(display_vocab)
        return overlap_ratio >= 0.75

    def _clean_symbol_map(self, value: object) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        out: dict[str, str] = {}
        for key, raw in value.items():
            symbol = str(key).strip()
            meaning = self._clean_note_body(str(raw))
            if not symbol or not meaning:
                continue
            out[symbol[:20]] = meaning[:80]
            if len(out) == 4:
                break
        return out

    def _strip_latex_markup(self, text: str) -> str:
        stripped = text.replace("\\(", "").replace("\\)", "").replace("\\[", "").replace("\\]", "").replace("$", "")
        stripped = re.sub(r"\\text\{([^}]*)\}", r"\1", stripped)
        stripped = re.sub(r"\\mathbb\{E\}", "E", stripped)
        stripped = re.sub(r"\\hat\{([^}]*)\}", r"\1-hat", stripped)
        stripped = re.sub(r"\\mid", "|", stripped)
        stripped = re.sub(r"\\[a-zA-Z]+", "", stripped)
        return stripped.replace("{", "").replace("}", "")

    def _normalize_selected_quote(self, quote: str) -> str:
        quote = clean_text(quote)
        if not quote:
            return ""
        sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", quote) if sentence.strip()]
        if len(sentences) <= 2 and len(quote.split()) <= 55:
            return quote
        if sentences:
            first_sentence = sentences[0]
            if len(first_sentence.split()) >= 8:
                return first_sentence
            if len(sentences) >= 2:
                combined = " ".join(sentences[:2])
                if len(combined.split()) <= 55:
                    return combined
        return quote

    def _best_anchor_quote(self, block: ExtractedBlock, idea: dict) -> str:
        candidates = self._ranked_anchor_candidates(block, idea)
        if not candidates:
            return block.text
        return candidates[0]

    def _candidate_anchor_quotes(self, block: ExtractedBlock, block_selection: dict) -> list[str]:
        idea = {
            "title": str(block_selection.get("label", "")),
            "statement": str(block_selection.get("rationale", "")),
        }
        ranked = self._ranked_anchor_candidates(block, idea)
        normalized_selected = clean_text(str(block_selection.get("selected_quote", "")))
        candidates: list[str] = []
        seen: set[str] = set()
        for candidate in ranked:
            cleaned = clean_text(candidate)
            if not cleaned or cleaned == normalized_selected or cleaned in seen:
                continue
            seen.add(cleaned)
            candidates.append(candidate)
            if len(candidates) == 6:
                break
        return candidates

    def _ranked_anchor_candidates(self, block: ExtractedBlock, idea: dict) -> list[str]:
        candidates = self._sentence_candidates(block.text)
        if not candidates:
            return []
        scored = [(candidate, self._anchor_score(candidate, idea)) for candidate in candidates]
        scored.sort(key=lambda item: item[1], reverse=True)
        ranked: list[str] = []
        seen: set[str] = set()
        for candidate, sentence_score in scored:
            clause = self._best_clause_anchor(candidate, idea)
            preferred: list[str] = []
            if clause is not None:
                clause_score = self._anchor_score(clause, idea)
                if clause_score[0] >= sentence_score[0] - 0.05:
                    preferred.append(clause)
            if len(tokenize_for_match(candidate)) <= 60:
                preferred.append(candidate)
            elif clause:
                preferred.append(clause)
            for item in preferred or [candidate]:
                cleaned = clean_text(item)
                if not cleaned or cleaned in seen:
                    continue
                seen.add(cleaned)
                ranked.append(item)
        return ranked

    def _sentence_candidates(self, text: str) -> list[str]:
        cleaned = clean_text(text)
        if not cleaned:
            return []
        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?:;])\s+(?=[A-Z0-9\"'“(])", cleaned)
            if sentence.strip()
        ]
        candidates = [sentence for sentence in sentences if len(tokenize_for_match(sentence)) >= 5]
        return candidates or [cleaned]

    def _best_clause_anchor(self, sentence: str, idea: dict) -> str | None:
        clauses = [
            clause.strip()
            for clause in re.split(r"(?<=[,:;])\s+", sentence)
            if clause.strip()
        ]
        if len(clauses) <= 1:
            return None
        scored = sorted(clauses, key=lambda clause: self._anchor_score(clause, idea), reverse=True)
        for clause in scored:
            token_count = len(tokenize_for_match(clause))
            if 5 <= token_count <= 45:
                return clause
        return None

    def _anchor_score(self, text: str, idea: dict) -> tuple[float, int, int]:
        candidate_tokens = tokenize_for_match(text)
        if not candidate_tokens:
            return (0.0, 0, 0)
        candidate_text = " ".join(candidate_tokens)
        statement_tokens = tokenize_for_match(str(idea.get("statement", "")))
        statement_text = " ".join(statement_tokens)
        title_text = " ".join(tokenize_for_match(str(idea.get("title", ""))))
        statement_score = SequenceMatcher(a=statement_text, b=candidate_text).ratio() if statement_text else 0.0
        title_score = SequenceMatcher(a=title_text, b=candidate_text).ratio() if title_text else 0.0
        overlap = len(set(candidate_tokens) & set(statement_tokens))
        punctuation_bonus = 1 if re.search(r"[.!?:;](?:[\"')\]]*)$", text) else 0
        return (statement_score + title_score * 0.35 + overlap * 0.05 + punctuation_bonus * 0.02, overlap, -len(candidate_tokens))

    def _note_request_item(
        self,
        page_blocks: list[ExtractedBlock],
        document: ExtractedDocument,
        block: ExtractedBlock,
        highlight: HighlightSelection,
        key_ideas: list[dict],
    ) -> dict[str, str]:
        linked_ideas = self._linked_key_ideas(highlight.block_id, key_ideas)
        return {
            "highlight_id": highlight.highlight_id,
            "label": highlight.label,
            "section_title": block.section_title or "",
            "matched_quote": highlight.matched_quote,
            "local_context": self._note_context(page_blocks, block),
            "section_context": self._note_section_context(document, block),
            "paper_context": self._document_overview_context(document),
            "article_context": self._full_article_context(document),
            "idea_context": " | ".join(f"{idea['title']}: {idea['statement']}" for idea in linked_ideas)[:500],
            "focus_question": f"Explain the technical role of this highlighted passage in section {block.section_title or 'unknown section'}.",
        }

    def _linked_key_ideas(self, block_id: str, key_ideas: list[dict]) -> list[dict]:
        return [idea for idea in key_ideas if idea.get("block_id") == block_id][:2]

    def _note_context(self, page_blocks: list[ExtractedBlock], anchor: ExtractedBlock) -> str:
        try:
            index = next(i for i, block in enumerate(page_blocks) if block.block_id == anchor.block_id)
        except StopIteration:
            return anchor.text

        context_parts: list[str] = []
        for candidate in page_blocks[max(0, index - 1) : min(len(page_blocks), index + 2)]:
            if candidate.is_heading:
                continue
            if candidate.section_title != anchor.section_title:
                continue
            context_parts.append(candidate.text)
        context = " ".join(context_parts) if context_parts else anchor.text
        return context[:1400]

    def _note_section_context(self, document: ExtractedDocument, anchor: ExtractedBlock) -> str:
        if not self._has_useful_section_structure(document):
            return self._neighboring_block_context(document, anchor.page_number, anchor.block_id, 3000)
        context_parts: list[str] = []
        for page in document.pages:
            for block in page.blocks:
                if not block.words or block.is_heading or self._is_reference_block(block):
                    continue
                if block.section_title != anchor.section_title:
                    continue
                context_parts.append(block.text)
        context = " ".join(context_parts) if context_parts else anchor.text
        return context[:2400]

    def _document_overview_context(self, document: ExtractedDocument) -> str:
        parts: list[str] = []
        for page in document.pages:
            if page.is_reference_page:
                continue
            for block in page.blocks:
                if not block.words or self._is_reference_block(block):
                    continue
                if len(parts) >= 18:
                    break
                parts.append(block.text)
            if len(parts) >= 18:
                break
        return " ".join(parts)[:3200]

    def _full_article_context(self, document: ExtractedDocument) -> str:
        parts: list[str] = []
        for page in document.pages:
            if page.is_reference_page:
                continue
            for block in page.blocks:
                if not block.words or block.is_heading or self._is_reference_block(block):
                    continue
                parts.append(block.text)
        return " ".join(parts)[:18000]

    def _equation_request_item(
        self,
        document: ExtractedDocument,
        candidate: EquationCandidate,
        role: str,
    ) -> dict[str, str]:
        return {
            "equation_id": candidate.equation_id,
            "block_id": candidate.block_id,
            "page_number": candidate.page_number,
            "equation_label": candidate.equation_label,
            "equation_text_clean": candidate.equation_text_clean,
            "source_kind": candidate.source_kind,
            "section_title": candidate.section_title,
            "role": role,
            "local_context": candidate.local_context,
            "symbol_context": candidate.symbol_context,
            "page_context": self._equation_page_context(document, candidate),
            "section_context": self._equation_section_context(document, candidate),
            "paper_context": self._equation_paper_context(document, candidate),
            "article_context": self._full_article_context(document),
            "focus_question": self._equation_focus_question(candidate, role),
        }

    def _equation_page_context(self, document: ExtractedDocument, candidate: EquationCandidate) -> str:
        page = document.pages[candidate.page_number - 1]
        blocks = [block for block in page.blocks if block.words and not self._is_reference_block(block)]
        try:
            index = next(i for i, block in enumerate(blocks) if block.block_id == candidate.block_id)
        except StopIteration:
            return candidate.local_context
        context = " ".join(block.text for block in blocks[max(0, index - 4) : min(len(blocks), index + 5)])
        return context[:2600]

    def _equation_section_context(self, document: ExtractedDocument, candidate: EquationCandidate) -> str:
        if not self._has_useful_section_structure(document):
            return self._neighboring_block_context(document, candidate.page_number, candidate.block_id, 3600)
        context_parts: list[str] = []
        for page in document.pages:
            for block in page.blocks:
                if not block.words or block.is_heading or self._is_reference_block(block):
                    continue
                if block.section_title != candidate.section_title:
                    continue
                context_parts.append(block.text)
        context = " ".join(context_parts) if context_parts else candidate.local_context
        return context[:4200]

    def _equation_paper_context(self, document: ExtractedDocument, candidate: EquationCandidate) -> str:
        if not self._has_useful_section_structure(document):
            return self._document_overview_context(document)
        parts: list[str] = []
        seen_sections: set[str] = set()
        for page in document.pages:
            if page.is_reference_page:
                continue
            for block in page.blocks:
                if block.is_heading:
                    section = block.text.strip()
                    if self._structure.is_reference_heading(section):
                        continue
                    if section and section not in seen_sections:
                        parts.append(section)
                        seen_sections.add(section)
                    continue
                if not block.words or self._is_reference_block(block):
                    continue
                if len(parts) >= 18:
                    break
                parts.append(block.text)
            if len(parts) >= 18:
                break
        if candidate.section_title and candidate.section_title not in seen_sections:
            parts.append(candidate.section_title)
        return " ".join(parts)[:3200]

    def _equation_focus_question(self, candidate: EquationCandidate, role: str) -> str:
        label = candidate.equation_label or candidate.equation_id
        return (
            f"Explain exactly what equation {label} is doing in this paper as a {role}. "
            "Resolve symbols from the supplied page, section, and paper context before giving any interpretation."
        )

    def _has_useful_section_structure(self, document: ExtractedDocument) -> bool:
        section_titles = {
            block.section_title.strip()
            for page in document.pages
            for block in page.blocks
            if (
                block.words
                and not block.is_heading
                and not self._is_reference_block(block)
                and block.section_title
                and block.section_title.strip()
            )
        }
        return len(section_titles) >= 2

    def _neighboring_block_context(
        self,
        document: ExtractedDocument,
        page_number: int,
        block_id: str,
        char_limit: int,
    ) -> str:
        window_pages = range(max(1, page_number - 1), min(len(document.pages), page_number + 1) + 1)
        blocks = [
            block
            for number in window_pages
            for block in document.pages[number - 1].blocks
            if block.words and not block.is_heading and not self._is_reference_block(block)
        ]
        if not blocks:
            return ""
        try:
            index = next(i for i, block in enumerate(blocks) if block.block_id == block_id)
        except StopIteration:
            index = len(blocks) // 2
        window = blocks[max(0, index - 8) : min(len(blocks), index + 9)]
        return " ".join(block.text for block in window)[:char_limit]


class PaperCoachPipeline:
    def __init__(self, services: ServiceConfig) -> None:
        self._trace_writer: TraceWriter | None = None
        self._services = services

    def highlight_plan(self, run: RunConfig) -> HighlightPlan:
        self._prepare_workdir(run)
        run.trace_path.write_text("", encoding="utf-8")
        trace_writer = TraceWriter(run.trace_path)
        llm = ChatMockClient(self._services, trace_writer)
        llm.healthcheck()
        planner = HighlightPlanner(
            extractor=PdfExtractor(),
            prompt_library=PromptLibrary(),
            llm=llm,
            aligner=SpanAligner(),
            trace_writer=trace_writer,
        )
        plan = planner.build_plan(run)
        run.plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
        return plan

    def render_highlights(self, run: RunConfig, plan_path: Path | None = None) -> HighlightPlan:
        self._prepare_workdir(run)
        actual_plan_path = plan_path or run.plan_path
        plan = HighlightPlan.model_validate_json(actual_plan_path.read_text(encoding="utf-8"))
        renderer = PdfHighlightRenderer()
        renderer.render(run.input_pdf, run.out_pdf, plan, run.margin_width, run.max_notes_per_page, run.max_equations_per_page)
        self._write_manifest(run, plan, self._services.model)
        return plan

    def highlight(self, run: RunConfig) -> HighlightPlan:
        plan = self.highlight_plan(run)
        self.render_highlights(run, run.plan_path)
        return plan

    def _prepare_workdir(self, run: RunConfig) -> None:
        if not run.input_pdf.exists():
            raise FileNotFoundError(f"Input PDF not found: {run.input_pdf}")
        run.workdir.mkdir(parents=True, exist_ok=True)
        run.out_pdf.parent.mkdir(parents=True, exist_ok=True)

    def _write_manifest(self, run: RunConfig, plan: HighlightPlan, model_name: str | None = None) -> None:
        highlights = [highlight for page in plan.pages for highlight in page.highlights]
        notes = [note for page in plan.pages for note in page.notes]
        equations = [equation for page in plan.pages for equation in page.equations]
        equation_notes = [note for page in plan.pages for note in page.equation_notes]
        manifest = RunManifest(
            input_pdf=str(run.input_pdf),
            output_pdf=str(run.out_pdf),
            plan_path=str(run.plan_path),
            trace_path=str(run.trace_path),
            model=model_name or self._services.model,
            highlight_count=len(highlights),
            pages_with_highlights=sum(1 for page in plan.pages if page.highlights),
            note_count=len(notes),
            equation_count=len(equations),
            equation_note_count=len(equation_notes),
        )
        run.manifest_path.write_text(manifest.model_dump_json(indent=2), encoding="utf-8")


def build_default_out_path(input_pdf: Path) -> Path:
    slug = slugify(input_pdf.stem)
    return Path("output/pdf") / f"{slug}-highlighted.pdf"


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "paper"
