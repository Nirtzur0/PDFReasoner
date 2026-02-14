from __future__ import annotations

from pathlib import Path

import pytest

from papercoach.config import RunConfig, ServiceConfig
from papercoach.pipeline import preflight, _logger


class _BadGrobid:
    def __init__(self, *args, **kwargs):
        pass

    def healthcheck(self):
        raise RuntimeError("grobid down")


class _BadOllama:
    def __init__(self, *args, **kwargs):
        pass

    def healthcheck(self):
        raise RuntimeError("ollama down")


class _OkCrossref:
    def __init__(self, *args, **kwargs):
        pass

    def healthcheck(self):
        pass


class _OkS2:
    def __init__(self, *args, **kwargs):
        pass

    def healthcheck(self):
        pass


def test_preflight_fails_when_grobid_unavailable(monkeypatch, sample_pdf: Path, tmp_path: Path) -> None:
    run = RunConfig(input_pdf=sample_pdf, out_pdf=tmp_path / "o.pdf", workdir=tmp_path / "w", no_web=True)
    logger = _logger(run.workdir)

    monkeypatch.setattr("papercoach.pipeline.GrobidClient", _BadGrobid)
    monkeypatch.setattr("papercoach.pipeline.OllamaClient", _OkCrossref)
    monkeypatch.setattr("papercoach.pipeline.CrossrefClient", _OkCrossref)
    monkeypatch.setattr("papercoach.pipeline.SemanticScholarClient", _OkS2)

    with pytest.raises(RuntimeError):
        preflight(run, ServiceConfig(), logger)


def test_preflight_fails_when_ollama_unavailable(monkeypatch, sample_pdf: Path, tmp_path: Path) -> None:
    run = RunConfig(input_pdf=sample_pdf, out_pdf=tmp_path / "o.pdf", workdir=tmp_path / "w2", no_web=True)
    logger = _logger(run.workdir)

    monkeypatch.setattr("papercoach.pipeline.GrobidClient", _OkCrossref)
    monkeypatch.setattr("papercoach.pipeline.OllamaClient", _BadOllama)
    monkeypatch.setattr("papercoach.pipeline.CrossrefClient", _OkCrossref)
    monkeypatch.setattr("papercoach.pipeline.SemanticScholarClient", _OkS2)

    with pytest.raises(RuntimeError):
        preflight(run, ServiceConfig(), logger)
