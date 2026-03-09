"""Prompt library for highlight planning.

Sources:
- https://platform.openai.com/docs/api-reference/responses
- https://github.com/RayBytes/ChatMock
- https://platform.openai.com/docs/guides/text?api-mode=responses
- https://aclanthology.org/2020.sdp-1.16.pdf
- https://matplotlib.org/stable/users/explain/text/mathtext.html
"""

from __future__ import annotations

import json

from papercoach.extract.equations import EquationCandidate
from papercoach.extract.extractor import ExtractedBlock, ExtractedDocument
from papercoach.models import PromptProfile

_SOURCE_LINKS = [
    "https://pymupdf.readthedocs.io/en/latest/recipes-text.html",
    "https://platform.openai.com/docs/api-reference/responses",
    "https://github.com/RayBytes/ChatMock",
    "https://aclanthology.org/2020.sdp-1.16.pdf",
    "https://matplotlib.org/stable/users/explain/text/mathtext.html",
]

_ALLOWED_LABELS = ["contribution", "method", "result", "setup", "limitation", "definition"]
_EQUATION_ROLES = ["objective", "definition", "transition", "update", "constraint", "result"]


class PromptLibrary:
    def _field(self, item: object, name: str, default=None):
        if isinstance(item, dict):
            return item.get(name, default)
        return getattr(item, name, default)

    def profile(self, density: str, audience: str, style: str) -> PromptProfile:
        if density != "balanced":
            raise ValueError("Phase 1 only supports balanced density")
        if audience != "paper-native":
            raise ValueError("Phase 1 only supports paper-native audience")
        if style != "minimal":
            raise ValueError("Phase 1 only supports minimal style")
        return PromptProfile(density=density, audience=audience, style=style, source_links=_SOURCE_LINKS)

    def key_idea_prompt(
        self,
        document: ExtractedDocument,
        blocks: list[ExtractedBlock],
        target_ideas: int,
    ) -> tuple[str, str]:
        payload = {
            "task_kind": "key_idea_extraction",
            "paper_title": document.title,
            "target_ideas": target_ideas,
            "allowed_labels": _ALLOWED_LABELS,
            "blocks": [
                {
                    "block_id": block.block_id,
                    "page_number": block.page_number,
                    "section_title": block.section_title,
                    "text": block.text,
                    "word_count": block.word_count,
                }
                for block in blocks
            ],
        }
        system = (
            "You identify the key ideas in a research paper before any annotation is written. "
            "Return strict JSON only."
        )
        user = (
            "TASK_KIND: key_idea_extraction\n"
            "Read the whole paper and extract the central ideas a strong technical reader should track.\n"
            "Prefer ideas that define the paper's thesis, method, objectives, assumptions, update rules, evaluation logic, central results, or explicit limitations.\n"
            "Do not list section headings, generic motivation, or repeated restatements of the same contribution.\n"
            "Each idea must be tied to one supporting source block from the paper.\n"
            'Return JSON: {"ideas":[{"idea_id":"idea-1","title":"...","statement":"...","label":"method","block_id":"...","confidence":0.0}]}\n'
            "PAYLOAD_JSON_START\n"
            f"{json.dumps(payload, ensure_ascii=True)}\n"
            "PAYLOAD_JSON_END"
        )
        return (system, user)

    def document_selection_prompts(
        self,
        blocks: list[ExtractedBlock],
        document: ExtractedDocument,
        target_highlights: int,
        key_ideas: list[dict] | None = None,
    ) -> tuple[str, str]:
        payload = {
            "task_kind": "document_selection",
            "title": document.title,
            "page_count": len(document.pages),
            "target_highlights": target_highlights,
            "allowed_labels": _ALLOWED_LABELS,
            "key_ideas": key_ideas or [],
            "blocks": [
                {
                    "block_id": block.block_id,
                    "page_number": block.page_number,
                    "section_title": block.section_title,
                    "text": block.text,
                    "word_count": block.word_count,
                }
                for block in blocks
            ],
        }
        system = (
            "You select the most study-worthy passages in an entire research paper. "
            "Match the technical level of the paper itself. Return strict JSON only."
        )
        user = (
            "TASK_KIND: document_selection\n"
            "You are given the paper text as ordered blocks for the full paper.\n"
            "Choose the most important passages to highlight for studying the paper.\n"
            "Use the whole document context when deciding what matters, but select passage-local text.\n"
            "Use the extracted key ideas to drive coverage. Prefer at least one strong quote for each central idea when the paper supports it.\n"
            "Prefer claims that change understanding of the paper: contribution statements, objective definitions, assumptions, approximations, update rules, empirical findings, and explicit limitations.\n"
            "Avoid generic motivation, transitions, repeated restatements of the same contribution, bibliography entries, and redundant variants of the same point.\n"
            "Distribute selections across the paper instead of overloading a single page or section.\n"
            "Each selection must include an exact contiguous quote copied from one block text.\n"
            "The quote should usually be a single complete sentence. Use two short adjacent sentences only when one sentence alone is incomplete.\n"
            "Do not return dangling fragments that end in unfinished function words such as 'of the', 'with', 'and', or 'to'.\n"
            'Return JSON: {"selections":[{"block_id":"...","label":"...","rationale":"...","confidence":0.0,"selected_quote":"..."}]}\n'
            "PAYLOAD_JSON_START\n"
            f"{json.dumps(payload, ensure_ascii=True)}\n"
            "PAYLOAD_JSON_END"
        )
        return (system, user)

    def equation_candidate_prompt(
        self,
        document: ExtractedDocument,
        candidates: list[EquationCandidate] | list[dict],
    ) -> tuple[str, str]:
        payload = {
            "task_kind": "equation_candidate_screen",
            "paper_title": document.title,
            "candidates": [
                {
                    "equation_id": self._field(candidate, "equation_id"),
                    "block_id": self._field(candidate, "block_id"),
                    "page_number": self._field(candidate, "page_number"),
                    "equation_text_clean": self._field(candidate, "equation_text_clean"),
                    "equation_label": self._field(candidate, "equation_label"),
                    "source_kind": self._field(candidate, "source_kind"),
                    "section_title": self._field(candidate, "section_title"),
                    "local_context": self._field(candidate, "local_context"),
                    "symbol_context": self._field(candidate, "symbol_context"),
                    "page_context": self._field(candidate, "page_context"),
                    "section_context": self._field(candidate, "section_context"),
                    "paper_context": self._field(candidate, "paper_context"),
                    "focus_question": self._field(candidate, "focus_question"),
                    "quality_score": self._field(candidate, "quality_score", 0.5),
                }
                for candidate in candidates
            ],
        }
        system = (
            "You identify which displayed formulas in a research paper deserve study attention. "
            "Ground math in the paper's own surrounding text and return strict JSON only."
        )
        user = (
            "TASK_KIND: equation_candidate_screen\n"
            "For each candidate equation, decide whether it is mathematically central enough to consider for explanation.\n"
            "Keep only equations that define the model, objective, state transition, observation rule, update step, constraint, or a key result.\n"
            "Reject decorative, purely algebraic intermediate, redundant, or heavily garbled equations when the local context is too weak to ground them.\n"
            "Prefer omission over speculative reconstruction: if the visible equation text is too broken to support a PhD-level gloss, do not keep it.\n"
            "Assign a local role from the allowed set only when keep=true.\n"
            f"Allowed roles: {', '.join(_EQUATION_ROLES)}.\n"
            'Return JSON: {"candidates":[{"equation_id":"...","keep":true,"role":"objective","rationale":"...","confidence":0.0}]}\n'
            "PAYLOAD_JSON_START\n"
            f"{json.dumps(payload, ensure_ascii=True)}\n"
            "PAYLOAD_JSON_END"
        )
        return (system, user)

    def equation_selection_prompt(
        self,
        document: ExtractedDocument,
        screened_candidates: list[dict],
        max_equations_per_page: int,
    ) -> tuple[str, str]:
        payload = {
            "task_kind": "equation_selection",
            "paper_title": document.title,
            "max_equations_per_page": max_equations_per_page,
            "candidates": screened_candidates,
        }
        system = (
            "You choose the most study-worthy equations in a research paper. "
            "Prefer sparse, non-redundant math coverage and return strict JSON only."
        )
        user = (
            "TASK_KIND: equation_selection\n"
            "Select the equations that a technically fluent reader should stop and understand.\n"
            "Prefer one or two equations per important page, avoid repeats, and cover distinct mathematical roles.\n"
            "Prefer equations with stronger local grounding and cleaner visible structure when mathematical importance is similar.\n"
            "Avoid low-quality candidates whose extraction is too garbled to support a faithful explanation.\n"
            "Do not select an equation merely because the surrounding heading names a parameter if the displayed row itself is too corrupted to explain non-speculatively.\n"
            "Each kept equation must remain grounded in its local context rather than textbook conventions.\n"
            'Return JSON: {"selections":[{"equation_id":"...","role":"transition","reason":"...","confidence":0.0}]}\n'
            "PAYLOAD_JSON_START\n"
            f"{json.dumps(payload, ensure_ascii=True)}\n"
            "PAYLOAD_JSON_END"
        )
        return (system, user)

    def equation_explanation_prompt(
        self,
        document: ExtractedDocument,
        page_number: int,
        equations: list[dict],
    ) -> tuple[str, str]:
        payload = {
            "task_kind": "equation_explanation",
            "paper_title": document.title,
            "page_number": page_number,
            "equations": equations,
        }
        system = (
            "You explain equations in research papers for a technically fluent reader. "
            "Ground every claim in nearby text and return strict JSON only."
        )
        user = (
            "TASK_KIND: equation_explanation\n"
            "Write one compact explanation per selected equation.\n"
            "Treat each equation as a specific target inside the full article, not as an isolated formula.\n"
            "You are given a dossier with the exact target equation plus local context, page context, section context, compact paper context, the full article text, and a focus question for that exact equation.\n"
            "Use the full article only to resolve intent and notation; the explanation itself must stay about the specific target equation.\n"
            "Resolve symbols from local_context first, then page_context, then section_context, then paper_context, then article_context.\n"
            "Do not invent symbol meanings. Leave symbols unmapped if the supplied contexts do not define them.\n"
            "Do not give a textbook tutorial. Stay local to the paper's argument and answer the focus question for the specific equation in the payload.\n"
            "Return a display_latex field with valid LaTeX math for the equation or the exact local formula being explained. Do not wrap it in $ delimiters.\n"
            "The symbol_map keys must also be valid LaTeX math snippets for the paper's notation. Use values only for locally grounded meanings.\n"
            "Keep plain_explanation and intuition_or_consequence mostly prose. If you mention notation there, keep it minimal because rendered math is shown separately.\n"
            f"Use one role from: {', '.join(_EQUATION_ROLES)}.\n"
            'Return JSON: {"explanations":[{"equation_id":"...","title":"...","display_latex":"\\\\hat{x}_t = A x_{t-1}","symbol_map":{"x_t":"latent state"},"equation_role":"transition","plain_explanation":"...","intuition_or_consequence":"...","confidence":0.0}]}\n'
            "PAYLOAD_JSON_START\n"
            f"{json.dumps(payload, ensure_ascii=True)}\n"
            "PAYLOAD_JSON_END"
        )
        return (system, user)

    def equation_evaluation_prompt(
        self,
        document: ExtractedDocument,
        page_number: int,
        equations: list[dict],
    ) -> tuple[str, str]:
        payload = {
            "task_kind": "equation_evaluation",
            "paper_title": document.title,
            "page_number": page_number,
            "equations": equations,
        }
        system = (
            "You audit equation explanations for local grounding and notation fidelity. "
            "Return strict JSON only."
        )
        user = (
            "TASK_KIND: equation_evaluation\n"
            "Evaluate each explanation against the equation dossier: local context, page context, section context, paper context, article context, and focus question.\n"
            "Fail an explanation if it invents symbol meanings, drifts from the paper's notation, gives invalid or misleading LaTeX math, or says only generic textbook facts.\n"
            'Return JSON: {"evaluations":[{"equation_id":"...","pass":true,"feedback":"...","confidence":0.0}]}\n'
            "PAYLOAD_JSON_START\n"
            f"{json.dumps(payload, ensure_ascii=True)}\n"
            "PAYLOAD_JSON_END"
        )
        return (system, user)

    def note_prompt(
        self,
        document: ExtractedDocument,
        page_number: int,
        highlights: list[dict],
    ) -> tuple[str, str]:
        payload = {
            "task_kind": "page_note_generation",
            "paper_title": document.title,
            "page_number": page_number,
            "highlights": highlights,
        }
        system = (
            "You write concise study notes for research papers. "
            "Match the paper's technical level, stay local to the quoted passage, and return strict JSON only."
        )
        user = (
            "TASK_KIND: page_note_generation\n"
            "Write one clear margin note for each listed highlight.\n"
            "Treat each highlight as a specific target line or idea inside the full paper.\n"
            "Each note should help a technically fluent reader understand the local technical role of the quoted passage in this paper.\n"
            "You are given local context, section context, compact paper context, the full article text, a linked key idea when available, and a focus question for each highlight.\n"
            "Use the full article only to understand what the target passage is doing. Keep the written note local to the highlighted passage itself rather than summarizing the whole paper.\n"
            "If a linked key idea is provided, use it to keep the note centered on the paper's main argument rather than on a secondary detail.\n"
            "Preserve notation when it matters, and explain one concrete thing: the assumption, objective, approximation, update, contrast, or consequence fixed by the passage.\n"
            "Do not add outside facts. Do not drift into generic textbook explanation.\n"
            "Do not write review-summary prose such as 'This paper's central contribution', 'This sentence states', 'This line introduces', or 'This result shows' unless the quote itself is explicitly making that claim.\n"
            "Do not use LaTeX, backslashes, or escaped math delimiters. If notation matters, write it in plain text such as x_t, p(y), or log P(x,y).\n"
            "Write like a sharp margin gloss for a PhD reader, not an abstract.\n"
            "Prefer a single dense sentence. Use a second short sentence only if it adds an immediate consequence that the first sentence cannot carry.\n"
            "Each note should be 18 to 40 words total.\n"
            "Each title must be 2 to 5 words and name the technical move or concept, not a generic takeaway.\n"
            'Return JSON: {"notes":[{"highlight_id":"...","title":"...","body":"...","confidence":0.0}]}\n'
            "PAYLOAD_JSON_START\n"
            f"{json.dumps(payload, ensure_ascii=True)}\n"
            "PAYLOAD_JSON_END"
        )
        return (system, user)
