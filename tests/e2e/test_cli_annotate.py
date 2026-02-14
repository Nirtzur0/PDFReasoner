from __future__ import annotations

from pathlib import Path

from papercoach.cli import main
from papercoach.models import EvidenceRef, MarginNote


class _FakeGrobid:
    def process_fulltext(self, _pdf: Path) -> dict:
        return {"sections": [{"title": "Introduction", "text": "text"}], "bibliography": [{"id": "1", "raw": "Smith 2019"}]}


class _FakeOllama:
    pass


def test_cli_annotate_runs(monkeypatch, tmp_path: Path, sample_pdf: Path) -> None:
    def fake_preflight(run, services, logger):
        return {
            "grobid": _FakeGrobid(),
            "ollama": _FakeOllama(),
            "crossref": None,
            "s2": None,
            "cache": None,
            "paper_id": "pid",
        }

    def fake_generate_note(*args, **kwargs):
        evidence = kwargs.get("evidence", []) or [EvidenceRef(type="paper", pointer={"p": 0}, quote="q")]
        return MarginNote(
            page=kwargs["page"],
            anchor_bbox=kwargs["anchor_bbox"],
            title="Note",
            body="Likely interpretation based on evidence.",
            key_points=["k"],
            evidence=evidence,
            confidence=0.8 if evidence else 0.2,
            uncertainties=[] if evidence else ["uncertain"],
            flags=[kwargs.get("note_kind", "generic")],
        )

    monkeypatch.setattr("papercoach.pipeline.preflight", fake_preflight)
    monkeypatch.setattr("papercoach.pipeline.generate_note", fake_generate_note)

    out_pdf = tmp_path / "enhanced.pdf"
    workdir = tmp_path / "run"
    rc = main([
        "annotate",
        str(sample_pdf),
        "--out",
        str(out_pdf),
        "--workdir",
        str(workdir),
        "--no-web",
    ])

    assert rc == 0
    assert out_pdf.exists()
    assert (workdir / "annotation_plan.json").exists()
    assert (workdir / "evidence_ledger.jsonl").exists()
