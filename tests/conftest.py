from __future__ import annotations

from contextlib import contextmanager
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import threading

import fitz
import pytest


@pytest.fixture()
def sample_pdf(tmp_path: Path) -> Path:
    pdf_path = tmp_path / "sample.pdf"
    document = fitz.open()
    page = document.new_page()
    title_rect = fitz.Rect(50, 40, 560, 90)
    page.insert_textbox(title_rect, "A Small Study of Reliable Highlighting", fontsize=20)
    abstract_rect = fitz.Rect(50, 110, 560, 220)
    page.insert_textbox(
        abstract_rect,
        "Abstract We propose a highlighting pipeline that identifies method blocks and result claims in research papers. "
        "The system keeps only short study-worthy spans and avoids reference clutter.",
        fontsize=11,
    )
    method_rect = fitz.Rect(50, 240, 560, 370)
    page.insert_textbox(
        method_rect,
        "Method Our method extracts block-level text with word coordinates, asks a model to score the page, "
        "and then aligns a contiguous quote back to the original PDF words. This keeps highlights precise.",
        fontsize=11,
    )
    result_rect = fitz.Rect(50, 390, 560, 510)
    page.insert_textbox(
        result_rect,
        "Results The balanced strategy highlights contribution and result passages while keeping the page readable. "
        "Visual clutter is reduced because the renderer uses translucent overlays.",
        fontsize=11,
    )
    equation_context_rect = fitz.Rect(50, 520, 560, 560)
    page.insert_textbox(
        equation_context_rect,
        "We define the scoring rule where z is the sum of a method score x and a result score y.",
        fontsize=11,
    )
    equation_rect = fitz.Rect(140, 565, 420, 600)
    page.insert_textbox(
        equation_rect,
        "z = x + y",
        fontsize=14,
        align=1,
    )
    equation_label_rect = fitz.Rect(470, 565, 520, 600)
    page.insert_textbox(
        equation_label_rect,
        "(1)",
        fontsize=11,
        align=1,
    )

    reference_page = document.new_page()
    reference_page.insert_textbox(
        fitz.Rect(50, 60, 560, 220),
        "References\n[1] Smith, 2020. Example Work.\n[2] Doe, 2021. Another Work.\n[3] Roe, 2022. More Work.\n"
        "[4] Poe, 2023. Final Work.\n[5] Moe, 2024. Sample Work.\n",
        fontsize=11,
    )

    document.save(pdf_path)
    document.close()
    return pdf_path


