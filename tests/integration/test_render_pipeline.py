from __future__ import annotations

from pathlib import Path

import fitz

from papercoach.config import RunConfig
from papercoach.models import (
    AnnotationPlan,
    EvidenceRef,
    GlossaryItem,
    Highlight,
    MarginNote,
    MindmapArtifact,
    PagePlan,
)
from papercoach.pipeline import render


def test_render_from_plan_outputs_pdf(tmp_path: Path, sample_pdf: Path) -> None:
    workdir = tmp_path / "run"
    workdir.mkdir(parents=True, exist_ok=True)

    plan = AnnotationPlan(
        paper_id="pid",
        meta={},
        pages={
            0: PagePlan(
                page=0,
                highlights=[Highlight(page=0, bbox=[45, 140, 500, 165], tag="theorem_like")],
                anchors=[],
                notes=[
                    MarginNote(
                        page=0,
                        anchor_bbox=[45, 140, 500, 165],
                        title="Theorem note",
                        body="Likely interpretation based on text evidence.",
                        key_points=["k"],
                        evidence=[EvidenceRef(type="paper", pointer={"p": 0}, quote="q")],
                        confidence=0.8,
                        uncertainties=[],
                        flags=["theorem_like"],
                    )
                ],
            ),
            1: PagePlan(page=1, highlights=[], anchors=[], notes=[]),
        },
        references=[],
        glossary=[
            GlossaryItem(
                symbol="x",
                meaning="vector",
                first_occurrence_page=0,
                first_occurrence_bbox=[1, 1, 2, 2],
                confidence=0.9,
                evidence=[EvidenceRef(type="paper", pointer={"p": 0}, quote="x")],
            )
        ],
        mindmaps=[MindmapArtifact(path=str(workdir / "mindmap.png"), position="appendix", node_count=1, edge_count=0)],
    )

    # minimal valid PNG
    (workdir / "mindmap.png").write_bytes(
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc```\x00\x00\x00\x04\x00\x01\x0b\xe7\x02\x9d\x00\x00\x00\x00IEND\xaeB`\x82"
    )

    plan_path = workdir / "annotation_plan.json"
    plan_path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")

    out_pdf = tmp_path / "enhanced.pdf"
    run = RunConfig(input_pdf=sample_pdf, out_pdf=out_pdf, workdir=workdir)
    render(run, plan_path=plan_path)

    assert out_pdf.exists()
    with fitz.open(out_pdf) as out:
        assert out.page_count >= 2
