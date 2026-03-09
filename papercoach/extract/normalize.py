from __future__ import annotations

import re
import unicodedata

_WHITESPACE_RE = re.compile(r"\s+")
_EDGE_PUNCT_RE = re.compile(r"^[^\w]+|[^\w]+$")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_TOKEN_RE = re.compile(r"[0-9A-Za-z\u0370-\u03FF]+(?:[-'][0-9A-Za-z\u0370-\u03FF]+)*")

_COMMON_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "this",
    "to",
    "was",
    "we",
    "with",
}

_JOINABLE_COMMON_PAIRS = {
    ("in", "to"),
}

_CHAR_MAP = str.maketrans(
    {
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\ufb00": "ff",
        "\ufb01": "fi",
        "\ufb02": "fl",
        "\ufb03": "ffi",
        "\ufb04": "ffl",
    }
)


def clean_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text).translate(_CHAR_MAP)
    normalized = _CONTROL_RE.sub("", normalized)
    return _WHITESPACE_RE.sub(" ", normalized).strip()


def repair_extracted_text(text: str) -> str:
    repaired, _ranges = repair_token_sequence(clean_text(text).split(" "))
    return " ".join(token for token in repaired if token)


def repair_token_sequence(tokens: list[str]) -> tuple[list[str], list[tuple[int, int]]]:
    filtered_tokens = [token for token in tokens if token]
    repaired_tokens = filtered_tokens[:]
    ranges = [(index, index + 1) for index in range(len(filtered_tokens))]
    changed = True
    while changed:
        changed = False
        merged_tokens: list[str] = []
        merged_ranges: list[tuple[int, int]] = []
        index = 0
        while index < len(repaired_tokens):
            current = repaired_tokens[index]
            if index + 1 < len(repaired_tokens) and _should_merge_fragment(current, repaired_tokens[index + 1]):
                merged_tokens.append(f"{current}{repaired_tokens[index + 1]}")
                merged_ranges.append((ranges[index][0], ranges[index + 1][1]))
                index += 2
                changed = True
                continue
            merged_tokens.append(current)
            merged_ranges.append(ranges[index])
            index += 1
        repaired_tokens = merged_tokens
        ranges = merged_ranges
    return repaired_tokens, ranges


def _should_merge_fragment(left: str, right: str) -> bool:
    left_core = _EDGE_PUNCT_RE.sub("", left)
    right_core = _EDGE_PUNCT_RE.sub("", right)
    if not left_core or not right_core:
        return False
    if not left_core.isalpha() or not right_core.isalpha():
        return False
    left_lower = left_core.lower()
    right_lower = right_core.lower()
    if left_lower in _COMMON_WORDS or right_lower in _COMMON_WORDS:
        return (left_lower, right_lower) in _JOINABLE_COMMON_PAIRS
    if len(left_core) == 1 and len(right_core) == 1 and left_core.islower() and right_core.islower():
        return True
    if len(left_core) == 1 and len(right_core) >= 2 and left_core.islower():
        return True
    if len(right_core) == 1 and 2 <= len(left_core) <= 4 and left_core.islower() and right_core.islower():
        return True
    if len(left_core) == 1 or len(right_core) == 1:
        return False
    if min(len(left_core), len(right_core)) <= 2 and max(len(left_core), len(right_core)) <= 4:
        return len(left_core) + len(right_core) <= 10
    return False


def normalize_token(text: str) -> str:
    tokens = tokenize_for_match(text)
    return tokens[0] if tokens else ""


def tokenize_for_match(text: str) -> list[str]:
    return [match.group(0).lower() for match in _TOKEN_RE.finditer(clean_text(text))]
