from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import fitz
from graphviz import Digraph

from papercoach.analyze.text_clean import clean_extracted_text
from papercoach.models import Citation, MindmapArtifact

_MINDMAP_SCHEMA = {
    "type": "object",
    "properties": {
        "root": {"type": "string"},
        "nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "label": {"type": "string"},
                    "group": {"type": "string"},
                },
                "required": ["id", "label", "group"],
            },
        },
        "edges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "source": {"type": "string"},
                    "target": {"type": "string"},
                    "label": {"type": "string"},
                },
                "required": ["source", "target", "label"],
            },
        },
    },
    "required": ["root", "nodes", "edges"],
}


def _safe_id(text: str, fallback: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", text.strip().lower()).strip("_")
    return cleaned[:40] or fallback


def _pick_root_label(sections: list[dict], note_signals: list[dict]) -> str:
    generic = {"paper", "root", "root node", "paper mind map", "technical paper"}
    for sec in sections:
        title = clean_extracted_text(str(sec.get("title", "")))
        if len(title.split()) >= 4 and title.lower() not in generic:
            return title
    for signal in note_signals:
        title = clean_extracted_text(str(signal.get("title", "")))
        if len(title.split()) >= 3 and title.lower() not in generic:
            return title
    for sec in sections:
        title = clean_extracted_text(str(sec.get("title", "")))
        if title and title.lower() not in generic:
            return title
    return "Paper Overview"


def _fallback_spec(
    sections: list[dict], theorem_nodes: list[dict], citations: list[Citation], note_signals: list[dict]
) -> dict:
    root = _pick_root_label(sections, note_signals)
    nodes: list[dict] = [{"id": "root", "label": root[:72], "group": "root"}]
    edges: list[dict] = []

    for i, sec in enumerate(sections[:6]):
        nid = f"s{i}"
        label = clean_extracted_text(sec["title"])[:64]
        if not label or _is_generic_label(label):
            continue
        nodes.append({"id": nid, "label": label, "group": "section"})
        edges.append({"source": "root", "target": nid, "label": "scope"})

    for i, n in enumerate(note_signals[:6]):
        nid = f"m{i}"
        label = clean_extracted_text(str(n.get("title", "")))[:64]
        if not label or _is_generic_label(label):
            continue
        group = "method"
        flag = str(n.get("flag", ""))
        if "result" in flag or "theorem" in flag:
            group = "result"
        elif "assumption" in flag:
            group = "assumption"
        nodes.append({"id": nid, "label": label, "group": group})
        parent = "s0" if any(x["id"] == "s0" for x in nodes) else "root"
        edges.append({"source": parent, "target": nid, "label": "develops"})

    for i, th in enumerate(theorem_nodes[:4]):
        nid = f"t{i}"
        label = clean_extracted_text(th["label"])[:64]
        if not label or _is_generic_label(label):
            continue
        nodes.append({"id": nid, "label": label, "group": "result"})
        parent = "s0" if any(n["id"] == "s0" for n in nodes) else "root"
        edges.append({"source": parent, "target": nid, "label": "supports"})

    for i, c in enumerate(citations[:4]):
        title = c.resolved.title if c.resolved and c.resolved.title else c.raw
        nid = f"c{i}"
        label = clean_extracted_text(title)[:64]
        if not label or _is_generic_label(label):
            continue
        nodes.append({"id": nid, "label": label, "group": "citation"})
        parent = "root"
        edges.append({"source": parent, "target": nid, "label": "uses"})

    dedup: dict[str, dict] = {}
    for n in nodes:
        key = n["label"].strip().lower()
        if key not in dedup:
            dedup[key] = n
    nodes = list(dedup.values())
    valid_ids = {n["id"] for n in nodes}
    edges = [e for e in edges if e["source"] in valid_ids and e["target"] in valid_ids and e["source"] != e["target"]]
    return {"root": root, "nodes": nodes, "edges": edges}


def _mindmap_prompt(
    sections: list[dict], theorem_nodes: list[dict], citations: list[Citation], note_signals: list[dict]
) -> str:
    sec_payload = [{"title": s.get("title", ""), "page": s.get("page", 0)} for s in sections[:12]]
    th_payload = [{"label": t.get("label", ""), "page": t.get("page", 0)} for t in theorem_nodes[:10]]
    cit_payload = []
    for c in citations[:12]:
        title = c.resolved.title if c.resolved and c.resolved.title else c.raw
        cit_payload.append({"title": title, "mentions": c.mention_count})
    payload = {
        "sections": sec_payload,
        "key_results": th_payload,
        "citations": cit_payload,
        "annotation_signals": note_signals[:12],
    }
    return (
        "Build a concise mind-map backbone for this technical paper.\n"
        "Output JSON with root/nodes/edges only.\n"
        "Constraints:\n"
        "- 8 to 18 nodes total.\n"
        "- Capture scope, method pipeline, assumptions, results, and external links.\n"
        "- Keep labels specific to the paper, no generic placeholders.\n"
        "- Prefer concrete nodes from sections, equations, assumptions, update steps, and cited works.\n"
        "- Keep each label under 8 words.\n"
        "- Use groups: root, section, method, result, assumption, citation.\n"
        "- Edges should describe relation semantics (e.g., defines, depends_on, evaluates, cites).\n\n"
        f"Paper signals:\n{json.dumps(payload, ensure_ascii=True)}"
    )


def _llm_spec(
    ollama_client, sections: list[dict], theorem_nodes: list[dict], citations: list[Citation], note_signals: list[dict]
) -> dict | None:
    if not ollama_client or not hasattr(ollama_client, "structured_output"):
        return None
    prompt = _mindmap_prompt(sections, theorem_nodes, citations, note_signals)
    try:
        return ollama_client.structured_output(
            prompt=prompt,
            schema=_MINDMAP_SCHEMA,
            system_prompt=(
                "Return strict JSON only. Build a logical technical mind-map from provided paper signals."
            ),
        )
    except Exception:
        return None


def _normalize_spec(spec: dict | None, fallback: dict) -> dict:
    if not isinstance(spec, dict):
        return fallback
    root = clean_extracted_text(str(spec.get("root") or fallback["root"]))[:80]
    if _is_generic_label(root):
        root = fallback["root"]
    raw_nodes = spec.get("nodes", [])
    raw_edges = spec.get("edges", [])
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        return fallback

    nodes: list[dict] = [{"id": "root", "label": root, "group": "root"}]
    seen = {"root"}
    for i, n in enumerate(raw_nodes[:24]):
        if not isinstance(n, dict):
            continue
        nid = _safe_id(str(n.get("id", "")), f"n{i}")
        if nid in seen:
            continue
        label = clean_extracted_text(str(n.get("label", "")))[:80]
        if not label:
            continue
        if _is_generic_label(label):
            continue
        if label.lower() == root.lower() or label.lower() in {"root", "root node", "paper mind map"}:
            continue
        group = str(n.get("group", "section")).strip().lower()[:24] or "section"
        nodes.append({"id": nid, "label": label, "group": group})
        seen.add(nid)

    edges: list[dict] = []
    for e in raw_edges[:48]:
        if not isinstance(e, dict):
            continue
        src = _safe_id(str(e.get("source", "")), "")
        dst = _safe_id(str(e.get("target", "")), "")
        if src not in seen or dst not in seen or src == dst:
            continue
        label = clean_extracted_text(str(e.get("label", "rel")))[:32] or "rel"
        edges.append({"source": src, "target": dst, "label": label})

    dedup_edges: list[dict] = []
    edge_seen: set[tuple[str, str, str]] = set()
    for e in edges:
        key = (e["source"], e["target"], e["label"])
        if key in edge_seen:
            continue
        edge_seen.add(key)
        dedup_edges.append(e)
    edges = dedup_edges

    if not edges:
        for n in nodes[1:]:
            edges.append({"source": "root", "target": n["id"], "label": "scope"})
    else:
        connected = {e["source"] for e in edges} | {e["target"] for e in edges}
        for n in nodes[1:]:
            if n["id"] not in connected:
                edges.append({"source": "root", "target": n["id"], "label": "scope"})

    max_edges = max(8, min(18, len(nodes) * 2))
    if len(edges) > max_edges:
        edges = edges[:max_edges]

    return {"root": root, "nodes": nodes, "edges": edges}


def _is_generic_label(text: str) -> bool:
    t = text.lower().strip()
    generic = {
        "technical paper",
        "paper",
        "paper mind map",
        "root",
        "root node",
        "scope",
        "results",
        "main findings",
        "key assumption",
        "conclusion",
        "method",
        "method pipeline",
        "workflow",
        "introduction and scope",
        "key findings and results",
        "underlying assumptions and limitations",
        "technical point",
        "section focus",
        "imported idea reference",
        "guidance note",
    }
    return t in generic


def _spec_is_too_generic(spec: dict, sections: list[dict], note_signals: list[dict]) -> bool:
    labels = [n["label"] for n in spec["nodes"]]
    if not labels:
        return True
    generic_hits = sum(1 for l in labels if _is_generic_label(l))
    if generic_hits >= max(2, len(labels) // 2):
        return True
    section_titles = {s.get("title", "").strip().lower() for s in sections if s.get("title")}
    signal_titles = {n.get("title", "").strip().lower() for n in note_signals if n.get("title")}
    known_titles = section_titles | signal_titles
    if not known_titles:
        return False
    if len(known_titles) < 2:
        return False
    overlap = sum(1 for l in labels if l.strip().lower() in known_titles)
    return overlap == 0


def _to_mermaid(spec: dict) -> str:
    lines = ["flowchart LR"]
    for n in spec["nodes"]:
        nid = n["id"]
        label = n["label"].replace('"', "'")
        lines.append(f'    {nid}["{label}"]')
    for e in spec["edges"]:
        label = e["label"].replace('"', "'")
        lines.append(f'    {e["source"]} -- "{label}" --> {e["target"]}')
    lines.extend(
        [
            "    classDef root fill:#0b7285,color:#fff,stroke:#0b7285,stroke-width:2px;",
            "    classDef section fill:#e3fafc,stroke:#66d9e8,color:#0b7285;",
            "    classDef method fill:#fff3bf,stroke:#fcc419,color:#7c5b00;",
            "    classDef result fill:#d3f9d8,stroke:#69db7c,color:#2b8a3e;",
            "    classDef assumption fill:#ffe3e3,stroke:#ff8787,color:#c92a2a;",
            "    classDef citation fill:#f3f0ff,stroke:#9775fa,color:#5f3dc4;",
        ]
    )
    for n in spec["nodes"]:
        cls = n["group"] if n["group"] in {"root", "section", "method", "result", "assumption", "citation"} else "section"
        lines.append(f'    class {n["id"]} {cls};')
    return "\n".join(lines)


def _write_mermaid_files(out_png: Path, mermaid: str) -> tuple[Path, Path]:
    mmd_path = out_png.with_suffix(".mmd")
    md_path = out_png.with_suffix(".md")
    mmd_path.write_text(mermaid + "\n", encoding="utf-8")
    md_path.write_text(f"# Mind Map\n\n```mermaid\n{mermaid}\n```\n", encoding="utf-8")
    return mmd_path, md_path


def _render_mermaid_cli(mmd_path: Path, out_png: Path) -> bool:
    mmdc = shutil.which("mmdc")
    if not mmdc:
        return False
    cmd = [mmdc, "-i", str(mmd_path), "-o", str(out_png), "-t", "neutral", "-b", "white"]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return out_png.exists() and out_png.stat().st_size > 2000
    except Exception:
        return False


def _render_graphviz(spec: dict, out_png: Path) -> bool:
    color_map = {
        "root": ("#0b7285", "#0b7285", "white"),
        "section": ("#66d9e8", "#e3fafc", "#0b7285"),
        "method": ("#fcc419", "#fff3bf", "#7c5b00"),
        "result": ("#69db7c", "#d3f9d8", "#2b8a3e"),
        "assumption": ("#ff8787", "#ffe3e3", "#c92a2a"),
        "citation": ("#9775fa", "#f3f0ff", "#5f3dc4"),
    }
    try:
        dot = Digraph(comment="PaperCoach Mindmap")
        dot.attr(rankdir="LR", bgcolor="white", splines="spline", nodesep="0.45", ranksep="0.65")
        dot.attr("node", shape="box", style="rounded,filled", fontname="Helvetica", fontsize="11")
        dot.attr("edge", fontname="Helvetica", fontsize="9", color="#666666")

        for n in spec["nodes"]:
            stroke, fill, font = color_map.get(n["group"], color_map["section"])
            dot.node(n["id"], n["label"], color=stroke, fillcolor=fill, fontcolor=font)
        for e in spec["edges"]:
            dot.edge(e["source"], e["target"], label=e["label"])

        rendered = Path(dot.render(filename=out_png.stem, directory=str(out_png.parent), format="png", cleanup=True))
        if rendered != out_png:
            rendered.replace(out_png)
        return out_png.exists() and out_png.stat().st_size > 2000
    except Exception:
        return False


def _render_fitz(spec: dict, out_png: Path) -> None:
    doc = fitz.open()
    page = doc.new_page(width=1400, height=900)
    page.draw_rect(page.rect, fill=(0.985, 0.99, 1.0), color=None)
    page.insert_text((40, 42), "Paper Mind Map", fontsize=28, fontname="helv", color=(0.12, 0.2, 0.3))
    page.insert_text(
        (40, 66),
        "Scope backbone, method flow, assumptions, results, and references",
        fontsize=11,
        fontname="helv",
        color=(0.35, 0.4, 0.45),
    )

    nodes = spec["nodes"]
    edges = spec["edges"]
    id_to_node = {n["id"]: n for n in nodes}

    levels: dict[str, int] = {"root": 0}
    frontier = ["root"]
    parent_map: dict[str, list[str]] = {}
    while frontier:
        cur = frontier.pop(0)
        lvl = levels[cur]
        for e in edges:
            if e["source"] == cur and e["target"] not in levels:
                levels[e["target"]] = lvl + 1
                frontier.append(e["target"])
            parent_map.setdefault(e["target"], []).append(e["source"])
    max_level = max(levels.values()) if levels else 0
    for n in nodes:
        if n["id"] not in levels:
            max_level += 1
            levels[n["id"]] = max_level

    buckets: dict[int, list[str]] = {}
    for nid, lvl in levels.items():
        buckets.setdefault(lvl, []).append(nid)

    pos: dict[str, fitz.Rect] = {}
    left = 40.0
    right = page.rect.width - 40.0
    top = 110.0
    bottom = page.rect.height - 40.0
    levels_sorted = sorted(buckets)
    level_count = max(1, len(levels_sorted))
    x_gap = 24.0
    available_w = right - left
    width = (available_w - x_gap * (level_count - 1)) / level_count
    width = max(150.0, min(230.0, width))
    total_w = width * level_count + x_gap * (level_count - 1)
    x_start = left + max(0.0, (available_w - total_w) / 2.0)
    color_map = {
        "root": ((0.06, 0.4, 0.46), (0.06, 0.4, 0.46), (1.0, 1.0, 1.0)),
        "section": ((0.35, 0.58, 0.76), (0.9, 0.96, 1.0), (0.12, 0.2, 0.3)),
        "method": ((0.89, 0.68, 0.16), (1.0, 0.96, 0.84), (0.35, 0.26, 0.05)),
        "result": ((0.37, 0.73, 0.47), (0.9, 0.98, 0.91), (0.14, 0.36, 0.2)),
        "assumption": ((0.88, 0.41, 0.43), (1.0, 0.92, 0.92), (0.45, 0.12, 0.12)),
        "citation": ((0.51, 0.45, 0.86), (0.95, 0.93, 1.0), (0.25, 0.2, 0.48)),
    }

    for lvl in levels_sorted:
        ids = list(buckets[lvl])
        if lvl > 0:
            ids.sort(
                key=lambda nid: (
                    sum(((pos[p].y0 + pos[p].y1) / 2.0) for p in parent_map.get(nid, []) if p in pos)
                    / max(1, len([p for p in parent_map.get(nid, []) if p in pos])),
                    id_to_node.get(nid, {}).get("label", ""),
                )
            )
        x0 = x_start + lvl * (width + x_gap)
        height = 88.0
        y_gap = 18.0
        available_h = bottom - top
        total_h = len(ids) * height + max(0, len(ids) - 1) * y_gap
        if total_h > available_h:
            height = max(64.0, (available_h - y_gap * max(0, len(ids) - 1)) / max(1, len(ids)))
            total_h = len(ids) * height + max(0, len(ids) - 1) * y_gap
        y_start = top + max(0.0, (available_h - total_h) / 2.0)
        for i, nid in enumerate(ids):
            y0 = y_start + i * (height + y_gap)
            rect = fitz.Rect(x0, y0, x0 + width, y0 + height)
            pos[nid] = rect
            node = id_to_node.get(nid, {"label": nid, "group": "section"})
            stroke, fill, font = color_map.get(node.get("group", "section"), color_map["section"])
            page.draw_rect(rect, color=stroke, fill=fill, width=1.2)
            page.insert_textbox(
                rect + (10, 10, -10, -10),
                str(node.get("label", nid))[:120],
                fontsize=10.5,
                fontname="helv",
                color=font,
            )

    for e in edges:
        if e["source"] not in pos or e["target"] not in pos:
            continue
        a = pos[e["source"]]
        b = pos[e["target"]]
        if a.x0 <= b.x0:
            p0 = (a.x1, (a.y0 + a.y1) / 2)
            p1 = (b.x0, (b.y0 + b.y1) / 2)
        else:
            p0 = (a.x0, (a.y0 + a.y1) / 2)
            p1 = (b.x1, (b.y0 + b.y1) / 2)
        mid_x = (p0[0] + p1[0]) / 2.0
        page.draw_line(p0, (mid_x, p0[1]), color=(0.52, 0.56, 0.6), width=0.9)
        page.draw_line((mid_x, p0[1]), (mid_x, p1[1]), color=(0.52, 0.56, 0.6), width=0.9)
        page.draw_line((mid_x, p1[1]), p1, color=(0.52, 0.56, 0.6), width=0.9)
        if len(edges) <= 14:
            label_pos = (mid_x + 3, (p0[1] + p1[1]) / 2 - 3)
            page.insert_text(label_pos, e["label"][:18], fontsize=7, fontname="helv", color=(0.38, 0.42, 0.46))

    pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    pix.save(str(out_png))
    doc.close()


def generate_mindmap(
    out_png: Path,
    sections: list[dict],
    theorem_nodes: list[dict],
    citations: list[Citation],
    position: str,
    ollama_client=None,
    note_signals: list[dict] | None = None,
) -> MindmapArtifact:
    note_signals = note_signals or []
    fallback = _fallback_spec(sections, theorem_nodes, citations, note_signals)
    llm_spec = _llm_spec(ollama_client, sections, theorem_nodes, citations, note_signals)
    spec = _normalize_spec(llm_spec, fallback)
    if _spec_is_too_generic(spec, sections, note_signals):
        spec = fallback

    mermaid = _to_mermaid(spec)
    mmd_path, _md_path = _write_mermaid_files(out_png, mermaid)

    rendered = _render_mermaid_cli(mmd_path, out_png)
    if not rendered:
        rendered = _render_graphviz(spec, out_png)
    if not rendered:
        _render_fitz(spec, out_png)

    return MindmapArtifact(
        path=str(out_png),
        position=position,
        node_count=len(spec["nodes"]),
        edge_count=len(spec["edges"]),
    )
