from __future__ import annotations

from pathlib import Path

from papercoach.config import ServiceConfig
from papercoach.llm.client import ChatMockClient, TraceWriter


def test_client_repairs_invalid_json_escapes(tmp_path: Path) -> None:
    client = ChatMockClient(
        ServiceConfig(base_url="http://127.0.0.1:8000/v1", api_key="test-key", model="gpt-5"),
        TraceWriter(tmp_path / "trace.jsonl"),
    )

    repaired = client._repair_invalid_json_escapes('{"body":"Use \\(x_t\\) here."}')

    assert repaired == '{"body":"Use \\\\(x_t\\\\) here."}'
