from __future__ import annotations

import re

from papercoach.analyze.prompt_library import build_note_prompt
from papercoach.analyze.text_clean import clean_extracted_text
from papercoach.models import EvidenceRef, MarginNote, TextBlock

SKIP_RE = re.compile(
    r"\b(clearly|obvious|obviously|straightforward|we omit|it follows|standard argument)\b",
    re.IGNORECASE,
)
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
GENERIC_TITLE_RE = re.compile(
    r"^(summarize.*|section tldr|page tldr|local technical claim(?:[: ].*)?|local technical claim explanation|guidance note)$",
    re.IGNORECASE,
)
NOISY_TITLE_RE = re.compile(r"(tldr|local context|technical focus:|[^A-Za-z0-9\s:\-()])", re.IGNORECASE)
GENERIC_BODY_PREFIX_RE = re.compile(
    r"^(?:the\s+)?(?:(?:local|core)\s+)?(?:(?:technical|section)\s+)?(?:claim|point)\s+(?:states|is)\s+that\s+",
    re.IGNORECASE,
)
SECTION_GOAL_PREFIX_RE = re.compile(r"^the goal of this section is to\s+", re.IGNORECASE)
PAPER_CLAIM_PREFIX_RE = re.compile(r"^the paper claims that\s+", re.IGNORECASE)
HEADINGISH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\s\-']{2,72}$")


def _clean_generated_text(text: str) -> str:
    text = MARKDOWN_LINK_RE.sub(r"\1", text)
    return clean_extracted_text(text)


def _derived_title(anchor_text: str, note_kind: str) -> str:
    cleaned_anchor = clean_extracted_text(anchor_text)
    lower = cleaned_anchor.lower()
    if "kalman" in lower and "hmm" in lower:
        return "Kalman and HMM connection"
    if "log likelihood" in lower:
        return "Expected log-likelihood update"
    if "initial state covariance" in lower or ("covariance" in lower and "initial" in lower):
        return "Initial state covariance estimation"
    if "input" in lower and "output" in lower:
        return "Input-output extension"
    if "em algorithm" in lower:
        return "EM parameter estimation"
    if "factor analysis" in lower:
        return "Factor-analysis relation"
    if note_kind == "section_tldr":
        first_clause = cleaned_anchor.split(".", 1)[0].strip(" :;,-")
        if HEADINGISH_RE.match(first_clause):
            words = first_clause.split()
            if 2 <= len(words) <= 7:
                return " ".join(words)

    if note_kind == "citation_trace":
        return "Imported idea reference"
    if note_kind == "section_tldr":
        return "Section focus"
    if note_kind in {"page_focus", "page_tldr"}:
        return "Technical point"
    return "Guidance note"


def _normalize_body(body: str) -> str:
    out = clean_extracted_text(body)
    out = GENERIC_BODY_PREFIX_RE.sub("", out)
    out = SECTION_GOAL_PREFIX_RE.sub("", out)
    out = PAPER_CLAIM_PREFIX_RE.sub("", out)
    if out:
        out = out[0].upper() + out[1:]
    return out

def validate_generated_note(note_json: dict, allowed_evidence_ids: set[str]) -> dict:
    missing = {k for k in ["title", "body", "key_points", "evidence_used", "confidence", "uncertainties"] if k not in note_json}
    if missing:
        raise RuntimeError(f"Ollama note missing keys: {sorted(missing)}")

    used = set(note_json.get("evidence_used", []))
    if not used.issubset(allowed_evidence_ids):
        raise RuntimeError("Ollama note used unknown evidence IDs")

    body = str(note_json.get("body", ""))
    if re.search(r"\bwe prove|therefore the theorem proves|new theorem\b", body, re.IGNORECASE):
        raise RuntimeError("Unsupported claim detected in generated note")

    if not used and float(note_json.get("confidence", 0.0)) > 0.35:
        raise RuntimeError("Confidence policy violated: no evidence and confidence > 0.35")

    if not used and "can't" not in body.lower() and "uncertain" not in body.lower() and "likely" not in body.lower():
        raise RuntimeError("No-evidence note must include uncertainty language")

    return note_json


def generate_note(
    ollama_client,
    page: int,
    anchor_bbox: list[float],
    anchor_text: str,
    context: str,
    evidence: list[EvidenceRef],
    note_kind: str,
) -> MarginNote:
    evidence_ids = [f"e{i}" for i in range(len(evidence))]
    allowed_ids = set(evidence_ids)

    prompt = build_note_prompt(anchor_text, context, evidence, note_kind)
    generated = ollama_client.structured_note(prompt)
    if isinstance(generated.get("evidence_used"), list):
        generated["evidence_used"] = [eid for eid in generated["evidence_used"] if eid in allowed_ids]
    if evidence_ids and not generated.get("evidence_used"):
        generated["evidence_used"] = [evidence_ids[0]]

    used_after_filter = set(generated.get("evidence_used", []))
    if not used_after_filter:
        try:
            if float(generated.get("confidence", 0.0)) > 0.35:
                generated["confidence"] = 0.35
        except (TypeError, ValueError):
            generated["confidence"] = 0.35

        body = str(generated.get("body", ""))
        if "can't" not in body.lower() and "uncertain" not in body.lower() and "likely" not in body.lower():
            generated["body"] = (body + " This interpretation is uncertain without explicit evidence.").strip()
        uncertainties = generated.get("uncertainties")
        if not isinstance(uncertainties, list):
            uncertainties = []
        if not uncertainties:
            uncertainties = ["No direct evidence ID was returned by the model."]
        generated["uncertainties"] = uncertainties

    try:
        confidence = float(generated.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    generated["confidence"] = max(0.0, min(1.0, confidence))

    validated = validate_generated_note(generated, allowed_ids)

    used_ids = set(validated.get("evidence_used", []))
    used_evidence: list[EvidenceRef] = [e for i, e in enumerate(evidence) if f"e{i}" in used_ids]

    title = _clean_generated_text(str(validated["title"]))
    if not title or GENERIC_TITLE_RE.match(title) or NOISY_TITLE_RE.search(title):
        title = _derived_title(anchor_text, note_kind)
    body = _normalize_body(_clean_generated_text(str(validated["body"])))
    if not body:
        body = "Interpretation is uncertain due to limited extracted evidence."

    return MarginNote(
        page=page,
        anchor_bbox=anchor_bbox,
        note_bbox=None,
        title=title,
        body=body,
        key_points=[str(x).strip() for x in validated.get("key_points", []) if str(x).strip()],
        evidence=used_evidence,
        confidence=float(validated["confidence"]),
        uncertainties=[str(x).strip() for x in validated.get("uncertainties", []) if str(x).strip()],
        flags=[note_kind],
    )


def build_skip_notes(blocks: list[TextBlock]) -> list[tuple[TextBlock, list[EvidenceRef], str]]:
    out: list[tuple[TextBlock, list[EvidenceRef], str]] = []
    for b in blocks:
        if SKIP_RE.search(b.text):
            evidence = [
                EvidenceRef(
                    type="paper",
                    pointer={"page": b.page, "block_id": b.block_id},
                    quote=b.text[:250],
                )
            ]
            out.append((b, evidence, "proof_skip"))
    return out
