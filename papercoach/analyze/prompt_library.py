from __future__ import annotations

import re

from papercoach.models import EvidenceRef
from papercoach.analyze.text_clean import clean_extracted_text

NOTE_KIND_GUIDANCE: dict[str, str] = {
    "section_tldr": "Summarize the section goal and the key technical move in this local block.",
    "section_heading": "Explain what this section heading introduces in nearby text.",
    "theorem_like": "State what the theorem/definition is about and why it is used here.",
    "proof": "Explain the proof direction and which assumptions are being used.",
    "proof_skip": "Explain the omitted step and what would need verification.",
    "equation": "Explain what the equation expresses and how it connects to surrounding prose.",
    "citation_trace": (
        "Explain what imported idea is referenced, how the paper adapts it, and the first-principles link"
        " from the cited concept to this local derivation."
    ),
    "page_tldr": "Summarize the core technical point in this page region.",
    "page_focus": "Explain the local technical claim and why it matters for the paper's estimation pipeline.",
}

_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "from",
    "this",
    "that",
    "into",
    "over",
    "under",
    "then",
    "than",
    "are",
    "was",
    "were",
    "have",
    "has",
    "had",
    "not",
    "can",
    "will",
    "you",
    "your",
    "their",
    "its",
    "our",
    "model",
    "paper",
    "method",
    "methods",
    "result",
    "results",
    "extends",
    "introduces",
    "presents",
    "focuses",
    "shows",
    "using",
    "used",
    "based",
}

_SYMBOL_RE = re.compile(r"\b[A-Za-z](?:[A-Za-z0-9_']{0,12})\b")
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-']+")
_DEFINITION_PATTERNS = [
    r"\b{term}\b\s+(?:is|are|means|denotes|refers to)\b",
    r"\b(?:let|define|denote|called)\b[^.:\n]{{0,40}}\b{term}\b",
]
_TERM_TAILS = {
    "filter",
    "filtering",
    "estimator",
    "estimation",
    "covariance",
    "likelihood",
    "dynamics",
    "model",
    "models",
    "equation",
    "equations",
    "algorithm",
    "algorithms",
    "recursion",
    "recursions",
    "objective",
    "posterior",
    "prior",
    "observation",
    "observations",
    "variance",
    "matrix",
    "matrices",
}


def _trim_line(text: str, limit: int = 220) -> str:
    compact = clean_extracted_text(text)
    return compact[:limit]


def _extract_notation(anchor_text: str, context: str, evidence: list[EvidenceRef], max_items: int = 10) -> list[str]:
    corpus = [clean_extracted_text(anchor_text), clean_extracted_text(context)]
    corpus.extend((e.quote or "") for e in evidence)
    out: list[str] = []
    seen: set[str] = set()
    for text in corpus:
        for tok in _SYMBOL_RE.findall(text):
            low = tok.lower()
            if low in _STOPWORDS:
                continue
            has_subscript = "_" in tok
            has_digit = any(ch.isdigit() for ch in tok)
            is_single_var = len(tok) == 1 and tok.lower() not in {"a", "i"}
            is_short_upper = tok.isupper() and len(tok) <= 4
            if not (has_subscript or has_digit or is_single_var or is_short_upper):
                continue
            key = tok.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(tok)
            if len(out) >= max_items:
                return out
    return out


def _extract_scope_terms(anchor_text: str, context: str, evidence: list[EvidenceRef], max_items: int = 6) -> list[str]:
    texts = [clean_extracted_text(anchor_text), clean_extracted_text(context)]
    texts.extend((e.quote or "") for e in evidence)
    seen: set[str] = set()
    candidates: list[str] = []
    for text in texts:
        words = [w.lower() for w in _WORD_RE.findall(text)]
        for i in range(len(words) - 1):
            a, b = words[i], words[i + 1]
            if a in _STOPWORDS or b in _STOPWORDS:
                continue
            if len(a) < 4 or len(b) < 4:
                continue
            if b not in _TERM_TAILS and not b.endswith(
                ("tion", "sion", "ance", "ence", "ity", "ics", "ism", "ment", "ness")
            ):
                continue
            phrase = f"{a} {b}"
            if phrase in seen:
                continue
            seen.add(phrase)
            candidates.append(phrase)
            if len(candidates) >= max_items:
                return candidates
    return candidates


def _has_local_definition(term: str, anchor_text: str, context: str, evidence: list[EvidenceRef]) -> bool:
    corpus = "\n".join([anchor_text, context] + [(e.quote or "") for e in evidence]).lower()
    escaped = re.escape(term.lower())
    for pattern in _DEFINITION_PATTERNS:
        if re.search(pattern.format(term=escaped), corpus):
            return True
    return False


def _scope_constraints(anchor_text: str, context: str, evidence: list[EvidenceRef]) -> str:
    terms = _extract_scope_terms(anchor_text, context, evidence)
    no_definition_terms = [t for t in terms if not _has_local_definition(t, anchor_text, context, evidence)]
    if not no_definition_terms:
        term_line = "- Avoid broad textbook framing; explain only what this passage adds or changes."
    else:
        term_line = (
            "- Do not define baseline terms unless locally defined in evidence: "
            + ", ".join(no_definition_terms)
            + "."
        )
    return (
        "Scope calibration:\n"
        "- Assume a technically fluent reader in this paper's field.\n"
        "- Explain local role and consequences, not generic introductions.\n"
        f"{term_line}\n"
        "- Prefer specifics (assumptions, parameterization, update steps, caveats) over background."
    )


def build_note_prompt(anchor_text: str, context: str, evidence: list[EvidenceRef], note_kind: str) -> str:
    evidence_ids = [f"e{i}" for i in range(len(evidence))]
    evidence_lines = []
    for i, ev in enumerate(evidence):
        quote = _trim_line(ev.quote or "[no quote available]")
        evidence_lines.append(f"e{i}: {quote}")

    notation = _extract_notation(anchor_text, context, evidence)
    notation_line = ", ".join(notation) if notation else "[none identified]"
    task_brief = NOTE_KIND_GUIDANCE.get(note_kind, "Explain the anchored text in plain, grounded terms.")
    scope_block = _scope_constraints(anchor_text, context, evidence)

    return (
        f"Task type: {note_kind}\n"
        f"Task brief: {task_brief}\n"
        "Write 70-110 words. First sentence plain-language meaning, second sentence technical role.\n"
        f"{scope_block}\n"
        "Problem breakdown:\n"
        "1) Identify the exact claim in the anchor.\n"
        "2) Reuse notation exactly as shown (no renaming).\n"
        "3) Connect the claim to nearby context with evidence IDs.\n\n"
        f"Anchor text:\n{_trim_line(anchor_text, 300)}\n\n"
        f"Local context:\n{_trim_line(context, 600)}\n\n"
        f"Notation to preserve:\n{notation_line}\n\n"
        f"Evidence quotes:\n{chr(10).join(evidence_lines)}\n\n"
        f"Allowed evidence IDs: {', '.join(evidence_ids)}\n"
        "Hard rules:\n"
        "- Do not introduce external facts.\n"
        "- Body must include at least one preserved notation token when available.\n"
        "- Normalize obvious extraction artifacts in prose (e.g., split words) when the intended token is clear.\n"
        "- If evidence is weak, state uncertainty explicitly.\n"
        "- Use only allowed evidence IDs.\n\n"
        "Return strict JSON with title/body/key_points/evidence_used/confidence/uncertainties."
    )
