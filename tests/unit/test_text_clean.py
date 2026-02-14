from __future__ import annotations

from papercoach.analyze.text_clean import clean_extracted_text


def test_clean_extracted_text_repairs_spaced_character_chains() -> None:
    raw = "Sh um w a y and Sto er discuss co v ariance and observ ations."
    cleaned = clean_extracted_text(raw)
    assert "Shumway" in cleaned
    assert "Stoer" in cleaned
    assert "covariance" in cleaned
    assert "observations" in cleaned


def test_clean_extracted_text_keeps_common_short_words() -> None:
    raw = "In this section, we refer to the model and to observations."
    cleaned = clean_extracted_text(raw)
    assert "In this section" in cleaned
    assert " refer to " in cleaned


def test_clean_extracted_text_preserves_connectors_after_capital_words() -> None:
    raw = "Extension of Maximum Likelihood Factor Analysis."
    cleaned = clean_extracted_text(raw)
    assert "Extension of Maximum" in cleaned
    assert "Extensionof" not in cleaned


def test_clean_extracted_text_splits_common_stuck_tokens() -> None:
    raw = "Thisisa key step because xtthat follows the recursion."
    cleaned = clean_extracted_text(raw)
    assert "This is a key step" in cleaned
    assert "xt that follows" in cleaned
