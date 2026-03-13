from __future__ import annotations

from pathlib import Path
import json

import fitz

from papercoach.config import RunConfig, ServiceConfig
from papercoach.pipeline import PaperCoachPipeline


def test_pipeline_builds_plan_and_rendered_pdf(
    sample_pdf: Path,
    tmp_path: Path,
    fake_chatmock_base_url: str,
) -> None:
    workdir = tmp_path / "run"
    out_pdf = tmp_path / "highlighted.pdf"
    pipeline = PaperCoachPipeline(
        ServiceConfig(base_url=fake_chatmock_base_url, api_key="test-key", model="gpt-5")
    )
    run = RunConfig(input_pdf=sample_pdf, out_pdf=out_pdf, workdir=workdir)

    plan = pipeline.highlight(run)

    assert workdir.joinpath("highlight_plan.json").exists()
    assert workdir.joinpath("run_manifest.json").exists()
    assert workdir.joinpath("trace.jsonl").exists()
    assert out_pdf.exists()
    assert sum(len(page.highlights) for page in plan.pages) >= 1
    assert sum(len(page.notes) for page in plan.pages) >= 1
    assert sum(len(page.equations) for page in plan.pages) >= 1
    assert sum(len(page.equation_notes) for page in plan.pages) >= 1

    trace_events = [
        json.loads(line)
        for line in workdir.joinpath("trace.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    note_requests = [
        event
        for event in trace_events
        if event.get("type") == "request" and event.get("prompt_name") == "note_generation"
    ]
    assert len(note_requests) == 1
    equation_explanation_requests = [
        event
        for event in trace_events
        if event.get("type") == "request" and event.get("prompt_name") == "equation_explanation"
    ]
    equation_evaluation_requests = [
        event
        for event in trace_events
        if event.get("type") == "request" and event.get("prompt_name") == "equation_evaluation"
    ]
    assert len(equation_explanation_requests) == 1
    assert len(equation_evaluation_requests) == 1

    with fitz.open(out_pdf) as document, fitz.open(sample_pdf) as original:
        assert document.page_count == 2
        assert document[0].first_annot is not None
        assert document[0].rect.width > original[0].rect.width
        assert document[1].rect.width == original[1].rect.width


def test_pipeline_fails_when_required_model_is_missing(sample_pdf: Path, tmp_path: Path, fake_chatmock_base_url: str) -> None:
    pipeline = PaperCoachPipeline(
        ServiceConfig(base_url=fake_chatmock_base_url, api_key="test-key", model="gpt-5.4")
    )
    run = RunConfig(input_pdf=sample_pdf, out_pdf=tmp_path / "out.pdf", workdir=tmp_path / "run")

    try:
        pipeline.highlight_plan(run)
    except RuntimeError as exc:
        assert "gpt-5.4" in str(exc)
    else:
        raise AssertionError("Expected strict model validation to fail")


def test_pipeline_overwrites_stale_manifest_model(
    sample_pdf: Path,
    tmp_path: Path,
    fake_chatmock_base_url: str,
) -> None:
    workdir = tmp_path / "run"
    out_pdf = tmp_path / "highlighted.pdf"
    pipeline = PaperCoachPipeline(
        ServiceConfig(base_url=fake_chatmock_base_url, api_key="test-key", model="gpt-5")
    )
    run = RunConfig(input_pdf=sample_pdf, out_pdf=out_pdf, workdir=workdir)

    plan = pipeline.highlight_plan(run)
    workdir.mkdir(parents=True, exist_ok=True)
    run.manifest_path.write_text(
        json.dumps(
            {
                "input_pdf": str(sample_pdf),
                "output_pdf": str(out_pdf),
                "plan_path": str(run.plan_path),
                "trace_path": str(run.trace_path),
                "model": "stale-model",
                "highlight_count": 0,
                "pages_with_highlights": 0,
                "note_count": 0,
                "equation_count": 0,
                "equation_note_count": 0,
            }
        ),
        encoding="utf-8",
    )

    pipeline.render_highlights(run, run.plan_path)

    manifest = json.loads(run.manifest_path.read_text(encoding="utf-8"))
    assert manifest["model"] == "gpt-5"
    assert manifest["highlight_count"] == sum(len(page.highlights) for page in plan.pages)
