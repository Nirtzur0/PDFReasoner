from __future__ import annotations

from papercoach.analyze.prompt_library import build_note_prompt
from papercoach.models import EvidenceRef


def test_prompt_library_includes_task_breakdown_and_evidence_ids() -> None:
    prompt = build_note_prompt(
        anchor_text="x_t = A x_t-1 + w_t",
        context="State transition equation for the latent dynamics.",
        evidence=[
            EvidenceRef(type="paper", pointer={"page": 1}, quote="x_t = A x_t-1 + w_t"),
            EvidenceRef(type="paper", pointer={"page": 1}, quote="w_t is Gaussian noise"),
        ],
        note_kind="equation",
    )
    assert "Task type: equation" in prompt
    assert "Problem breakdown:" in prompt
    assert "Allowed evidence IDs: e0, e1" in prompt


def test_prompt_library_lists_notation_tokens() -> None:
    prompt = build_note_prompt(
        anchor_text="The filter uses K_t and P_t to update x_t.",
        context="Kalman gain K_t controls correction while P_t tracks covariance.",
        evidence=[EvidenceRef(type="paper", pointer={"page": 2}, quote="K_t = P_t C^T (...)")],
        note_kind="page_tldr",
    )
    assert "Notation to preserve:" in prompt
    assert "K_t" in prompt
    assert "P_t" in prompt


def test_prompt_library_adds_expert_scope_calibration() -> None:
    prompt = build_note_prompt(
        anchor_text="This section applies optimal filtering to switched state-space dynamics.",
        context="The derivation focuses on parameter updates rather than introductory motivation.",
        evidence=[EvidenceRef(type="paper", pointer={"page": 2}, quote="applies optimal filtering to switched dynamics")],
        note_kind="page_tldr",
    )
    assert "Scope calibration:" in prompt
    assert "Assume a technically fluent reader" in prompt
    assert "Do not define baseline terms unless locally defined in evidence" in prompt
    assert "optimal filtering" in prompt


def test_prompt_library_allows_local_definition_when_explicit() -> None:
    prompt = build_note_prompt(
        anchor_text="Optimal filtering is defined here as minimizing expected squared error.",
        context="The text denotes optimal filtering as an MMSE estimator in this setup.",
        evidence=[EvidenceRef(type="paper", pointer={"page": 1}, quote="optimal filtering is defined as minimizing expected squared error")],
        note_kind="section_tldr",
    )
    assert "Scope calibration:" in prompt
    assert "Optimal filtering is defined here" in prompt
