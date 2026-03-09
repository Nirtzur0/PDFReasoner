from __future__ import annotations

from dataclasses import dataclass
import re


HEADING_RE = re.compile(
    r"^(abstract|introduction|background|related work|method|methods|experiments|results|discussion|conclusion|references)\b",
    re.IGNORECASE,
)
NUMBERED_HEADING_RE = re.compile(r"^\d+(?:\.\d+)*\.?\s+[A-Z][^\n]*$")
REFERENCE_ENTRY_RE = re.compile(r"^\[[0-9]+\]|\([12][0-9]{3}\)")
REFERENCE_HEADING_RE = re.compile(r"^(?:\d+(?:\.\d+)*\.?\s+)?references\b", re.IGNORECASE)
LEADING_SECTION_RE = re.compile(r"^(?P<number>\d+(?:\.\d+)*\.?)\s+(?P<rest>.+)$")
_HEADING_CONNECTORS = {"a", "an", "and", "for", "from", "in", "of", "on", "or", "the", "to", "with", "without"}


@dataclass(slots=True)
class BlockStructure:
    is_heading: bool
    section_title: str | None


class StructureDetector:
    def is_reference_heading(self, text: str) -> bool:
        return bool(REFERENCE_HEADING_RE.match(text.strip()))

    def is_reference_section(self, section_title: str | None) -> bool:
        return bool(section_title and self.is_reference_heading(section_title))

    def is_reference_entry(self, text: str) -> bool:
        return bool(REFERENCE_ENTRY_RE.search(text.strip()))

    def leading_section_title(self, text: str) -> str | None:
        compact = text.strip()
        match = LEADING_SECTION_RE.match(compact)
        if not match:
            return None
        number = match.group("number")
        if not self._looks_like_section_number(number):
            return None
        words = match.group("rest").split()
        if any("?" in word for word in words[:12]):
            question_words: list[str] = []
            for word in words[:12]:
                clean = word.strip().strip(",.:;")
                if not clean:
                    break
                question_words.append(clean)
                if "?" in word:
                    if len(question_words) >= 2:
                        return f"{number} {' '.join(question_words)}"
                    break
        title_words: list[str] = []
        for index, word in enumerate(words):
            stripped = word.strip()
            clean = stripped.strip(",.:;")
            next_word = words[index + 1] if index + 1 < len(words) else ""
            if not clean:
                break
            if title_words and stripped.endswith(","):
                break
            if title_words and self._looks_like_sentence_start(clean, next_word):
                break
            if not self._is_heading_word(clean):
                break
            title_words.append(clean)
            if stripped.endswith("?"):
                break
        if len(title_words) < 2:
            return None
        return f"{number} {' '.join(title_words)}"

    def is_heading(self, text: str, avg_font_size: float, baseline_font_size: float, block_height: float, baseline_block_height: float) -> bool:
        compact = text.strip()
        if len(compact) < 3 or len(compact) > 110:
            return False
        if compact.endswith("."):
            return False
        if HEADING_RE.match(compact):
            return True
        if NUMBERED_HEADING_RE.match(compact) and self._looks_like_section_number(compact):
            return True
        words = compact.split()
        digit_tokens = sum(1 for word in words if any(ch.isdigit() for ch in word))
        title_case_words = sum(1 for word in words if word[:1].isupper())
        looks_like_heading_text = self._looks_like_heading_text(words)
        if (
            len(words) <= 8
            and avg_font_size >= max(baseline_font_size * 1.15, baseline_font_size + 0.8)
            and "@" not in compact
            and digit_tokens <= 1
            and not any(symbol in compact for symbol in ("#", "%", "=", "[", "]", "(", ")", "+", "@"))
            and looks_like_heading_text
        ):
            return True
        if (
            len(words) <= 8
            and baseline_font_size <= 1.0
            and avg_font_size <= 1.0
            and block_height >= max(baseline_block_height * 1.12, baseline_block_height + 1.0)
            and "@" not in compact
            and digit_tokens <= 1
            and not any(symbol in compact for symbol in ("#", "%", "=", "[", "]", "(", ")", "+", "@"))
            and looks_like_heading_text
        ):
            return True
        return False

    def _looks_like_section_number(self, text: str) -> bool:
        number_token = text.split(maxsplit=1)[0].rstrip(".")
        try:
            parts = [int(part) for part in number_token.split(".") if part]
        except ValueError:
            return False
        if not parts:
            return False
        return 1 <= parts[0] <= 20 and all(0 <= part <= 20 for part in parts[1:])

    def _is_heading_word(self, word: str) -> bool:
        if not word:
            return False
        lowered = word.lower()
        if lowered in _HEADING_CONNECTORS:
            return True
        if word.isupper():
            return True
        if word[:1].isupper():
            return True
        if "-" in word:
            return all(self._is_heading_word(part) for part in word.split("-") if part)
        return False

    def _looks_like_heading_text(self, words: list[str]) -> bool:
        title_case_words = sum(1 for word in words if word[:1].isupper())
        if title_case_words == len(words):
            return sum(len(word) for word in words) >= 4
        if len(words) >= 3 and title_case_words >= len(words) - 1:
            return True
        alpha_words = [word for word in words if word.isalpha()]
        if len(alpha_words) != len(words):
            return False
        if len(words) > 3:
            return False
        if sum(len(word) for word in words) < 8:
            return False
        if any(len(word) == 1 and word.islower() for word in words):
            return False
        return bool(words[0][:1].isupper())

    def _looks_like_sentence_start(self, word: str, next_word: str) -> bool:
        return bool(word[:1].isupper() and next_word[:1].islower())

    def is_reference_page(self, block_texts: list[str]) -> bool:
        if not block_texts:
            return False
        heading_hits = sum(1 for text in block_texts if self.is_reference_heading(text))
        entry_hits = sum(1 for text in block_texts if self.is_reference_entry(text))
        return heading_hits > 0 or entry_hits >= 5