class _FakeHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        if self.path == "/v1/models":
            self._write_json({"data": [{"id": "gpt-5"}]})
            return
        self.send_error(404)

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/chat/completions":
            self.send_error(404)
            return
        content_length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        full_text = self._full_text(payload)
        prompt_payload = self._extract_prompt_payload(full_text)
        body = self._document_selection(prompt_payload)
        self._write_json(
            {
                "id": "chatcmpl_fake",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": f"<think>fake</think>{json.dumps(body)}",
                        },
                    }
                ],
            }
        )

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return

    def _write_json(self, body: dict) -> None:
        encoded = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _full_text(self, payload: dict) -> str:
        texts = []
        for item in payload.get("messages", []):
            content = item.get("content")
            if isinstance(content, str):
                texts.append(content)
        return "\n".join(texts)

    def _extract_prompt_payload(self, text: str) -> dict:
        match = re.search(r"PAYLOAD_JSON_START\n(.*)\nPAYLOAD_JSON_END", text, re.DOTALL)
        if not match:
            raise ValueError("Prompt payload missing")
        return json.loads(match.group(1))

    def _document_selection(self, payload: dict) -> dict:
        if payload["task_kind"] == "key_idea_extraction":
            ideas = []
            for index, block in enumerate(sorted(payload["blocks"], key=lambda item: item["word_count"], reverse=True)[: payload["target_ideas"]], start=1):
                text = block["text"].lower()
                if "result" in text:
                    label = "result"
                    title = "Main result"
                elif "method" in text or "align" in text:
                    label = "method"
                    title = "Alignment method"
                elif "propose" in text:
                    label = "contribution"
                    title = "Core contribution"
                else:
                    label = "definition"
                    title = "Study idea"
                ideas.append(
                    {
                        "idea_id": f"idea-{index}",
                        "title": title,
                        "statement": self._choose_quote(block["text"]),
                        "label": label,
                        "block_id": block["block_id"],
                        "confidence": 0.83,
                    }
                )
            return {"ideas": ideas}
        if payload["task_kind"] == "equation_candidate_screen":
            return {
                "candidates": [
                    {
                        "equation_id": item["equation_id"],
                        "keep": "=" in item["equation_text_clean"],
                        "role": "definition",
                        "rationale": "Central displayed equation.",
                        "confidence": 0.86,
                    }
                    for item in payload["candidates"]
                ]
            }
        if payload["task_kind"] == "equation_selection":
            selections = []
            seen_pages: dict[int, int] = {}
            for item in payload["candidates"]:
                page_number = int(item["page_number"])
                if seen_pages.get(page_number, 0) >= int(payload["max_equations_per_page"]):
                    continue
                seen_pages[page_number] = seen_pages.get(page_number, 0) + 1
                selections.append(
                    {
                        "equation_id": item["equation_id"],
                        "role": item["role"],
                        "reason": "Displayed equation is central.",
                        "confidence": 0.87,
                    }
                )
            return {"selections": selections}
        if payload["task_kind"] == "equation_explanation":
            return {
                "explanations": [
                    {
                        "equation_id": item["equation_id"],
                        "title": f"Eq. {item.get('equation_label') or ''} Score definition".strip(),
                        "display_latex": "z = x + y",
                        "symbol_map": {"z": "overall score", "x": "method score", "y": "result score"},
                        "equation_role": item["role"],
                        "plain_explanation": "This equation defines the paper's local score as the sum of method and result contributions.",
                        "intuition_or_consequence": "Increasing either component raises the combined score.",
                        "confidence": 0.9,
                    }
                    for item in payload["equations"]
                ]
            }
        if payload["task_kind"] == "equation_evaluation":
            return {
                "evaluations": [
                    {
                        "equation_id": item["equation_id"],
                        "pass": True,
                        "feedback": "",
                        "confidence": 0.88,
                    }
                    for item in payload["equations"]
                ]
            }
        if payload["task_kind"] == "page_note_generation":
            return {
                "notes": [
                    {
                        "highlight_id": item["highlight_id"],
                        "title": "Why this matters",
                        "body": "This passage states a core point in the local argument and clarifies how it supports the paper's main technical story.",
                        "confidence": 0.84,
                    }
                    for item in payload["highlights"]
                ]
            }
        blocks = payload["blocks"]
        selections = []
        for block in sorted(blocks, key=lambda item: item["word_count"], reverse=True):
            text = block["text"].lower()
            if "result" in text:
                label = "result"
            elif "method" in text or "align" in text:
                label = "method"
            elif "propose" in text:
                label = "contribution"
            else:
                label = "definition"
            selections.append(
                {
                    "block_id": block["block_id"],
                    "label": label,
                    "rationale": "Selected for study value.",
                    "confidence": 0.82,
                    "selected_quote": self._choose_quote(block["text"]),
                }
            )
            if len(selections) >= payload["target_highlights"]:
                break
        return {"selections": selections}

    def _choose_quote(self, text: str) -> str:
        sentences = [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", text) if segment.strip()]
        selected = sentences[0] if sentences else text
        words = selected.split()
        if len(words) > 32:
            selected = " ".join(words[:32])
        return selected


@contextmanager
def _run_fake_server() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/v1"
    finally:
        server.shutdown()
        thread.join()


@pytest.fixture()
def fake_chatmock_base_url() -> str:
    with _run_fake_server() as base_url:
        yield base_url
