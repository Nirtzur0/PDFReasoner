from __future__ import annotations

from pathlib import Path

from papercoach.analyze.mindmap import generate_mindmap
from papercoach.models import Citation


class _FakeOllama:
    def structured_output(self, prompt: str, schema: dict, system_prompt: str) -> dict:
        assert "mind-map backbone" in prompt
        return {
            "root": "Linear Dynamical Systems",
            "nodes": [
                {"id": "sec_intro", "label": "Model Setup", "group": "section"},
                {"id": "meth_em", "label": "EM Updates", "group": "method"},
                {"id": "res_est", "label": "Parameter Estimates", "group": "result"},
            ],
            "edges": [
                {"source": "root", "target": "sec_intro", "label": "scope"},
                {"source": "sec_intro", "target": "meth_em", "label": "defines"},
                {"source": "meth_em", "target": "res_est", "label": "produces"},
            ],
        }


class _GenericOllama:
    def structured_output(self, prompt: str, schema: dict, system_prompt: str) -> dict:
        return {
            "root": "Technical Paper",
            "nodes": [
                {"id": "scope", "label": "Introduction and Scope", "group": "section"},
                {"id": "method", "label": "Method Pipeline", "group": "method"},
            ],
            "edges": [{"source": "root", "target": "scope", "label": "defines"}],
        }


def test_generate_mindmap_writes_mermaid_and_png(tmp_path: Path) -> None:
    out_png = tmp_path / "mindmap.png"
    artifact = generate_mindmap(
        out_png=out_png,
        sections=[{"title": "Introduction", "page": 0}],
        theorem_nodes=[{"block_id": "b1", "page": 1, "label": "Theorem 1"}],
        citations=[Citation(raw="Anderson and Moore")],
        position="appendix",
        ollama_client=_FakeOllama(),
    )

    assert artifact.path == str(out_png)
    assert artifact.node_count >= 3
    assert artifact.edge_count >= 2
    assert out_png.exists()
    assert out_png.stat().st_size > 2000
    md_path = out_png.with_suffix(".md")
    mmd_path = out_png.with_suffix(".mmd")
    assert md_path.exists()
    assert mmd_path.exists()
    assert "```mermaid" in md_path.read_text(encoding="utf-8")
    assert "flowchart LR" in mmd_path.read_text(encoding="utf-8")


def test_generate_mindmap_rejects_generic_llm_graph(tmp_path: Path) -> None:
    out_png = tmp_path / "mindmap.png"
    generate_mindmap(
        out_png=out_png,
        sections=[{"title": "EM Algorithm", "page": 2}, {"title": "M step", "page": 3}],
        theorem_nodes=[],
        citations=[],
        position="appendix",
        ollama_client=_GenericOllama(),
    )
    mmd = out_png.with_suffix(".mmd").read_text(encoding="utf-8")
    assert "EM Algorithm" in mmd
