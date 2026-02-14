from __future__ import annotations

import re

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_SPACED_CHAR_CHAIN_RE = re.compile(r"\b(?:[A-Za-z]\s+){2,}[A-Za-z]\b")
_SHORT_FRAGMENT_CHAIN_RE = re.compile(r"\b(?:[A-Za-z]{1,2}\s+){2,}[A-Za-z]{1,2}\b")
_SHORT_CHAIN_WITH_LONG_TAIL_RE = re.compile(r"\b(?:[A-Za-z]{1,2}\s+){2,}[A-Za-z]{3,}\b")
_CAPITAL_TAIL_RE = re.compile(r"\b([A-Z][a-z]{2,})\s+([a-z]{1,2})\b")
_LOWER_TAIL_RE = re.compile(r"\b([a-z]{4,})\s+([a-z])\b")
_SUFFIX_SPLIT_RE = re.compile(
    r"\b([a-z]{3,})\s+(ations?|ation|tions?|tion|ments?|ment|ness|ality|ities?|ity|ances?|ence|ences|ing|ed|er|ers|ive|ally|al|ous)\b"
)
_CHAIN_BLACKLIST = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "if",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "we",
    "with",
}
_TAIL_CONNECTOR_BLACKLIST = {"a", "an", "as", "at", "by", "for", "in", "is", "of", "on", "or", "to", "we", "with"}
_STUCK_CONNECTOR_RE = re.compile(r"\b([A-Za-z]{4,})(of|to|in|for|and|with)([A-Z][A-Za-z]{2,})\b")
_STUCK_PRONOUN_AUX_RE = re.compile(
    r"\b(This|this|That|that|It|it|There|there|Here|here)(is|are|was|were|can|could|will|would|has|have|had)\b"
)
_STUCK_MATH_TAIL_RE = re.compile(r"\b([xyzuvwprqmnk][a-z0-9_']{0,3})(that|which|is|are|was|were)\b", re.IGNORECASE)
_TARGETED_FIXES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bKalman lter\b", re.IGNORECASE), "Kalman filter"),
    (re.compile(r"\bWerst\b"), "We first"),
    (re.compile(r"\bTheab\b"), "The above"),
    (re.compile(r"\bforma\b", re.IGNORECASE), "form a"),
    (re.compile(r"\bprovidesa\b", re.IGNORECASE), "provides a"),
    (re.compile(r"\brequiresa\b", re.IGNORECASE), "requires a"),
    (re.compile(r"\bbecomesa\b", re.IGNORECASE), "becomes a"),
)


def _join_spaced_chars(match: re.Match[str]) -> str:
    return "".join(match.group(0).split())


def _join_fragment_chain(match: re.Match[str]) -> str:
    raw = match.group(0)
    tokens = raw.split()
    if any(t.lower() in _CHAIN_BLACKLIST for t in tokens):
        return raw
    return "".join(tokens)


def _join_capital_tail(match: re.Match[str]) -> str:
    head = match.group(1)
    tail = match.group(2)
    if tail.lower() in _TAIL_CONNECTOR_BLACKLIST:
        return f"{head} {tail}"
    return f"{head}{tail}"


def clean_extracted_text(text: str) -> str:
    out = _CONTROL_RE.sub(" ", text)
    out = re.sub(r"\s+", " ", out).strip()
    out = _SPACED_CHAR_CHAIN_RE.sub(_join_spaced_chars, out)
    out = _SHORT_FRAGMENT_CHAIN_RE.sub(_join_fragment_chain, out)
    out = _SHORT_CHAIN_WITH_LONG_TAIL_RE.sub(_join_fragment_chain, out)

    previous = ""
    while out != previous:
        previous = out
        out = _LOWER_TAIL_RE.sub(r"\1\2", out)
        out = _SUFFIX_SPLIT_RE.sub(r"\1\2", out)
        out = _CAPITAL_TAIL_RE.sub(_join_capital_tail, out)
        out = _STUCK_CONNECTOR_RE.sub(r"\1 \2 \3", out)
        out = _STUCK_PRONOUN_AUX_RE.sub(r"\1 \2", out)
        out = _STUCK_MATH_TAIL_RE.sub(r"\1 \2", out)
        out = re.sub(r"\(\s*[,;:]*\s*\)", "", out)
        out = re.sub(r"\s+", " ", out).strip()
    for pattern, replacement in _TARGETED_FIXES:
        out = pattern.sub(replacement, out)
    return out
