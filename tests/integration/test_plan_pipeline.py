from __future__ import annotations

from pathlib import Path

from papercoach.config import RunConfig, ServiceConfig
from papercoach.models import EvidenceRef, MarginNote
from papercoach.pipeline import analyze


class _FakeGrobid:
    def process_fulltext(self, _pdf: Path) -> dict:
        return {
            "sections": [{"title": "Introduction", "text": "text"}],
            "bibliography": [{"id": "1", "raw": "Smith, 2019"}],
        }


class _FakeOllama:
    pass


def test_plan_emits_required_artifacts(monkeypatch, tmp_path: Path, sample_pdf: Path) -> None:
    def fake_preflight(run, services, logger):
        return {
            "grobid": _FakeGrobid(),
            "ollama": _FakeOllama(),
            "crossref": None,
            "s2": None,
            "cache": None,
            "paper_id": "abc123",
        }

    def fake_generate_note(*args, **kwargs):
        evidence = kwargs.get("evidence", []) or [EvidenceRef(type="paper", pointer={"a": 1}, quote="q")]
        return MarginNote(
            page=kwargs["page"],
            anchor_bbox=kwargs["anchor_bbox"],
            title="Note",
            body="Interpretation likely based on provided evidence.",
            key_points=["k1"],
            evidence=evidence,
            confidence=0.8 if evidence else 0.2,
            uncertainties=[] if evidence else ["uncertain"],
            flags=[kwargs.get("note_kind", "generic")],
        )

    monkeypatch.setattr("papercoach.pipeline.preflight", fake_preflight)
    monkeypatch.setattr("papercoach.pipeline.generate_note", fake_generate_note)

    run = RunConfig(
        input_pdf=sample_pdf,
        out_pdf=tmp_path / "enhanced.pdf",
        workdir=tmp_path / "run",
        no_web=True,
    )
    plan = analyze(run, ServiceConfig())

    assert plan.paper_id == "abc123"
    assert (run.workdir / "annotation_plan.json").exists()
    assert (run.workdir / "evidence_ledger.jsonl").exists()
    assert (run.workdir / "mindmap.png").exists()
    assert (run.workdir / "report.html").exists()
