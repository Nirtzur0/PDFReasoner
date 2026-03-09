from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re

from papercoach.extract.extractor import ExtractedBlock, ExtractedWord
from papercoach.extract.normalize import clean_text, repair_token_sequence, tokenize_for_match

_INCOMPLETE_BOUNDARY_TOKENS = {
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
_SECTION_NUMBER_TOKEN_RE = re.compile(r"^\d+(?:\.\d+)*\.?$")


@dataclass(slots=True)
class AlignmentResult:
    matched_text: str
    quads: list[tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]]]


class SpanAligner:
    def align_quote(self, block: ExtractedBlock, quote: str) -> AlignmentResult | None:
        return self.align_quote_in_words(block.words, quote)

    def align_block_words(self, words: list[ExtractedWord]) -> AlignmentResult | None:
        full_words = [word for word in words if word.text.strip()]
        if not full_words:
            return None
        quads = self._line_quads(full_words)
        matched_text = clean_text(" ".join(word.text for word in full_words))
        return AlignmentResult(matched_text=matched_text, quads=quads)

    def align_quote_in_words(self, words: list[ExtractedWord], quote: str) -> AlignmentResult | None:
        quote_tokens = tokenize_for_match(quote)
        if not quote_tokens or len(quote_tokens) > 60:
            return None

        full_words = [word for word in words if word.text.strip()]
        block_tokens, match_to_full = self._tokenize_words(full_words)
        if len(quote_tokens) > len(block_tokens):
            return None

        exact_hits = self._exact_hits(block_tokens, quote_tokens)
        if len(exact_hits) == 1:
            return self._build_result(full_words, match_to_full, exact_hits[0], exact_hits[0] + len(quote_tokens), quote_tokens)
        if len(exact_hits) > 1:
            return None

        best_window = self._best_fuzzy_window(block_tokens, quote_tokens)
        if best_window is None:
            repaired_result = self._align_against_repaired_tokens(full_words, block_tokens, quote_tokens, match_to_full)
            if repaired_result is None:
                return None
            return repaired_result
        start, end = best_window
        return self._build_result(full_words, match_to_full, start, end, quote_tokens)

    def _align_against_repaired_tokens(
        self,
        full_words: list[ExtractedWord],
        block_tokens: list[str],
        quote_tokens: list[str],
        match_to_full: list[int],
    ) -> AlignmentResult | None:
        repaired_tokens, repaired_ranges = repair_token_sequence(block_tokens)
        if not repaired_tokens:
            return None
        exact_hits = self._exact_hits(repaired_tokens, quote_tokens)
        if len(exact_hits) == 1:
            repaired_start = exact_hits[0]
            repaired_end = repaired_start + len(quote_tokens)
            return self._build_result(
                full_words,
                match_to_full,
                repaired_ranges[repaired_start][0],
                repaired_ranges[repaired_end - 1][1],
                quote_tokens,
            )
        if len(exact_hits) > 1:
            return None
        best_window = self._best_fuzzy_window(repaired_tokens, quote_tokens)
        if best_window is None:
            return None
        start, end = best_window
        return self._build_result(
            full_words,
            match_to_full,
            repaired_ranges[start][0],
            repaired_ranges[end - 1][1],
            quote_tokens,
        )

    def _tokenize_words(self, words: list[ExtractedWord]) -> tuple[list[str], list[int]]:
        tokens: list[str] = []
        match_to_full: list[int] = []
        for index, word in enumerate(words):
            for token in tokenize_for_match(word.text):
                tokens.append(token)
                match_to_full.append(index)
        return (tokens, match_to_full)

    def _exact_hits(self, block_tokens: list[str], quote_tokens: list[str]) -> list[int]:
        hits = []
        window = len(quote_tokens)
        for start in range(0, len(block_tokens) - window + 1):
            if block_tokens[start : start + window] == quote_tokens:
                hits.append(start)
        return hits

    def _best_fuzzy_window(self, block_tokens: list[str], quote_tokens: list[str]) -> tuple[int, int] | None:
        target = " ".join(quote_tokens)
        candidates: list[tuple[float, int, int]] = []
        for window in range(max(1, len(quote_tokens) - 2), min(len(block_tokens), len(quote_tokens) + 2) + 1):
            for start in range(0, len(block_tokens) - window + 1):
                candidate = " ".join(block_tokens[start : start + window])
                score = SequenceMatcher(a=target, b=candidate).ratio()
                candidates.append((score, start, start + window))
        candidates.sort(reverse=True)
        if not candidates or candidates[0][0] < 0.86:
            return None
        if len(candidates) > 1 and candidates[0][0] - candidates[1][0] < 0.03:
            return None
        _, start, end = candidates[0]
        return (start, end)

    def _build_result(
        self,
        full_words: list[ExtractedWord],
        match_to_full: list[int],
        start: int,
        end: int,
        quote_tokens: list[str],
    ) -> AlignmentResult:
        full_start = match_to_full[start]
        full_end = match_to_full[end - 1] + 1
        full_start, full_end = self._trim_to_anchor_words(full_words, full_start, full_end, quote_tokens)
        full_start, full_end = self._expand_to_sentence(full_words, full_start, full_end)
        matched_words = full_words[full_start:full_end]
        quads = self._line_quads(matched_words)
        matched_text = clean_text(" ".join(word.text for word in matched_words))
        return AlignmentResult(matched_text=matched_text, quads=quads)

    def _trim_to_anchor_words(
        self,
        words: list[ExtractedWord],
        start: int,
        end: int,
        quote_tokens: list[str],
    ) -> tuple[int, int]:
        if start >= end or not quote_tokens:
            return (start, end)
        start_anchor = self._boundary_anchor_token(quote_tokens, reverse=False)
        if start_anchor:
            search_end = min(end, start + 8)
            for index in range(start, search_end):
                if start_anchor in tokenize_for_match(words[index].text):
                    start = index
                    break
        end_anchor = self._boundary_anchor_token(quote_tokens, reverse=True)
        if end_anchor:
            search_start = max(start, end - 8)
            for index in range(end - 1, search_start - 1, -1):
                if end_anchor in tokenize_for_match(words[index].text):
                    end = index + 1
                    break
        return (start, end)

    def _boundary_anchor_token(self, quote_tokens: list[str], reverse: bool) -> str | None:
        tokens = reversed(quote_tokens) if reverse else quote_tokens
        for token in tokens:
            if len(token) >= 3:
                return token
        return quote_tokens[-1] if reverse else quote_tokens[0]

    def _expand_to_sentence(self, words: list[ExtractedWord], start: int, end: int) -> tuple[int, int]:
        sentence_start = start
        while sentence_start > 0 and not self._is_sentence_ender(words[sentence_start - 1].text):
            if words[sentence_start - 1].block_id != words[sentence_start].block_id and (
                self._looks_like_sentence_start(words[sentence_start].text)
                or self._looks_like_heading_start(words, sentence_start)
            ):
                break
            sentence_start -= 1
            if start - sentence_start >= 50:
                break

        while sentence_start < end and self._is_leading_marker(words[sentence_start].text):
            sentence_start += 1

        sentence_end = end
        while sentence_end < len(words) and not self._is_sentence_ender(words[sentence_end - 1].text):
            previous = words[sentence_end - 1]
            current = words[sentence_end]
            previous_tokens = tokenize_for_match(previous.text)
            if current.block_id != previous.block_id and (
                self._looks_like_sentence_start(current.text) or self._looks_like_heading_start(words, sentence_end)
            ):
                break
            if previous_tokens and previous_tokens[-1] in _INCOMPLETE_BOUNDARY_TOKENS and self._looks_like_sentence_start(current.text):
                break
            sentence_end += 1
            if sentence_end - sentence_start >= 60:
                break

        return (sentence_start, sentence_end)

    def _line_quads(
        self,
        words: list[ExtractedWord],
    ) -> list[tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]]]:
        quads: list[tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]]] = []
        current: list[ExtractedWord] = []
        for word in words:
            if current and not self._same_line(current[-1], word):
                quads.append(self._line_quad(current))
                current = []
            current.append(word)
        if current:
            quads.append(self._line_quad(current))
        return quads

    def _same_line(self, left: ExtractedWord, right: ExtractedWord) -> bool:
        left_mid = (left.bbox[1] + left.bbox[3]) / 2.0
        right_mid = (right.bbox[1] + right.bbox[3]) / 2.0
        return abs(left_mid - right_mid) <= 2.5

    def _is_sentence_ender(self, text: str) -> bool:
        return bool(re.search(r"[.!?:;](?:[\"')\]]*)$", text))

    def _is_leading_marker(self, text: str) -> bool:
        return text in {"-", "*", "•", '"', "'"}

    def _looks_like_sentence_start(self, text: str) -> bool:
        return bool(text) and text[0].isupper()

    def _looks_like_heading_start(self, words: list[ExtractedWord], index: int) -> bool:
        current = words[index].text
        if not _SECTION_NUMBER_TOKEN_RE.fullmatch(current):
            return False
        if index + 1 >= len(words):
            return False
        next_word = words[index + 1].text
        return bool(next_word) and next_word[0].isupper()

    def _line_quad(
        self,
        words: list[ExtractedWord],
    ) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]]:
        x0 = min(word.bbox[0] for word in words)
        y0 = min(word.bbox[1] for word in words)
        x1 = max(word.bbox[2] for word in words)
        y1 = max(word.bbox[3] for word in words)
        return ((x0, y0), (x1, y0), (x0, y1), (x1, y1))
